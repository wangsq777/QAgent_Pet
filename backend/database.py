import aiosqlite
from contextlib import asynccontextmanager
from typing import AsyncGenerator

DATABASE_PATH = "./qagent_pet.db"


async def init_database():
    async with aiosqlite.connect(DATABASE_PATH) as db:
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

        # 扩展 user_profiles 表
        for col_sql in [
            "ALTER TABLE user_profiles ADD COLUMN occupation TEXT",
            "ALTER TABLE user_profiles ADD COLUMN personality_hint TEXT",
            "ALTER TABLE user_profiles ADD COLUMN active_hours TEXT",
            "ALTER TABLE user_profiles ADD COLUMN mood_tendency TEXT",
        ]:
            try:
                await db.execute(col_sql)
            except Exception:
                pass

        await db.commit()


@asynccontextmanager
async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    db = await aiosqlite.connect(DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()