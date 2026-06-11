import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from backend.database import init_database
from backend.routers import sessions_router, chat_router
from backend.routers.custom_pets import router as custom_pets_router
from backend.auth import AuthMiddleware
from backend.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_database()
    print("Database initialized")
    yield
    print("Application shutdown")


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