from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from fastapi.responses import RedirectResponse

# 导入我们的新生命周期管理器和路由
from .core.http_client import lifespan
from .api import routes as api_routes
from .pages import router as pages_router
from .core.config import get_active_password

# 使用集成的 lifespan 管理器创建 FastAPI 应用
app = FastAPI(
    lifespan=lifespan,
    title="tgState",
    description="一个基于 Telegram 的私有文件存储系统。",
    version="2.0.0"
)

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """
    一个全局中间件，用于处理所有页面的访问权限。
    """
    active_password = get_active_password()
    
    # 如果没有设置登录密码，则不进行任何拦截
    if not active_password:
        return await call_next(request)

    # 定义需要密码保护的页面路径
    protected_paths = ["/", "/settings", "/image_hosting"]
    
    # 定义公共路径，这些路径不应被拦截
    public_paths = ["/pwd", "/static", "/api", "/d"]

    request_path = request.url.path
    
    # 检查请求是否是公共路径
    is_public = any(request_path.startswith(p) for p in public_paths)
    
    if not is_public and request_path in protected_paths:
        session_password = request.cookies.get("password")
        if session_password != active_password:
            # 如果密码不匹配，重定向到密码输入页面
            return RedirectResponse(url="/pwd", status_code=307)

    # 如果验证通过或是公共路径，则继续处理请求
    response = await call_next(request)
    return response

# 挂载静态文件目录
# 注意：这个路径是相对于项目根目录的
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# 设置模板目录
# 注意：这个路径也是相对于项目根目录的
templates = Jinja2Templates(directory="app/templates")

# 包含 API 和页面路由
app.include_router(api_routes.router)
app.include_router(pages_router)

