from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.templating import Jinja2Templates

from . import database
from .core.config import Settings, get_active_password, get_settings
from .utils.file_paths import build_file_path

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _serialize_file_for_page(file_info: dict, settings: Settings) -> dict:
    path = build_file_path(file_info["file_id"], file_info["filename"], settings.FILE_ROUTE)
    return {
        **file_info,
        "path": path,
        "url": f"{settings.BASE_URL.strip('/')}{path}",
    }


@router.get("/", response_class=HTMLResponse)
async def main_page(request: Request, settings: Settings = Depends(get_settings)):
    """提供主页，展示文件上传区域和所有文件列表。"""
    files = [_serialize_file_for_page(file_info, settings) for file_info in database.get_all_files()]
    return templates.TemplateResponse("index.html", {"request": request, "files": files})


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """提供设置页面，用于更改密码。"""
    return templates.TemplateResponse("settings.html", {"request": request})


@router.get("/pwd", response_class=HTMLResponse)
async def get_password_page(request: Request):
    """提供密码输入页面。"""
    return templates.TemplateResponse("pwd.html", {"request": request})


@router.post("/pwd")
async def submit_password(password: str = Form(...)):
    """处理密码提交，设置 Cookie 并重定向。"""
    active_password = get_active_password()
    if password == active_password:
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(key="password", value=password, httponly=True, samesite="Lax")
        return response
    return RedirectResponse(url="/pwd?error=1", status_code=303)


@router.get("/image_hosting", response_class=HTMLResponse)
async def image_hosting_page(request: Request, settings: Settings = Depends(get_settings)):
    """提供图床页面，并展示所有已上传图片。"""
    files = [_serialize_file_for_page(file_info, settings) for file_info in database.get_all_files()]
    image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
    images = [
        file_info
        for file_info in files
        if file_info["filename"].lower().endswith(image_extensions)
    ]
    return templates.TemplateResponse("image_hosting.html", {"request": request, "images": images})


@router.get("/share/{file_id}", response_class=HTMLResponse)
async def share_page(request: Request, file_id: str, settings: Settings = Depends(get_settings)):
    """提供文件分享页面，生成下载链接。"""
    file_info = database.get_file_info(file_id)
    if not file_info:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "File not found!"},
            status_code=404,
        )

    serialized_file = _serialize_file_for_page(file_info, settings)
    file_data = {
        "filename": serialized_file["filename"],
        "filesize": serialized_file["filesize"],
        "upload_date": serialized_file["upload_date"],
        "file_url": serialized_file["url"],
        "html_code": f'&lt;a href="{serialized_file["url"]}"&gt;Download {serialized_file["filename"]}&lt;/a&gt;',
        "markdown_code": f'[{serialized_file["filename"]}]({serialized_file["url"]})',
    }
    return templates.TemplateResponse("download.html", {"request": request, "file": file_data})
