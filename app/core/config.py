import os
from functools import lru_cache
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    """
    应用程序设置。
    """
    BOT_TOKEN: str
    CHANNEL_NAME: str
    PASS_WORD: Optional[str] = None
    PICGO_API_KEY: Optional[str] = None # [可选] PicGo 上传接口的 API 密钥
    BASE_URL: str = "http://127.0.0.1:8000"
    MODE: str = "p" # p 代表公开模式, m 代表私有模式
    FILE_ROUTE: str = "/d/"


@lru_cache()
def get_settings() -> Settings:
    """
    获取应用程序设置。

    此函数会被缓存，以避免在每个请求中都从环境中重新读取设置。
    """
    return Settings()

def get_active_password() -> Optional[str]:
    """
    获取当前有效的密码。
    优先从 .password 文件读取，如果文件不存在，则回退到环境变量。
    """
    password_file = ".password"
    if os.path.exists(password_file):
        with open(password_file, "r", encoding="utf-8") as f:
            password = f.read().strip()
            if password:
                return password
    
    # 如果文件不存在或为空，则回退到环境变量
    return get_settings().PASS_WORD
