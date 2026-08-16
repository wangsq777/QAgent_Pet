import os

from pydantic_settings import BaseSettings
from typing import Optional


def _settings_file() -> str:
    """Allow the desktop shell to keep secrets in its per-user data directory."""
    return os.getenv("QAGENT_ENV_FILE", ".env")


class Settings(BaseSettings):
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.minimaxi.com/anthropic"
    LLM_MODEL: str = "MiniMax-M2.5"
    WEATHER_API_KEY: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///./qagent_pet.db"
    PORT: int = 10000

    # API 认证
    API_KEY: str = ""  # 为空时跳过认证（开发模式）

    # CORS 配置
    # 本地开发默认值，生产环境应限制为实际前端域名，如 "https://your-frontend.example.com"
    CORS_ORIGINS: str = "http://localhost:10000,http://127.0.0.1:10000"

    # Embedding API 配置（默认复用 LLM 的 base_url 和 key）
    EMBEDDING_API_URL: str = ""
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-3-small"

    # 可信反向代理 CIDR 列表（逗号分隔）。
    # 仅当请求直接来自这些代理时，才信任 X-Forwarded-For / X-Real-IP，
    # 防止客户端伪造这些头部。生产部署在 Render / nginx / Caddy 之后时应配置为代理出口 IP。
    # 留空表示不启用可信代理校验（仅本地开发安全）。
    TRUSTED_PROXIES: str = ""

    # 日志级别
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = _settings_file()
        env_file_encoding = "utf-8"


settings = Settings()
