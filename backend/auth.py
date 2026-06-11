"""
API Key 认证中间件

通过 Bearer Token 方式验证请求。当 API_KEY 为空时跳过认证（开发模式）。
"""

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from backend.config import settings


EXCLUDED_PATHS = ["/health", "/docs", "/openapi.json", "/redoc"]


class AuthMiddleware(BaseHTTPMiddleware):
    """API Key 认证中间件"""

    async def dispatch(self, request: Request, call_next):
        # 排除健康检查和文档路径
        path = request.url.path
        if path in EXCLUDED_PATHS or path.startswith("/frontend"):
            return await call_next(request)

        # 开发模式跳过
        if not settings.API_KEY:
            return await call_next(request)

        # 从 Authorization header 提取 key
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
        else:
            token = auth

        if token != settings.API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized")

        return await call_next(request)