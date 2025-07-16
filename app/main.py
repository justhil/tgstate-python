from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from starlette.responses import HTMLResponse, RedirectResponse
from .api import routes as api_routes
from .pages import router as pages_router
from .core.config import get_active_password # 导入新的密码函数
from .bot_handler import create_bot_app
from . import database

# 创建 FastAPI 应用实例
app = FastAPI(
    title="tgState",
    description="一个基于 Telegram 的私有文件存储系统。",
    version="2.0.0"
)

@app.on_event("startup")
async def startup_event():
    """
    应用启动时，初始化数据库并启动 Telegram Bot。
    Bot 将在 FastAPI 的事件循环中作为后台任务运行。
    """
    database.init_db()
    
    try:
        # 创建并初始化 Bot
        bot_app = create_bot_app()
        app.state.bot_app = bot_app
        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling(drop_pending_updates=True)
        print("机器人已在后台启动...")
    except ValueError as e:
        print(f"启动机器人失败: {e}")
        app.state.bot_app = None

@app.on_event("shutdown")
async def shutdown_event():
    """
    应用关闭时，优雅地停止 Telegram Bot。
    """
    if hasattr(app.state, "bot_app") and app.state.bot_app:
        print("正在停止机器人...")
        await app.state.bot_app.updater.stop()
        await app.state.bot_app.stop()
        await app.state.bot_app.shutdown()
        print("机器人已停止。")


# 挂载静态文件
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# 设置模板
templates = Jinja2Templates(directory="app/templates")

# 包含 API 路由
app.include_router(api_routes.router)
app.include_router(pages_router)

@app.middleware("http")
async def password_protection_middleware(request: Request, call_next):
    """
    密码保护中间件。
    - 使用 get_active_password() 获取密码。
    - 保护除公共路径外的所有端点。
    """
    password = get_active_password()
    if password:
        # 定义公共路径
        public_paths = ["/pwd", "/static", "/docs", "/openapi.json", "/api/set-password", "/settings", "/api/upload"]
        
        is_public = any(request.url.path.startswith(path) for path in public_paths)

        if not is_public:
            password_cookie = request.cookies.get("password")
            if password_cookie != password:
                return RedirectResponse(url="/pwd", status_code=307)
    
    response = await call_next(request)
    return response

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """
    提供主 HTML 页面，并列出所有文件。
    """
    files = database.get_all_files()
    return templates.TemplateResponse("index.html", {"request": request, "files": files})

