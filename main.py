import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.database import init_database
from backend.routers import sessions_router, chat_router


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://127.0.0.1:8080", "http://localhost:10000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(sessions_router)
app.include_router(chat_router)


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