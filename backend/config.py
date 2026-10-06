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
    # API 协议: "anthropic"（/v1/messages）| "openai"（/chat/completions）
    # "auto" 时按 base_url 自动判断（含 "anthropic" 走 anthropic，否则走 openai）
    LLM_API_PROTOCOL: str = "auto"
    # LLM 调用重试：仅对 429/5xx 与网络错误重试，指数退避 base_delay * 2**attempt
    LLM_RETRY_ATTEMPTS: int = 2
    LLM_RETRY_BASE_DELAY: float = 1.0
    WEATHER_API_KEY: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///./qagent_pet.db"
    PORT: int = 10000

    # API 认证
    API_KEY: str = ""  # 为空时跳过认证（开发模式）

    # CORS 配置
    # 本地开发默认值，生产环境应限制为实际前端域名，如 "https://your-frontend.example.com"
    # "null" 对应桌面端 file:// 面板直连本机 API 时的 Origin
    CORS_ORIGINS: str = "http://localhost:10000,http://127.0.0.1:10000,null"

    # 允许的 Host 头（防 DNS rebinding：浏览器把攻击者域名解析到 127.0.0.1 时，
    # Host 不是回环地址，直接拒绝）。桌面本地部署保持默认即可；
    # 若部署到公网/反向代理后，把实际域名加进来，如 "api.example.com"
    ALLOWED_HOSTS: str = "127.0.0.1,localhost,::1"

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
