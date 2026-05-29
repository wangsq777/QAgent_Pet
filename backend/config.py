from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.minimax.chat/v1"
    LLM_MODEL: str = "MiniMax-M2.5"
    WEATHER_API_KEY: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///./qagent_pet.db"
    PORT: int = 10000

    # Embedding API 配置（默认复用 LLM 的 base_url 和 key）
    EMBEDDING_API_URL: str = ""
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-3-small"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()