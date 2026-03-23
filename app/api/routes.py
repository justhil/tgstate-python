import asyncio
import mimetypes
import os
import shutil
import tempfile
from typing import Any, List, Optional
from urllib.parse import quote

import httpx
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from .. import database
from ..core.config import Settings, get_active_password, get_settings
from ..core.http_client import get_http_client
from ..events import (
    publish_file_update,
    subscribe_file_updates,
    unsubscribe_file_updates,
)
from ..services.telegram_service import TelegramService, get_telegram_service
from ..utils.file_paths import build_file_path, extract_file_id_from_value

router = APIRouter()


class PasswordRequest(BaseModel):
    password: str


class BatchDeleteRequest(BaseModel):
    file_ids: List[str]


def _is_web_request(request: Request) -> bool:
    return "referer" in request.headers


def _ensure_request_authorized(
    request: Request,
    settings: Settings,
    submitted_key: str | None = None,
) -> None:
    """统一处理网页端与 API 端的鉴权逻辑。"""
    picgo_api_key = settings.PICGO_API_KEY
    active_password = get_active_password()
    is_web_request = _is_web_request(request)

    auth_ok = False
    error_detail = "验证失败"

    if not active_password and not picgo_api_key:
        auth_ok = True
    elif picgo_api_key and not active_password:
        if is_web_request:
            auth_ok = True
        elif picgo_api_key == submitted_key:
            auth_ok = True
        else:
            error_detail = "无效的 API 密钥"
    elif not picgo_api_key and active_password:
        if is_web_request:
            session_password = request.cookies.get("password")
            if active_password == session_password:
                auth_ok = True
            else:
                error_detail = "需要网页登录"
        else:
            auth_ok = True
    elif active_password and picgo_api_key:
        if is_web_request:
            session_password = request.cookies.get("password")
            if active_password == session_password:
                auth_ok = True
            else:
                error_detail = "需要网页登录"
        elif picgo_api_key == submitted_key:
            auth_ok = True
        else:
            error_detail = "无效的 API 密钥"

    if not auth_ok:
        raise HTTPException(status_code=401, detail=error_detail)


def _serialize_file(file_info: dict[str, Any], settings: Settings) -> dict[str, Any]:
    path = build_file_path(file_info["file_id"], file_info["filename"], settings.FILE_ROUTE)
    url = f"{settings.BASE_URL.strip('/')}{path}"
    return {
        "filename": file_info["filename"],
        "file_id": file_info["file_id"],
        "filesize": file_info["filesize"],
        "upload_date": file_info["upload_date"],
        "path": path,
        "url": url,
    }


def _extract_delete_targets(payload: Any, settings: Settings) -> list[str]:
    """尽量从不同格式的 PicList 请求体中提取 file_id。"""
    collected: list[str] = []

    def visit(value: Any) -> None:
        if value is None:
            return

        if isinstance(value, str):
            file_id = extract_file_id_from_value(value, settings.FILE_ROUTE)
            if file_id:
                collected.append(file_id)
            return

        if isinstance(value, list):
            for item in value:
                visit(item)
            return

        if isinstance(value, dict):
            for key in ("file_id", "fileId", "url", "imgUrl", "path", "src"):
                file_id = extract_file_id_from_value(value.get(key), settings.FILE_ROUTE)
                if file_id:
                    collected.append(file_id)

            for key in ("fullResult", "delete", "list", "items", "data"):
                if key in value:
                    visit(value[key])

    visit(payload)

    deduplicated: list[str] = []
    seen: set[str] = set()
    for file_id in collected:
        if file_id not in seen:
            deduplicated.append(file_id)
            seen.add(file_id)
    return deduplicated


async def _delete_file_and_sync(
    file_id: str,
    telegram_service: TelegramService,
) -> dict[str, Any]:
    """删除 Telegram 主消息后，同步清理数据库并广播删除事件。"""
    delete_result = await telegram_service.delete_file_with_chunks(file_id)
    delete_result["file_id"] = file_id
    error_text = " ".join(
        str(value)
        for value in (delete_result.get("reason"), delete_result.get("error"))
        if value
    ).lower()
    is_not_found_error = "not found" in error_text
    main_message_deleted = bool(delete_result.get("main_message_deleted"))

    if main_message_deleted or is_not_found_error:
        was_deleted_from_db = database.delete_file_metadata(file_id)
        if is_not_found_error:
            delete_result["db_status"] = "deleted_after_not_found"
            delete_result["status"] = "success"
        elif was_deleted_from_db:
            delete_result["db_status"] = "deleted"
        else:
            delete_result["db_status"] = "not_found_in_db"

        await publish_file_update(
            {
                "action": "delete",
                "file_id": file_id,
            }
        )

        message = f"文件 {file_id} 已删除。"
        if delete_result.get("status") == "partial_failure":
            message = (
                f"文件 {file_id} 已从前端列表移除，"
                f"但仍有 {len(delete_result.get('failed_chunks', []))} 个分块删除失败。"
            )
        elif is_not_found_error:
            message = f"文件 {file_id} 在 Telegram 中未找到，已按删除状态完成同步。"

        return {
            "status": "ok",
            "file_id": file_id,
            "message": message,
            "details": delete_result,
        }

    if delete_result.get("status") == "partial_failure":
        raise HTTPException(
            status_code=500,
            detail={
                "file_id": file_id,
                "message": f"文件 {file_id} 删除部分失败。",
                "details": delete_result,
            },
        )

    raise HTTPException(
        status_code=400,
        detail={
            "file_id": file_id,
            "message": f"删除文件 {file_id} 时出错。",
            "details": delete_result,
        },
    )


@router.post("/api/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    key: Optional[str] = Form(None),
    settings: Settings = Depends(get_settings),
    telegram_service: TelegramService = Depends(get_telegram_service),
    x_api_key: Optional[str] = Header(None),
):
    """处理网页与 PicList 的上传请求。"""
    submitted_key = x_api_key or key
    _ensure_request_authorized(request, settings, submitted_key)

    temp_file_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file.filename}") as temp_file:
            temp_file_path = temp_file.name
            shutil.copyfileobj(file.file, temp_file)

        file_id = await telegram_service.upload_file(temp_file_path, file.filename)
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)

    if not file_id:
        raise HTTPException(status_code=500, detail="文件上传失败。")

    file_info = database.get_file_info(file_id)
    if file_info:
        serialized_file = _serialize_file(file_info, settings)
        await publish_file_update({
            "action": "add",
            **serialized_file,
        })
    else:
        serialized_file = {
            "path": build_file_path(file_id, file.filename, settings.FILE_ROUTE),
            "url": f"{settings.BASE_URL.strip('/')}{build_file_path(file_id, file.filename, settings.FILE_ROUTE)}",
            "file_id": file_id,
            "filename": file.filename,
        }

    return {
        "path": serialized_file["path"],
        "url": serialized_file["url"],
        "file_id": file_id,
        "filename": file.filename,
        "delete_api": f"{settings.BASE_URL.strip('/')}/api/delete",
        "fullResult": {
            "file_id": file_id,
            "filename": file.filename,
            "path": serialized_file["path"],
            "url": serialized_file["url"],
            "delete_api": f"{settings.BASE_URL.strip('/')}/api/delete",
        },
    }


@router.get("/d/{file_id}/{filename}")
async def download_file(
    file_id: str,
    filename: str,
    telegram_service: TelegramService = Depends(get_telegram_service),
    client: httpx.AsyncClient = Depends(get_http_client),
):
    """处理单文件与清单文件的下载。"""
    try:
        _, real_file_id = file_id.split(':', 1)
    except ValueError:
        real_file_id = file_id

    download_url = await telegram_service.get_download_url(real_file_id)
    if not download_url:
        raise HTTPException(status_code=404, detail="文件未找到或下载链接已过期。")

    try:
        head_resp = await client.get(download_url, headers={"Range": "bytes=0-127"})
        head_resp.raise_for_status()
        first_bytes = head_resp.content
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"无法连接到 Telegram 服务器: {exc}") from exc

    if first_bytes.startswith(b'tgstate-blob\n'):
        manifest_resp = await client.get(download_url)
        manifest_resp.raise_for_status()
        manifest_content = manifest_resp.content

        lines = manifest_content.decode('utf-8').strip().split('\n')
        original_filename = lines[1]
        chunk_file_ids = lines[2:]
        filename_encoded = quote(str(original_filename), safe="")
        response_headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"
        }
        return StreamingResponse(
            stream_chunks(chunk_file_ids, telegram_service, client),
            headers=response_headers,
        )

    image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
    is_image = filename.lower().endswith(image_extensions)
    content_type, _ = mimetypes.guess_type(filename)
    if content_type is None:
        content_type = "application/octet-stream"

    filename_encoded = quote(str(filename), safe="")
    disposition_type = "inline" if is_image else "attachment"
    response_headers = {
        "Content-Disposition": f"{disposition_type}; filename*=UTF-8''{filename_encoded}",
        "Content-Type": content_type,
    }

    async def single_file_streamer():
        async with client.stream("GET", download_url) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                yield chunk

    return StreamingResponse(single_file_streamer(), headers=response_headers)


@router.get("/api/file-updates")
async def file_updates(request: Request):
    """向所有前端页面广播文件新增和删除事件。"""
    subscriber_queue = await subscribe_file_updates()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    print("客户端已断开连接，停止推送。")
                    break

                try:
                    update_json = await asyncio.wait_for(subscriber_queue.get(), timeout=30)
                    yield {"data": update_json}
                except asyncio.TimeoutError:
                    continue
                except Exception as exc:
                    print(f"推送事件时出错: {exc}")
        finally:
            await unsubscribe_file_updates(subscriber_queue)

    return EventSourceResponse(event_generator())


@router.get("/api/files")
async def get_files_list(settings: Settings = Depends(get_settings)):
    """从数据库获取文件列表。"""
    return [_serialize_file(file_info, settings) for file_info in database.get_all_files()]


@router.delete("/api/files/{file_id}")
async def delete_file(
    file_id: str,
    request: Request,
    key: Optional[str] = None,
    settings: Settings = Depends(get_settings),
    telegram_service: TelegramService = Depends(get_telegram_service),
    x_api_key: Optional[str] = Header(None),
):
    """删除单个文件，并同步前端与 Telegram 侧状态。"""
    _ensure_request_authorized(request, settings, x_api_key or key)
    return await _delete_file_and_sync(file_id, telegram_service)


@router.post("/api/delete")
@router.post("/api/piclist/delete")
async def delete_files_for_piclist(
    request: Request,
    payload: Any = Body(...),
    settings: Settings = Depends(get_settings),
    telegram_service: TelegramService = Depends(get_telegram_service),
    x_api_key: Optional[str] = Header(None),
):
    """兼容 PicList 脚本或自定义请求的删除入口。"""
    key = None
    if isinstance(payload, dict):
        key = payload.get("key")

    _ensure_request_authorized(request, settings, x_api_key or key)
    file_ids = _extract_delete_targets(payload, settings)
    if not file_ids:
        raise HTTPException(status_code=400, detail="请求体中未解析到可删除的 file_id。")

    deleted = []
    failed = []
    for file_id in file_ids:
        try:
            deleted.append(await _delete_file_and_sync(file_id, telegram_service))
        except HTTPException as exc:
            failed.append(exc.detail)

    return {
        "status": "completed",
        "deleted": deleted,
        "failed": failed,
    }


@router.post("/api/set-password")
async def set_password(payload: PasswordRequest):
    """设置或更新应用程序密码。"""
    try:
        with open(".password", "w", encoding="utf-8") as file:
            file.write(payload.password)

        get_settings.cache_clear()
        return JSONResponse(
            status_code=200,
            content={"status": "ok", "message": "密码已成功设置。"},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"无法写入密码文件: {exc}") from exc


@router.post("/api/batch_delete")
async def batch_delete_files(
    request_data: BatchDeleteRequest,
    request: Request,
    key: Optional[str] = None,
    settings: Settings = Depends(get_settings),
    telegram_service: TelegramService = Depends(get_telegram_service),
    x_api_key: Optional[str] = Header(None),
):
    """批量删除文件。"""
    _ensure_request_authorized(request, settings, x_api_key or key)

    successful_deletions = []
    failed_deletions = []
    for file_id in request_data.file_ids:
        try:
            successful_deletions.append(await _delete_file_and_sync(file_id, telegram_service))
        except HTTPException as exc:
            failed_deletions.append(exc.detail)

    return {
        "status": "completed",
        "deleted": successful_deletions,
        "failed": failed_deletions,
    }


async def stream_chunks(
    chunk_composite_ids: list[str],
    telegram_service: TelegramService,
    client: httpx.AsyncClient,
):
    """使用共享客户端流式输出分块文件内容。"""
    for chunk_id in chunk_composite_ids:
        try:
            _, actual_chunk_id = chunk_id.split(':', 1)
        except (ValueError, IndexError):
            print(f"警告: 无效的分块 ID 格式 '{chunk_id}'，已跳过。")
            continue

        chunk_url = await telegram_service.get_download_url(actual_chunk_id)
        if not chunk_url:
            print(f"警告: 无法为分块 {actual_chunk_id} 获取下载链接，已跳过。")
            continue

        try:
            async with client.stream('GET', chunk_url) as chunk_resp:
                if chunk_resp.status_code != 200:
                    print(f"错误: 获取分块 {chunk_id} 失败，状态码: {chunk_resp.status_code}")
                    await asyncio.sleep(1)
                    chunk_url = await telegram_service.get_download_url(actual_chunk_id)
                    if not chunk_url:
                        print(f"重试失败: 无法为分块 {chunk_id} 获取新的下载链接。")
                        break

                    async with client.stream('GET', chunk_url) as retry_resp:
                        retry_resp.raise_for_status()
                        async for chunk_data in retry_resp.aiter_bytes():
                            yield chunk_data
                else:
                    async for chunk_data in chunk_resp.aiter_bytes():
                        yield chunk_data
        except httpx.RequestError as exc:
            print(f"流式传输分块 {chunk_id} 时出现网络错误: {exc}")
            break
