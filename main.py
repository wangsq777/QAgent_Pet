import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from backend.database import init_database
from backend.routers import sessions_router, chat_router
from backend.routers.custom_pets import router as custom_pets_router
from backend.auth import AuthMiddleware
from backend.config import settings
from backend.logging_config import get_logger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_database()
    logger.info("Database initialized")
    yield
    logger.info("Application shutdown")


app = FastAPI(
    title="QAgent Pet API",
    description="QQ智能宠物伴侣 Agent API",
    version="1.0.0",
    lifespan=lifespan
)

origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.add_middleware(AuthMiddleware)

# 请求体大小限制（1MB）
class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 1024 * 1024:  # 1MB
            raise HTTPException(status_code=413, detail="Request too large")
        return await call_next(request)

app.add_middleware(MaxBodySizeMiddleware)

# 速率限制
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(sessions_router)
app.include_router(chat_router)
app.include_router(custom_pets_router)

# 挂载静态文件目录
frontend_path = os.path.join(os.path.dirname(__file__), "frontend")
app.mount("/frontend", StaticFiles(directory=frontend_path), name="frontend")


@app.get("/")
async def root():
    return {"message": "QAgent Pet API is running", "version": "1.0.0"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    from backend.config import settings
    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)