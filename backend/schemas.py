from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class UserCreateRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=100)
    nickname: Optional[str] = Field(None, max_length=20)


class SessionCreateRequest(BaseModel):
    # user_id 仅保留向后兼容，真实身份以 request.state.user_id（X-User-Id 头）为准
    # 请求体中的 user_id 若存在则被忽略，防止身份伪造
    user_id: Optional[str] = Field(None, min_length=1, max_length=100)
    pet_type: str
    nickname: Optional[str] = Field(None, max_length=20)
    custom_pet_id: Optional[str] = None  # 自定义宠物ID


class SessionResponse(BaseModel):
    session_id: str
    pet_type: str
    welcome_message: Optional[dict] = None
    intimacy: int
    is_existing: bool = False


class ChatRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)


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


class PetStatusResponse(BaseModel):
    status: str
    status_label: str
    status_reason: str
    today_interactions: int
    companion_minutes_today: int
    consecutive_days: int
    intimacy: int
    intimacy_level: str
    total_chats: int
    mood_tendency: Optional[str] = None
    last_interaction_at: Optional[str] = None


class UserProfileResponse(BaseModel):
    region: Optional[str] = None
    identity: Optional[str] = None
    interests: Optional[List[str]] = None
    extra_info: Optional[dict] = None


class UserProfileUpdateRequest(BaseModel):
    region: Optional[str] = Field(None, max_length=100)
    identity: Optional[str] = Field(None, max_length=50)
    interests: Optional[str] = Field(None, max_length=500)
    occupation: Optional[str] = Field(None, max_length=100)
    personality_hint: Optional[str] = Field(None, max_length=100)
    active_hours: Optional[str] = Field(None, max_length=100)
    mood_tendency: Optional[str] = Field(None, max_length=100)
    extra_info: Optional[str] = Field(None, max_length=500)


class ErrorResponse(BaseModel):
    error_code: str
    message: str


# ============ 自定义宠物相关 Schema ============

class CustomPetConfigRequest(BaseModel):
    """自定义宠物配置请求"""
    pet_name: str = Field(..., min_length=1, max_length=8)
    pet_type: str  # 宠物类型: dog/cat/hamster/panda/tiger/lion/snake/cheetah/deer/lamb/pig/horse等
    personality_tags: List[str]  # 性格标签列表
    catchphrase: Optional[str] = Field(None, max_length=20)
    special_habits: Optional[str] = Field(None, max_length=200)
    avatar_url: Optional[str] = None  # 自定义头像URL（base64）


class CustomPetPreviewRequest(BaseModel):
    """自定义宠物预览请求"""
    pet_name: str = Field(..., min_length=1, max_length=8)
    pet_type: str
    personality_tags: List[str]
    catchphrase: Optional[str] = Field(None, max_length=20)
    special_habits: Optional[str] = Field(None, max_length=200)


class CustomPetPreviewResponse(BaseModel):
    """自定义宠物预览响应"""
    system_prompt: str  # 生成的完整 System Prompt
    pet_name: str
    pet_type: str
    personality_tags: List[str]
    catchphrase: str
    special_habits: Optional[str] = None
    welcome_messages: List[str]  # 欢迎语列表


class CustomPetCreateRequest(BaseModel):
    """创建自定义宠物请求"""
    pet_name: str = Field(..., min_length=1, max_length=8)
    pet_type: str
    personality_tags: List[str]
    catchphrase: Optional[str] = Field(None, max_length=20)
    special_habits: Optional[str] = Field(None, max_length=200)
    avatar_url: Optional[str] = None


class CustomPetResponse(BaseModel):
    """自定义宠物响应"""
    pet_id: str
    pet_name: str
    pet_type: str
    personality_tags: List[str]
    catchphrase: str
    special_habits: Optional[str] = None
    avatar_url: Optional[str] = None
    system_prompt: str
    created_at: datetime


class PetTemplateResponse(BaseModel):
    """宠物模板响应"""
    pet_type: str
    pet_name: str
    personality_tags: List[str]
    is_preset: bool


class PetTemplateListResponse(BaseModel):
    """宠物模板列表响应"""
    presets: List[PetTemplateResponse]  # 预置宠物列表
    customs: List[PetTemplateResponse]  # 用户自定义宠物列表