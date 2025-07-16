from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

# 导入我们的新生命周期管理器和路由
from .core.http_client import lifespan
from .api import routes as api_routes
from .pages import router as pages_router

# 使用集成的 lifespan 管理器创建 FastAPI 应用
app = FastAPI(
    lifespan=lifespan,
    title="tgState",
    description="一个基于 Telegram 的私有文件存储系统。",
    version="2.0.0"
)

# 挂载静态文件目录
# 注意：这个路径是相对于项目根目录的
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# 设置模板目录
# 注意：这个路径也是相对于项目根目录的
templates = Jinja2Templates(directory="app/templates")

# 包含 API 和页面路由
app.include_router(api_routes.router)
app.include_router(pages_router)

# 根路由重定向到图床页面，方便使用
@app.get("/")
async def read_root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/image_hosting")
