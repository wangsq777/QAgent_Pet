import os
import aiosqlite
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from backend.logging_config import get_logger

logger = get_logger(__name__)

DATABASE_PATH = "./qagent_pet.db"


def _set_db_file_permissions():
    """限制数据库文件权限，仅所有者可读写（L-1）"""
    try:
        if os.path.exists(DATABASE_PATH):
            os.chmod(DATABASE_PATH, 0o600)
    except Exception as e:
        logger.warning("Failed to set database file permissions: %s", e)


async def init_database():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                nickname TEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS pet_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                pet_type TEXT NOT NULL CHECK(pet_type IN ('hot_dog', 'cold_cat', 'mouse', 'custom')),
                custom_pet_id TEXT,
                intimacy INTEGER DEFAULT 0,
                total_chats INTEGER DEFAULT 0,
                last_interaction_at DATETIME,
                pet_status TEXT DEFAULT 'normal' CHECK(pet_status IN ('normal', 'hiding', 'excited')),
                status_until DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                content TEXT NOT NULL,
                emotion_tag TEXT,
                is_proactive BOOLEAN DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES pet_sessions(session_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS long_term_memories (
                memory_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                source_range TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES pet_sessions(session_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS schedules (
                schedule_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                content TEXT NOT NULL,
                scheduled_time DATETIME NOT NULL,
                is_triggered BOOLEAN DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES pet_sessions(session_id)
            )
        """)

        # 自定义宠物表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS custom_pets (
                pet_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                pet_name TEXT NOT NULL,
                pet_type TEXT NOT NULL,
                personality_tags TEXT NOT NULL,
                catchphrase TEXT DEFAULT '',
                special_habits TEXT DEFAULT '',
                avatar_url TEXT DEFAULT '',
                system_prompt TEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_custom_pets_user ON custom_pets(user_id)
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                profile_id TEXT PRIMARY KEY,
                user_id TEXT UNIQUE NOT NULL,
                region TEXT,
                identity TEXT,
                interests TEXT,
                extra_info TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        # 新增：向量索引表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS memory_vectors (
                vector_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                source_type TEXT NOT NULL CHECK(source_type IN ('message', 'long_term')),
                source_id TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding TEXT NOT NULL,
                importance REAL DEFAULT 0.5,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES pet_sessions(session_id)
            )
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_vectors_session ON memory_vectors(session_id)
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_vectors_session_type ON memory_vectors(session_id, source_type)
        """)

        # 扩展 user_profiles 表（仅忽略"列已存在"错误，其他异常正常抛出）
        for col_sql in [
            "ALTER TABLE user_profiles ADD COLUMN occupation TEXT",
            "ALTER TABLE user_profiles ADD COLUMN personality_hint TEXT",
            "ALTER TABLE user_profiles ADD COLUMN active_hours TEXT",
            "ALTER TABLE user_profiles ADD COLUMN mood_tendency TEXT",
        ]:
            try:
                await db.execute(col_sql)
            except Exception as e:
                if "duplicate column name" not in str(e).lower():
                    logger.error("Migration failed: %s — %s", col_sql, e)
                    raise

        # 扩展 messages 表：情感捕捉 Phase 0 新增 need/intensity/risk_level
        for col_sql in [
            "ALTER TABLE messages ADD COLUMN emotional_need TEXT",
            "ALTER TABLE messages ADD COLUMN emotion_intensity INTEGER",
            "ALTER TABLE messages ADD COLUMN risk_level TEXT",
        ]:
            try:
                await db.execute(col_sql)
            except Exception as e:
                if "duplicate column name" not in str(e).lower():
                    logger.error("Migration failed: %s — %s", col_sql, e)
                    raise

        await db.execute("""
            CREATE TABLE IF NOT EXISTS pet_visits (
                visit_id          TEXT PRIMARY KEY,
                host_session_id   TEXT NOT NULL,
                guest_pet_id      TEXT NOT NULL,
                guest_session_id  TEXT,
                initiator_user_id TEXT NOT NULL,
                topic             TEXT,
                status            TEXT DEFAULT 'active' CHECK(status IN ('active', 'ended')),
                created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ended_at          DATETIME,
                FOREIGN KEY (host_session_id) REFERENCES pet_sessions(session_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS pet_visit_messages (
                msg_id            TEXT PRIMARY KEY,
                visit_id          TEXT NOT NULL,
                speaker_pet_id    TEXT NOT NULL,
                speaker_name      TEXT NOT NULL,
                content           TEXT NOT NULL,
                turn_index        INTEGER NOT NULL,
                created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (visit_id) REFERENCES pet_visits(visit_id)
            )
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_pet_visits_host ON pet_visits(host_session_id)
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_pet_visits_user ON pet_visits(initiator_user_id)
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_visit_messages_visit ON pet_visit_messages(visit_id)
        """)

        # 陪我学：学习会话表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS learning_sessions (
                id                    TEXT PRIMARY KEY,
                user_id               TEXT NOT NULL,
                pet_id                TEXT NOT NULL,
                pet_source            TEXT NOT NULL DEFAULT 'preset' CHECK(pet_source IN ('preset', 'custom')),
                github_url            TEXT NOT NULL,
                repo_owner            TEXT NOT NULL,
                repo_name             TEXT NOT NULL,
                repo_full_name        TEXT NOT NULL,
                repo_description      TEXT,
                outline_json          TEXT NOT NULL DEFAULT '[]',
                current_chapter       INTEGER NOT NULL DEFAULT 1,
                status                TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'paused', 'completed')),
                rewarded_chapters_json TEXT NOT NULL DEFAULT '[]',
                created_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at          DATETIME,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        # 陪我学：学习消息记录表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS learning_messages (
                id             TEXT PRIMARY KEY,
                session_id     TEXT NOT NULL,
                chapter_id     INTEGER,
                role           TEXT NOT NULL CHECK(role IN ('system', 'teacher', 'pet', 'user')),
                target         TEXT,
                content        TEXT NOT NULL,
                metadata_json  TEXT,
                created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES learning_sessions(id)
            )
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_learning_sessions_user_id ON learning_sessions(user_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_learning_sessions_pet_id ON learning_sessions(pet_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_learning_sessions_status ON learning_sessions(status)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_learning_messages_session_id ON learning_messages(session_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_learning_messages_chapter_id ON learning_messages(chapter_id)
        """)

        await db.commit()

    # 数据库初始化完成后设置文件权限
    _set_db_file_permissions()


@asynccontextmanager
async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    db = await aiosqlite.connect(DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()