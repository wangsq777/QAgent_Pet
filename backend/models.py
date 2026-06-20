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


@dataclass
class PetVisit:
    visit_id: str
    host_session_id: str
    guest_pet_id: str
    guest_session_id: Optional[str]
    initiator_user_id: str
    topic: Optional[str]
    status: str = "active"
    created_at: datetime = None
    ended_at: Optional[datetime] = None


@dataclass
class PetVisitMessage:
    msg_id: str
    visit_id: str
    speaker_pet_id: str
    speaker_name: str
    content: str
    turn_index: int
    created_at: datetime = None


@dataclass
class LearningSession:
    """陪我学：学习会话"""
    session_id: str
    user_id: str
    pet_id: str
    pet_source: str = "preset"  # preset / custom
    github_url: str = ""
    repo_owner: str = ""
    repo_name: str = ""
    repo_full_name: str = ""
    repo_description: Optional[str] = None
    outline_json: str = "[]"
    current_chapter: int = 1
    status: str = "active"  # active / paused / completed
    rewarded_chapters_json: str = "[]"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class LearningMessage:
    """陪我学：学习过程中的消息记录"""
    msg_id: str
    session_id: str
    chapter_id: Optional[int] = None
    role: str = ""  # system / teacher / pet / user
    target: Optional[str] = None  # teacher / pet，用于用户提问
    content: str = ""
    metadata_json: Optional[str] = None
    created_at: Optional[datetime] = None