from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.templating import Jinja2Templates

from . import database
from .core.config import get_active_password, get_settings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
@router.get("/", response_class=HTMLResponse)
async def main_page(request: Request):
    """
    提供主页，展示文件上传区域和所有文件的列表。
    权限验证已移至全局中间件。
    """
    files = database.get_all_files()
    return templates.TemplateResponse("index.html", {"request": request, "files": files})


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """
    提供设置页面，用于更改密码。
    权限验证已移至全局中间件。
    """
    return templates.TemplateResponse("settings.html", {"request": request})

@router.get("/pwd", response_class=HTMLResponse)
async def get_password_page(request: Request):
    """
    提供密码输入页面。
    """
    return templates.TemplateResponse("pwd.html", {"request": request})

@router.post("/pwd")
async def submit_password(password: str = Form(...)):
    """
    处理密码提交，设置 cookie 并重定向。
    """
    active_password = get_active_password()
    if password == active_password:
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(key="password", value=password, httponly=True, samesite="Lax")
        return response
    else:
        return RedirectResponse(url="/pwd?error=1", status_code=303)

@router.get("/image_hosting", response_class=HTMLResponse)
async def image_hosting_page(request: Request):
    """
    提供图床页面，并展示所有已上传的图片。
    权限验证已移至全局中间件。
    """
    files = database.get_all_files()
    # 定义图片文件后缀
    image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
    # 为模板准备图片数据，包括下载链接，只筛选图片文件
    images = [
        {
            "filename": file["filename"],
            "file_id": file["file_id"],
            "size": file["filesize"],
            "url": f"/d/{file['file_id']}",
            "upload_date": file["upload_date"]
        }
        for file in files if file["filename"].lower().endswith(image_extensions)
    ]
    return templates.TemplateResponse("image_hosting.html", {"request": request, "images": images})


@router.get("/share/{file_id}", response_class=HTMLResponse)
async def share_page(request: Request, file_id: str):
    """
    提供文件分享页面，生成多种格式的下载链接。
    """
    file_info = database.get_file_info(file_id)
    if not file_info:
        return templates.TemplateResponse("error.html", {"request": request, "message": "File not found!"}, status_code=404)

    # 构建完整的文件URL
    base_url = str(request.base_url)
    file_url = f"{base_url}file/{file_id}"

    # 准备传递给模板的数据
    file_data = {
        "filename": file_info["filename"],
        "filesize": file_info["filesize"],
        "upload_date": file_info["upload_date"],
        "file_url": file_url,
        "html_code": f'&lt;a href="{file_url}"&gt;Download {file_info["filename"]}&lt;/a&gt;',
        "markdown_code": f'[{file_info["filename"]}]({file_url})'
    }
    return templates.TemplateResponse("download.html", {"request": request, "file": file_data})
