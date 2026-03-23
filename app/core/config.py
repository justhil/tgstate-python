import os
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用程序设置。"""

    BOT_TOKEN: str
    CHANNEL_NAME: str
    PASS_WORD: Optional[str] = None
    PICGO_API_KEY: Optional[str] = None
    BASE_URL: str = "http://127.0.0.1:8000"
    MODE: str = "p"
    FILE_ROUTE: str = "/d"

    # 可选的 MTProto 同步配置，用于补齐群组手动删除后的前端同步。
    TG_API_ID: Optional[int] = None
    TG_API_HASH: Optional[str] = None
    TELEGRAM_SYNC_SESSION: str = "tgstate-sync"
    TELEGRAM_RECONCILE_INTERVAL: int = 60


@lru_cache()
def get_settings() -> Settings:
    """获取应用程序设置，并对结果做缓存。"""
    return Settings()


def get_active_password() -> Optional[str]:
    """
    获取当前有效的密码。
    优先从 `.password` 文件读取，如果文件不存在，则回退到环境变量。
    """
    password_file = ".password"
    if os.path.exists(password_file):
        with open(password_file, "r", encoding="utf-8") as file:
            password = file.read().strip()
            if password:
                return password

    return get_settings().PASS_WORD
