from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.minimax.chat/v1"
    LLM_MODEL: str = "MiniMax-Text-01"
    LLM_MODEL_BACKUP: Optional[str] = "MiniMax-Text-01-Turbo"
    WEATHER_API_KEY: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///./qagent_pet.db"
    PORT: int = 10000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()