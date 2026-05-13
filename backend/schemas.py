from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class UserCreateRequest(BaseModel):
    user_id: str
    nickname: Optional[str] = None


class SessionCreateRequest(BaseModel):
    user_id: str
    pet_type: str
    nickname: Optional[str] = None


class SessionResponse(BaseModel):
    session_id: str
    pet_type: str
    welcome_message: Optional[dict] = None
    intimacy: int
    is_existing: bool = False


class ChatRequest(BaseModel):
    content: str


class ChatResponse(BaseModel):
    reply: str
    emotion_tag: str
    intimacy: int
    total_chats: int
    schedule_extracted: Optional[dict] = None
    memory_compressed: bool = False
    daily_share: Optional[dict] = None  # 日常分享消息（约33%概率触发）
    user_profile_updated: bool = False  # 用户画像是否更新


class MessageResponse(BaseModel):
    message_id: str
    role: str
    content: str
    emotion_tag: Optional[str] = None
    is_proactive: bool = False
    created_at: datetime


class MessageListResponse(BaseModel):
    messages: List[MessageResponse]
    total: int


class SimulateTimeRequest(BaseModel):
    mode: str


class SimulateTimeResponse(BaseModel):
    proactive_message: Optional[dict] = None
    pet_status: str
    schedule_reminder: Optional[dict] = None


class MemoryPanelResponse(BaseModel):
    intimacy: int
    intimacy_level: str
    total_chats: int
    long_term_memories: List[dict]
    recent_messages_count: int
    user_profile: dict


class UserProfileResponse(BaseModel):
    region: Optional[str] = None
    identity: Optional[str] = None
    interests: Optional[List[str]] = None
    extra_info: Optional[dict] = None


class UserProfileUpdateRequest(BaseModel):
    region: Optional[str] = None
    identity: Optional[str] = None
    interests: Optional[str] = None
    extra_info: Optional[str] = None


class ErrorResponse(BaseModel):
    error_code: str
    message: str