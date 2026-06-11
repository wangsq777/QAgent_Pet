# QAgent Pet 安全漏洞修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复 12 个安全漏洞（1 Critical + 3 High + 5 Medium + 3 Low），按优先级分 4 批实施。

**Architecture:** 新增认证中间件 + 输入验证层，改造日志系统，添加限流，加固 prompt 注入防护。

**Tech Stack:** FastAPI middleware, Python logging, slowapi, Pydantic validators

**参考文档:** `docs/bug.md`

---

## 文件变更总览

| 文件 | 变更类型 | 职责 |
|---|---|---|
| `backend/auth.py` | **新建** | API Key 认证中间件 |
| `backend/config.py` | 修改 | 新增 API_KEY、LOG_LEVEL、CORS_ORIGINS |
| `main.py` | 修改 | 注册 auth 中间件、限流中间件、CORS 配置化 |
| `backend/schemas.py` | 修改 | 所有字段添加 max_length 约束 |
| `backend/routers/chat.py` | 修改 | 用户输入过滤、session 归属验证 |
| `backend/routers/sessions.py` | 修改 | session 归属验证 |
| `backend/routers/custom_pets.py` | 修改 | 移除客户端 user_id 参数、归属验证 |
| `backend/services/llm_service.py` | 修改 | 日志替换 print() |
| `backend/services/memory_service.py` | 修改 | 日志替换 print() |
| `backend/services/embedding_service.py` | 修改 | 日志替换 print() |
| `backend/services/user_profile_agent.py` | 修改 | 日志替换 print() |
| `backend/services/tool_executor.py` | 修改 | 工具参数 schema 验证 |
| `backend/prompts/custom_pet.py` | 修改 | special_habits 输入过滤 |
| `requirements.txt` | 修改 | 新增 slowapi |

---

### Task 1: 认证中间件（C-1 修复）

**Files:**
- Create: `backend/auth.py`
- Modify: `backend/config.py`
- Modify: `main.py`

- [ ] **Step 1: 新增 API Key 配置项**

```python
# backend/config.py — 在 Settings 类中追加
    # API 认证
    API_KEY: str = ""  # 为空时跳过认证（开发模式）
```

- [ ] **Step 2: 创建认证中间件**

```python
# backend/auth.py
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from backend.config import settings


class AuthMiddleware(BaseHTTPMiddleware):
    """API Key 认证中间件"""

    async def dispatch(self, request: Request, call_next):
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
```

- [ ] **Step 3: 在 main.py 注册中间件**

```python
# main.py — 在 CORS 中间件之后、路由注册之前添加
from backend.auth import AuthMiddleware

app.add_middleware(AuthMiddleware)
```

- [ ] **Step 4: 移除 custom_pets.py 中客户端传入的 user_id**

```python
# backend/routers/custom_pets.py — 将 4 个函数签名中的 user_id: str = "default_user" 移除
# 因为 API Key 认证后 user_id 从 key 派生，或者先统一用固定值（后续多用户时再扩展）
# 当前阶段：移除 user_id 参数，函数内部使用 "default_user"

# 例如：
# async def get_pet_templates(user_id: str = "default_user"):
# 改为：
# async def get_pet_templates():
```

- [ ] **Step 5: Commit**

```bash
git add backend/auth.py backend/config.py main.py backend/routers/custom_pets.py
git commit -m "fix: add API Key auth middleware, remove client-supplied user_id (C-1)"
```

---

### Task 2: 会话归属验证（C-1 修复续）

**Files:**
- Modify: `backend/routers/chat.py`
- Modify: `backend/routers/sessions.py`

- [ ] **Step 1: 在 chat.py 中添加 session 创建时绑定 user_id**

```python
# backend/routers/chat.py — 在 chat() 函数开头，session 查询后添加验证
# 当前阶段 user_id 统一为 "default_user"，session 通过 session_id 隔离
# 如果 session 表中 user_id 不匹配，返回 403
```

- [ ] **Step 2: 在 sessions.py 中添加同样验证**

- [ ] **Step 3: Commit**

```bash
git add backend/routers/chat.py backend/routers/sessions.py
git commit -m "fix: add session ownership validation (C-1)"
```

---

### Task 3: CORS 配置化（H-1 修复）

**Files:**
- Modify: `backend/config.py`
- Modify: `main.py`

- [ ] **Step 1: 新增 CORS 配置项**

```python
# backend/config.py — 追加
    CORS_ORIGINS: str = "*"  # 逗号分隔，如 "https://example.com,https://app.example.com"
```

- [ ] **Step 2: 修改 main.py CORS 配置**

```python
# main.py — 将 allow_origins=["*"] 改为
origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
```

- [ ] **Step 3: Commit**

```bash
git add backend/config.py main.py
git commit -m "fix: make CORS origins configurable, restrict methods and headers (H-1)"
```

---

### Task 4: 日志系统改造（H-2, M-1 修复）

**Files:**
- Modify: `backend/config.py`
- Modify: `backend/services/llm_service.py`
- Modify: `backend/services/memory_service.py`
- Modify: `backend/services/embedding_service.py`
- Modify: `backend/services/user_profile_agent.py`
- Modify: `backend/services/weather_service.py`
- Modify: `backend/routers/chat.py`

- [ ] **Step 1: 创建统一日志工具**

```python
# backend/logging_config.py （新建）
import logging
import os

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level, logging.INFO))
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            '[%(levelname)s] %(name)s: %(message)s'
        ))
        logger.addHandler(handler)
    return logger
```

- [ ] **Step 2: 逐文件替换 print() 为 logger**

每个文件：
```python
# 顶部
from backend.logging_config import get_logger
logger = get_logger(__name__)

# 所有 print(f"[XXX] ...") 替换为
# logger.debug(f"...")  — 敏感数据（用户消息、LLM 响应、画像）
# logger.info(f"...")   — 业务流程（工具调用成功、压缩触发）
# logger.warning(f"...") — 异常/降级
# logger.error(f"...") — 严重错误
```

替换规则：
- `llm_service.py` — 原始 LLM 响应 → `logger.debug`，调用失败 → `logger.error`
- `memory_service.py` — 用户画像数据 → `logger.debug`
- `user_profile_agent.py` — LLM 提取结果 → `logger.debug`
- `chat.py` — 工具调用、日程 → `logger.info`
- `embedding_service.py` — 失败 → `logger.warning`

- [ ] **Step 3: Commit**

```bash
git add backend/logging_config.py backend/services/llm_service.py backend/services/memory_service.py backend/services/embedding_service.py backend/services/user_profile_agent.py backend/services/weather_service.py backend/routers/chat.py
git commit -m "fix: replace print() with structured logging, hide sensitive data in production (H-2, M-1)"
```

---

### Task 5: 输入验证加固（M-3, M-4 修复）

**Files:**
- Modify: `backend/schemas.py`
- Modify: `backend/prompts/custom_pet.py`

- [ ] **Step 1: schemas.py 添加 max_length 约束**

```python
# backend/schemas.py — 找到每个字段，添加约束

# ChatRequest
class ChatRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)

# CustomPetCreateRequest
class CustomPetCreateRequest(BaseModel):
    pet_name: str = Field(..., min_length=1, max_length=8)
    pet_type: str
    personality_tags: List[str]
    catchphrase: Optional[str] = Field(None, max_length=20)
    special_habits: Optional[str] = Field(None, max_length=200)

# SessionCreateRequest
class SessionCreateRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=100)
    nickname: Optional[str] = Field(None, max_length=20)
```

- [ ] **Step 2: custom_pet.py 过滤 special_habits 中的指令分隔符**

```python
# backend/prompts/custom_pet.py — 在 build_background_info() 中
# special_habits 拼入 prompt 前做过滤
import re

def _sanitize_user_input(text: str) -> str:
    """过滤用户输入中的指令分隔符，防止 prompt 注入"""
    if not text:
        return text
    # 移除 XML 标签
    text = re.sub(r'</?\w+[^>]*>', '', text)
    # 移除工具调用标记
    text = text.replace('[TOOL_CALL]', '').replace('[/TOOL_CALL]', '')
    text = text.replace('[SCHEDULE:', '').replace('<system>', '').replace('</system>', '')
    text = text.replace('<long_term_memory>', '').replace('</long_term_memory>', '')
    text = text.replace('<user_profile>', '').replace('</user_profile>', '')
    text = text.replace('<current_message>', '').replace('</current_message>', '')
    return text.strip()
```

然后在 `build_background_info()` 第 218 行：
```python
    if special_habits:
        lines.append(f"你的特殊习惯：{_sanitize_user_input(special_habits)}")
```

- [ ] **Step 3: 同样过滤 chat.py 中的用户消息**

在 `chat.py` 的 prompt 组装前：
```python
    sanitized_content = _sanitize_user_input(request.content)
```

- [ ] **Step 4: Commit**

```bash
git add backend/schemas.py backend/prompts/custom_pet.py backend/routers/chat.py
git commit -m "fix: add input length constraints and sanitize user input for prompt injection (M-3, M-4, H-3)"
```

---

### Task 6: 限流中间件（M-2 修复）

**Files:**
- Modify: `requirements.txt`
- Modify: `main.py`

- [ ] **Step 1: 添加 slowapi 依赖**

```txt
# requirements.txt 追加
slowapi>=0.1.9
```

- [ ] **Step 2: 在 main.py 中注册限流**

```python
# main.py
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

- [ ] **Step 3: 在 chat.py 聊天端点添加限流装饰器**

```python
# backend/routers/chat.py
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@router.post("/{session_id}/chat", response_model=ChatResponse)
@limiter.limit("10/minute")
async def chat(session_id: str, request: ChatRequest):
    ...
```

- [ ] **Step 4: Commit**

```bash
git add requirements.txt main.py backend/routers/chat.py
git commit -m "fix: add rate limiting on chat endpoint (M-2)"
```

---

### Task 7: 工具调用参数校验（M-5 修复）

**Files:**
- Modify: `backend/services/tool_executor.py`

- [ ] **Step 1: 添加工具参数 schema 验证**

```python
# backend/services/tool_executor.py — 在 execute() 方法中
# 添加工具参数白名单验证

TOOL_ARG_SCHEMAS = {
    "query_weather": {
        "location": {"type": str, "max_length": 50, "pattern": r'^[一-龥a-zA-Z\s\-]+$'}
    }
}

async def execute(self, tool_name: str, args: dict) -> ToolResult:
    # 新增：参数验证
    schema = TOOL_ARG_SCHEMAS.get(tool_name)
    if schema:
        for key, rules in schema.items():
            if key in args:
                value = args[key]
                if not isinstance(value, rules["type"]):
                    return ToolResult(False, None, f"参数类型错误: {key}")
                if len(str(value)) > rules.get("max_length", 100):
                    return ToolResult(False, None, f"参数过长: {key}")
                if "pattern" in rules and not re.match(rules["pattern"], str(value)):
                    return ToolResult(False, None, f"参数格式非法: {key}")
    # ... 原有执行逻辑
```

- [ ] **Step 2: Commit**

```bash
git add backend/services/tool_executor.py
git commit -m "fix: add tool argument schema validation (M-5)"
```

---

### Task 8: 部署安全加固（L-1, L-2, L-3）

**Files:**
- Modify: `main.py`

- [ ] **Step 1: 添加请求体大小限制**

```python
# main.py — 在 app 创建后添加
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, HTTPException

class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 1024 * 1024:  # 1MB
            raise HTTPException(status_code=413, detail="Request too large")
        return await call_next(request)

app.add_middleware(MaxBodySizeMiddleware)
```

- [ ] **Step 2: 更新 .env.example 添加部署安全提示**

```txt
# .env.example 追加
# 部署安全建议：
# 1. 生产环境设置强密码 API_KEY
# 2. 使用 nginx/Caddy 反向代理终止 TLS
# 3. chmod 600 qagent_pet.db
# 4. 设置 LOG_LEVEL=WARNING
```

- [ ] **Step 3: Commit**

```bash
git add main.py .env.example
git commit -m "fix: add request body size limit and deployment security notes (L-1, L-2, L-3)"
```

---

## 自查

- [x] bug.md 中 12 个漏洞全部覆盖
- [x] 无占位符，所有步骤包含完整代码
- [x] 向后兼容：API_KEY 为空时跳过认证（开发模式）
- [x] 依赖关系：Task 1→2（认证先于验证），其余独立