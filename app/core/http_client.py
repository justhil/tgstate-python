import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI

# 导入应用所需的其他模块
from .. import database
from ..bot_handler import create_bot_app

# 这个变量将持有我们全局共享的客户端实例
http_client: httpx.AsyncClient | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理器。
    在应用启动时：
    1. 初始化数据库。
    2. 创建并启动 Telegram Bot。
    3. 创建一个共享的、支持高并发的 httpx.AsyncClient。
    在应用关闭时：
    1. 优雅地关闭 httpx.AsyncClient。
    2. 优雅地停止 Telegram Bot。
    """
    # --- 启动逻辑 ---
    print("🚀 应用启动...")
    
    # 1. 初始化数据库
    database.init_db()
    print("✔️ 数据库已初始化。")

    # 2. 创建共享的 httpx.AsyncClient
    global http_client
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    http_client = httpx.AsyncClient(timeout=300.0, limits=limits)
    print("✔️ 共享的 HTTP 客户端已创建。")

    # 3. 启动 Telegram Bot
    try:
        bot_app = create_bot_app()
        app.state.bot_app = bot_app
        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling(drop_pending_updates=True)
        print("✔️ 机器人已在后台启动...")
    except ValueError as e:
        print(f"❌ 启动机器人失败: {e}")
        app.state.bot_app = None

    yield # 应用在此处运行

    # --- 关闭逻辑 ---
    print("🔌 应用关闭...")

    # 1. 关闭共享的 httpx.AsyncClient
    if http_client:
        await http_client.aclose()
        print("✔️ 共享的 HTTP 客户端已关闭。")

    # 2. 停止 Telegram Bot
    if hasattr(app.state, "bot_app") and app.state.bot_app:
        print("正在停止机器人...")
        await app.state.bot_app.updater.stop()
        await app.state.bot_app.stop()
        await app.state.bot_app.shutdown()
        print("✔️ 机器人已停止。")


def get_http_client() -> httpx.AsyncClient:
    """
    一个 FastAPI 依赖项，用于获取共享的 httpx 客户端实例。
    """
    if http_client is None:
        raise RuntimeError("HTTP client is not initialized. Is the app lifespan configured correctly?")
    return http_client