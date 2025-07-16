import httpx
import tempfile
import os
import shutil
import mimetypes
from urllib.parse import quote
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Response, Request, Header, Form
from pydantic import BaseModel
from typing import List, Optional
from fastapi.responses import StreamingResponse, JSONResponse
from ..core.config import Settings, get_settings, get_active_password
from ..services.telegram_service import TelegramService, get_telegram_service
from ..core.http_client import get_http_client # 导入共享客户端

router = APIRouter()

@router.post("/api/upload")
async def upload_file(
    request: Request, # 引入 Request 对象以访问 cookie
    file: UploadFile = File(...),
    key: Optional[str] = Form(None), # 从表单中获取 key
    settings: Settings = Depends(get_settings),
    telegram_service: TelegramService = Depends(get_telegram_service),
    x_api_key: Optional[str] = Header(None) # 从请求头中获取 x-api-key
):
    """
    处理文件上传。
    此端点现在支持两种验证方式：
    1. API 密钥：通过 x-api-key (Header) 或 key (Form) 提供。
    2. Cookie 验证：通过检查已登录用户的会话 cookie。
    如果未设置任何密码，则允许匿名上传。
    """
    # 获取配置的密码
    picgo_api_key = settings.PICGO_API_KEY
    active_password = get_active_password()
    submitted_key = x_api_key or key

    # 修正后的验证逻辑
    # 通过 'Referer' 头来区分网页端和 API 端的请求
    is_web_request = "referer" in request.headers

    auth_ok = False
    error_detail = "验证失败"

    # 1. 两个密码都【没有】设置：完全开放
    if not active_password and not picgo_api_key:
        auth_ok = True

    # 2. 只设置了【Picogo密码】：网页开放，API需验证
    elif picgo_api_key and not active_password:
        if is_web_request:
            auth_ok = True  # 网页请求无条件允许
        else:
            if picgo_api_key == submitted_key:
                auth_ok = True  # API 请求验证密钥
            else:
                error_detail = "无效的 API 密钥"

    # 3. 只设置了【登录密码】：网页需登录，API开放
    elif not picgo_api_key and active_password:
        if is_web_request:
            session_password = request.cookies.get("password")
            if active_password == session_password:
                auth_ok = True  # 网页请求验证会话
            else:
                error_detail = "需要网页登录"
        else:
            auth_ok = True  # API 请求无条件允许

    # 4. 两个密码都【设置了】：网页和 API 都需要验证
    elif active_password and picgo_api_key:
        if is_web_request:
            session_password = request.cookies.get("password")
            if active_password == session_password:
                auth_ok = True
            else:
                error_detail = "需要网页登录"
        else:
            if picgo_api_key == submitted_key:
                auth_ok = True
            else:
                error_detail = "无效的 API 密钥"

    if not auth_ok:
        raise HTTPException(status_code=401, detail=error_detail)
    temp_file_path = None
    try:
        # 使用 tempfile 创建一个安全的临时文件
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file.filename}") as temp_file:
            temp_file_path = temp_file.name
            # 将上传的文件内容写入临时文件
            shutil.copyfileobj(file.file, temp_file)

        file_id = await telegram_service.upload_file(temp_file_path, file.filename)
    finally:
        # 确保临时文件在操作后被删除
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)

    if file_id:
        encoded_filename = quote(file.filename)
        file_path = f"/d/{file_id}/{encoded_filename}" # 关键变更：将文件名添加到URL中
        full_url = f"{settings.BASE_URL.strip('/')}{file_path}"
        return {"path": file_path, "url": str(full_url)}
    else:
        raise HTTPException(status_code=500, detail="文件上传失败。")

@router.get("/d/{file_id}/{filename}")
async def download_file(
    file_id: str, # Note: This can be a composite ID "message_id:file_id"
    filename: str, # 关键变更：从URL中获取原始文件名
    telegram_service: TelegramService = Depends(get_telegram_service),
    client: httpx.AsyncClient = Depends(get_http_client) # 注入共享客户端
):
    """
    处理文件下载。
    该函数实现了对清单文件和单个文件的真正流式处理，并确保文件名正确。
    """
    # 从复合ID中提取真实的 file_id，同时保持对旧格式的兼容性
    try:
        _, real_file_id = file_id.split(':', 1)
    except ValueError:
        real_file_id = file_id # 假定是旧格式

    download_url = await telegram_service.get_download_url(real_file_id)
    if not download_url:
        raise HTTPException(status_code=404, detail="文件未找到或下载链接已过期。")

    # 使用共享客户端进行范围请求，检查文件类型
    range_headers = {"Range": "bytes=0-127"}
    try:
        head_resp = await client.get(download_url, headers=range_headers)
        head_resp.raise_for_status()
        first_bytes = head_resp.content
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"无法连接到 Telegram 服务器: {e}")

    # 检查是否是清单文件
    if first_bytes.startswith(b'tgstate-blob\n'):
        # 是清单文件，使用共享客户端下载整个清单来解析
        manifest_resp = await client.get(download_url)
        manifest_resp.raise_for_status()
        manifest_content = manifest_resp.content
        
        lines = manifest_content.decode('utf-8').strip().split('\n')
        original_filename = lines[1]
        chunk_file_ids = lines[2:]
        
        filename_encoded = quote(str(original_filename))
        response_headers = {
            'Content-Disposition': f"attachment; filename*=UTF-8''{filename_encoded}"
        }
        # 将共享客户端传递给分块流式传输器
        return StreamingResponse(stream_chunks(chunk_file_ids, telegram_service, client), headers=response_headers)
    else:
        # 是单个文件，直接流式传输
        # 关键变更：文件名现在直接从URL参数中获取，不再需要数据库查询。

        # 检查文件是否为图片
        image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
        is_image = filename.lower().endswith(image_extensions)
        
        filename_encoded = quote(str(filename))
        
        # 动态获取 Content-Type
        content_type, _ = mimetypes.guess_type(filename)
        if content_type is None:
            content_type = "application/octet-stream"  # 如果无法猜测，则使用默认值

        # 根据是否为图片设置不同的 Content-Disposition
        disposition_type = "inline" if is_image else "attachment"
        response_headers = {
            'Content-Disposition': f"{disposition_type}; filename*=UTF-8''{filename_encoded}",
            'Content-Type': content_type,  # 关键修复：添加 Content-Type 头
        }

        async def single_file_streamer():
            # 使用共享客户端进行流式传输
            async with client.stream("GET", download_url) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    yield chunk
        
        return StreamingResponse(single_file_streamer(), headers=response_headers)

from .. import database
from ..events import file_update_queue
import asyncio
from sse_starlette.sse import EventSourceResponse

@router.get("/api/file-updates")
async def file_updates(request: Request):
    """
    一个 SSE 端点，用于向客户端实时推送新文件通知。
    """
    async def event_generator():
        while True:
            # 检查客户端是否已断开连接
            if await request.is_disconnected():
                print("客户端已断开连接，停止推送。")
                break
            
            try:
                # 等待队列中的新消息，设置一个超时以定期检查连接状态
                update_json = await asyncio.wait_for(file_update_queue.get(), timeout=30)
                yield {"data": update_json}
                file_update_queue.task_done()
            except asyncio.TimeoutError:
                # 超时是正常的，只是为了让我们有机会检查 is_disconnected
                continue
            except Exception as e:
                print(f"推送事件时出错: {e}")

    return EventSourceResponse(event_generator())

@router.get("/api/files")
async def get_files_list():
    """
    从数据库获取文件列表。
    """
    files = database.get_all_files()
    return files

@router.delete("/api/files/{file_id}")
async def delete_file(
    file_id: str, # Note: This is the composite ID "message_id:file_id"
    telegram_service: TelegramService = Depends(get_telegram_service)
):
    """
    完全删除一个文件，包括其所有分块（如果存在）。
    """
    # 步骤 1: 调用新的、更全面的删除服务
    delete_result = await telegram_service.delete_file_with_chunks(file_id)

    # 步骤 2: 检查删除结果，特别是处理“未找到”的情况
    # 关键逻辑：如果 TG 返回“未找到”，我们应将其视为成功，并确保数据库同步
    is_not_found_error = "not found" in delete_result.get("error", "").lower()

    if delete_result.get("main_message_deleted") or is_not_found_error:
        # 如果 TG 确认删除，或者返回“未找到”，我们都清理数据库
        was_deleted_from_db = database.delete_file_metadata(file_id)
        
        if is_not_found_error:
            print(f"文件 {file_id} 在 Telegram 中未找到，视为已删除。正在清理数据库...")
            delete_result["db_status"] = "deleted_after_not_found"
            # 强制将状态置为成功，以便前端正确处理
            delete_result["status"] = "success"
        elif not was_deleted_from_db:
            delete_result["db_status"] = "not_found_in_db"
            print(f"警告: 文件 {file_id} 在 Telegram 中已删除，但在数据库中未找到。")
        else:
            delete_result["db_status"] = "deleted"
    else:
        # 仅在删除失败且不是“未找到”错误时，才跳过数据库操作
        delete_result["db_status"] = "skipped_due_to_tg_error"

    # 步骤 3: 根据最终状态返回响应
    if delete_result["status"] == "success":
        # 包含了正常删除和“未找到”的情况
        return {"status": "ok", "message": f"文件 {file_id} 已成功处理。", "details": delete_result}
    
    elif delete_result["status"] == "partial_failure":
        raise HTTPException(
            status_code=500,
            detail={
                "message": f"文件 {file_id} 删除部分失败。",
                "details": delete_result
            }
        )
    else: # 'error'
        # 现在只有真正的、非“未找到”的错误才会走到这里
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"删除文件 {file_id} 时出错。",
                "details": delete_result
            }
        )


class PasswordRequest(BaseModel):
    password: str

class BatchDeleteRequest(BaseModel):
    file_ids: List[str]

@router.post("/api/set-password")
async def set_password(payload: PasswordRequest):
    """
    设置或更新应用程序密码。
    密码将存储在 .password 文件中，覆盖通过 .env 设置的密码。
    """
    try:
        with open(".password", "w", encoding="utf-8") as f:
            f.write(payload.password)
        
        # 清除 get_settings 的缓存，以防万一（尽管新逻辑绕过了它）
        get_settings.cache_clear()
        
        return JSONResponse(
            status_code=200,
            content={"status": "ok", "message": "密码已成功设置。"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"无法写入密码文件: {e}")

@router.post("/api/batch_delete")
async def batch_delete_files(
    request_data: BatchDeleteRequest,
    telegram_service: TelegramService = Depends(get_telegram_service)
):
    """
    批量、完全地删除文件，包括它们的所有分块。
    """
    successful_deletions = []
    failed_deletions = []

    for file_id in request_data.file_ids:
        try:
            # 调用重构后的单个文件删除逻辑
            response = await delete_file(file_id, telegram_service)
            successful_deletions.append(response)
        except HTTPException as e:
            failed_deletions.append(e.detail)
            
    return {
        "status": "completed",
        "deleted": successful_deletions,
        "failed": failed_deletions
    }


async def stream_chunks(chunk_composite_ids, telegram_service: TelegramService, client: httpx.AsyncClient):
    """一个使用共享客户端的异步生成器，用于流式传输分块。"""
    for chunk_id in chunk_composite_ids:
        try:
            # 关键变更：从复合ID "message_id:actual_file_id" 中解析出 actual_file_id
            _, actual_chunk_id = chunk_id.split(':', 1)
        except (ValueError, IndexError):
            print(f"警告：无效的分块ID格式 '{chunk_id}'，跳过。")
            continue

        # 关键修复：在每次循环时都实时获取最新的下载链接
        chunk_url = await telegram_service.get_download_url(actual_chunk_id)
        if not chunk_url:
            print(f"警告：无法为分块 {actual_chunk_id} 获取下载链接，跳过。")
            continue
        
        print(f"正在流式传输分块 {chunk_id} 从 URL: {chunk_url[:50]}...")
        try:
            async with client.stream('GET', chunk_url) as chunk_resp:
                # 检查状态码，以防链接过期
                if chunk_resp.status_code != 200:
                    print(f"错误：获取分块 {chunk_id} 失败，状态码: {chunk_resp.status_code}")
                    # 尝试为这个分块重新获取一次URL
                    print("正在尝试重新获取URL...")
                    await asyncio.sleep(1) # 短暂等待
                    chunk_url = await telegram_service.get_download_url(actual_chunk_id) # 使用 actual_chunk_id
                    if not chunk_url:
                        print(f"重试失败：无法为分块 {chunk_id} 获取新的URL。")
                        break
                    
                    # 使用新的URL重试
                    async with client.stream('GET', chunk_url) as retry_resp:
                        retry_resp.raise_for_status()
                        async for chunk_data in retry_resp.aiter_bytes():
                            yield chunk_data
                else:
                    async for chunk_data in chunk_resp.aiter_bytes():
                        yield chunk_data

        except httpx.RequestError as e:
            print(f"流式传输分块 {chunk_id} 时出现网络错误: {e}")
            break
