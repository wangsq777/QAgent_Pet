from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class User:
    user_id: str
    nickname: str
    created_at: datetime
    updated_at: datetime


@dataclass
class PetSession:
    session_id: str
    user_id: str
    pet_type: str
    intimacy: int = 0
    total_chats: int = 0
    last_interaction_at: Optional[datetime] = None
    pet_status: str = "normal"
    status_until: Optional[datetime] = None
    created_at: datetime = None
    updated_at: datetime = None


@dataclass
class Message:
    message_id: str
    session_id: str
    role: str
    content: str
    emotion_tag: Optional[str] = None
    is_proactive: bool = False
    created_at: datetime = None


@dataclass
class LongTermMemory:
    memory_id: str
    session_id: str
    summary: str
    source_range: Optional[str] = None
    created_at: datetime = None


@dataclass
class Schedule:
    schedule_id: str
    session_id: str
    content: str
    scheduled_time: datetime
    is_triggered: bool = False
    created_at: datetime = None


@dataclass
class UserProfile:
    profile_id: str
    user_id: str
    region: Optional[str] = None
    identity: Optional[str] = None
    interests: Optional[str] = None
    extra_info: Optional[str] = None
    created_at: datetime = None
    updated_at: datetime = None