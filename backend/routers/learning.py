"""
陪我学：学习功能 API 路由

提供：
- POST /api/learning/analyze        分析 GitHub 项目并生成大纲
- POST /api/learning/sessions        创建学习会话
- GET  /api/learning/sessions/{id}   获取学习会话详情（刷新恢复用）
- POST /api/learning/sessions/{id}/chapters/{chapter_id}/teach  章节讲解
- POST /api/learning/sessions/{id}/ask   用户提问（teacher / pet）
- POST /api/learning/sessions/{id}/pause   暂停学习
- POST /api/learning/sessions/{id}/complete  完成学习并结算奖励

所有接口校验学习会话归属当前 request.state.user_id，自定义宠物校验所有权。
"""

import re
import uuid
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from backend.database import get_db
from backend.services.learning_service import learning_service, LearningError
from backend.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/learning", tags=["learning"])
limiter = Limiter(key_func=get_remote_address)

UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE
)

PRESET_PET_IDS = {"hot_dog", "cold_cat", "mouse"}


def _validate_uuid(value: str, field_name: str = "id") -> None:
    if not value or not UUID_PATTERN.match(value):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name} format")


def _learning_error_to_http(e: LearningError) -> HTTPException:
    return HTTPException(status_code=e.status, detail=e.message)


async def _verify_pet_access(user_id: str, pet_id: str) -> str:
    """
    校验当前用户可使用该宠物，返回 pet_source('preset'/'custom')。
    预置宠物公开可用；自定义宠物需归属当前用户。
    """
    if pet_id in PRESET_PET_IDS:
        return "preset"
    # 自定义宠物：校验归属
    _validate_uuid(pet_id, "pet_id")
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT pet_id FROM custom_pets WHERE pet_id = ? AND user_id = ?",
            (pet_id, user_id)
        )
        if not await cursor.fetchone():
            raise HTTPException(status_code=403, detail="无权访问该自定义宠物")
    return "custom"


async def _get_session_and_check_owner(session_id: str, user_id: str) -> dict:
    """取学习会话并校验归属。"""
    row = await learning_service.get_session_row(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="学习会话不存在")
    if row["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="无权访问该学习会话")
    return row


# ============ Schemas ============

class OutlineChapter(BaseModel):
    chapter_id: int
    title: str = Field(..., min_length=1, max_length=100)
    learning_goal: str = Field("", max_length=200)
    focus_paths: List[str] = Field(default_factory=list, max_length=6)


class AnalyzeRequest(BaseModel):
    pet_id: str = Field(..., min_length=1, max_length=64)
    github_url: str = Field(..., min_length=1, max_length=500)


class CreateSessionRequest(BaseModel):
    pet_id: str = Field(..., min_length=1, max_length=64)
    github_url: str = Field(..., min_length=1, max_length=500)
    outline: List[OutlineChapter] = Field(..., min_length=1, max_length=6)


class AskRequest(BaseModel):
    target: str = Field(..., pattern="^(teacher|pet)$")
    question: str = Field(..., min_length=1, max_length=1000)
    chapter_id: Optional[int] = None


# ============ 端点 ============

@router.post("/analyze")
@limiter.limit("5/minute")
async def analyze(body: AnalyzeRequest, request: Request):
    """分析 GitHub 项目并生成学习大纲。"""
    user_id = request.state.user_id
    await _verify_pet_access(user_id, body.pet_id)

    try:
        outline = await learning_service.generate_outline(body.github_url)
    except LearningError as e:
        raise _learning_error_to_http(e)
    except Exception as e:
        logger.exception("analyze failed: %s", e)
        raise HTTPException(status_code=500, detail="分析项目失败，请稍后重试")

    return outline


@router.post("/sessions")
@limiter.limit("5/minute")
async def create_session(body: CreateSessionRequest, request: Request):
    """创建学习会话。"""
    user_id = request.state.user_id
    pet_source = await _verify_pet_access(user_id, body.pet_id)

    # 章节数限制
    if len(body.outline) < 1 or len(body.outline) > 6:
        raise HTTPException(status_code=400, detail="章节数需在 1-6 之间")

    try:
        result = await learning_service.create_session(
            user_id=user_id,
            pet_id=body.pet_id,
            pet_source=pet_source,
            github_url=body.github_url,
            outline=[c.model_dump() for c in body.outline],
        )
    except LearningError as e:
        raise _learning_error_to_http(e)
    return result


@router.get("/sessions/{session_id}")
@limiter.limit("60/minute")
async def get_session_detail(session_id: str, request: Request):
    """获取学习会话详情（含大纲、进度、消息，用于刷新恢复）。"""
    user_id = request.state.user_id
    _validate_uuid(session_id, "session_id")

    # 统一走归属校验：预置宠物会话同样只允许创建者本人读取（含历史问答等用户数据）
    row = await learning_service.get_session_row(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="学习会话不存在")
    if row["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="无权访问该学习会话")

    detail = await learning_service.get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="学习会话不存在")
    return detail


@router.post("/sessions/{session_id}/chapters/{chapter_id}/teach")
@limiter.limit("10/minute")
async def teach_chapter(session_id: str, chapter_id: int, request: Request):
    """生成或读取章节讲解 + 宠物章末旁白。"""
    user_id = request.state.user_id
    _validate_uuid(session_id, "session_id")
    if chapter_id < 1 or chapter_id > 99:
        raise HTTPException(status_code=400, detail="Invalid chapter_id")

    await _get_session_and_check_owner(session_id, user_id)

    try:
        result = await learning_service.teach_chapter(session_id, chapter_id)
    except LearningError as e:
        raise _learning_error_to_http(e)
    except Exception as e:
        logger.exception("teach_chapter failed: %s", e)
        raise HTTPException(status_code=500, detail="生成讲解失败，请稍后重试")
    return result


@router.post("/sessions/{session_id}/ask")
@limiter.limit("20/minute")
async def ask(session_id: str, body: AskRequest, request: Request):
    """用户提问（路由到 teacher / pet）。"""
    user_id = request.state.user_id
    _validate_uuid(session_id, "session_id")
    await _get_session_and_check_owner(session_id, user_id)

    try:
        result = await learning_service.ask_question(
            session_id=session_id,
            target=body.target,
            question=body.question,
            chapter_id=body.chapter_id,
        )
    except LearningError as e:
        raise _learning_error_to_http(e)
    except Exception as e:
        logger.exception("ask failed: %s", e)
        raise HTTPException(status_code=500, detail="回答失败，请稍后重试")
    return result


@router.post("/sessions/{session_id}/chapters/{chapter_id}/complete")
@limiter.limit("10/minute")
async def complete_chapter(session_id: str, chapter_id: int, request: Request):
    """完成本章，推进进度并发亲密度奖励（防重复）。"""
    user_id = request.state.user_id
    _validate_uuid(session_id, "session_id")
    if chapter_id < 1 or chapter_id > 99:
        raise HTTPException(status_code=400, detail="Invalid chapter_id")
    await _get_session_and_check_owner(session_id, user_id)

    try:
        result = await learning_service.complete_chapter(session_id, chapter_id)
    except LearningError as e:
        raise _learning_error_to_http(e)
    except Exception as e:
        logger.exception("complete_chapter failed: %s", e)
        raise HTTPException(status_code=500, detail="完成章节失败，请稍后重试")
    return result


@router.post("/sessions/{session_id}/pause")
@limiter.limit("10/minute")
async def pause_session(session_id: str, request: Request):
    """暂停学习。"""
    user_id = request.state.user_id
    _validate_uuid(session_id, "session_id")
    await _get_session_and_check_owner(session_id, user_id)

    try:
        return await learning_service.pause_session(session_id)
    except LearningError as e:
        raise _learning_error_to_http(e)


@router.post("/sessions/{session_id}/complete")
@limiter.limit("5/minute")
async def complete_session(session_id: str, request: Request):
    """完成全部学习并结算奖励。"""
    user_id = request.state.user_id
    _validate_uuid(session_id, "session_id")
    await _get_session_and_check_owner(session_id, user_id)

    try:
        return await learning_service.complete_session(session_id)
    except LearningError as e:
        raise _learning_error_to_http(e)
    except Exception as e:
        logger.exception("complete_session failed: %s", e)
        raise HTTPException(status_code=500, detail="完成学习失败，请稍后重试")
