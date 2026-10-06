"""
API Key 认证中间件

通过 Bearer Token 方式验证请求。当 API_KEY 为空时跳过认证（开发模式）。
"""

import re
import secrets
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from backend.config import settings
from backend.logging_config import get_logger

logger = get_logger(__name__)

EXCLUDED_PATHS = ["/health", "/docs", "/openapi.json", "/redoc"]

# X-User-Id 格式：1-64 位，仅允许字母、数字、下划线、连字符
USER_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')


class AuthMiddleware(BaseHTTPMiddleware):
    """API Key 认证中间件"""

    async def dispatch(self, request: Request, call_next):
        # Host 白名单：防 DNS rebinding（攻击者域名解析到 127.0.0.1 时 Host 不在白名单内）
        host_header = (request.headers.get("host") or "").strip().lower()
        if host_header.startswith("[") and "]" in host_header:  # IPv6 字面量 [::1]:port
            host = host_header[1:host_header.index("]")]
        else:
            host = host_header.split(":")[0]
        allowed_hosts = {h.strip().lower() for h in settings.ALLOWED_HOSTS.split(",") if h.strip()}
        if allowed_hosts and host not in allowed_hosts:
            return JSONResponse(status_code=403, content={"detail": "Forbidden host"})

        # 排除健康检查和文档路径
        path = request.url.path
        if path in EXCLUDED_PATHS or path.startswith("/frontend"):
            return await call_next(request)

        # 从 X-User-Id 请求头提取用户身份，存入 request.state
        user_id = request.headers.get("X-User-Id", "")
        if not user_id:
            user_id = "anonymous"  # 未提供时 fallback
        elif not USER_ID_PATTERN.match(user_id):
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid X-User-Id format (must be 1-64 chars, alphanumeric/underscore/hyphen)"}
            )
        request.state.user_id = user_id
        request.state.auth_disabled = not settings.API_KEY

        # 开发模式跳过（API_KEY 未配置时输出警告）
        if not settings.API_KEY:
            logger.warning("API_KEY not configured -- authentication is disabled, all requests are accepted")
            return await call_next(request)

        # 从 Authorization header 提取 key
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
        else:
            token = auth

        if not secrets.compare_digest(token, settings.API_KEY):
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"}
            )

        return await call_next(request)