import os
import sqlite3
from datetime import datetime, timezone
import aiosqlite
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from pathlib import Path
from backend.config import settings
from backend.logging_config import get_logger

logger = get_logger(__name__)

def resolve_database_path(data_dir: str = "", database_url: str = "") -> str:
    """Resolve the SQLite file while keeping the existing DATABASE_URL contract.

    The packaged desktop app always supplies QAGENT_DATA_DIR. Source runs can
    continue using DATABASE_URL and therefore keep their current database.
    """
    selected_data_dir = (data_dir or os.getenv("QAGENT_DATA_DIR", "")).strip()
    if selected_data_dir:
        return str(Path(selected_data_dir).expanduser() / "qagent_pet.db")

    selected_url = (database_url or settings.DATABASE_URL).strip()
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if selected_url.startswith(prefix):
            raw_path = selected_url[len(prefix):]
            if raw_path == ":memory:":
                return raw_path
            return str(Path(raw_path).expanduser())

    raise ValueError("QAgent Pet currently supports only SQLite DATABASE_URL values")


DATABASE_PATH = resolve_database_path()


def _ensure_database_parent() -> None:
    if DATABASE_PATH == ":memory:":
        return
    Path(DATABASE_PATH).expanduser().parent.mkdir(parents=True, exist_ok=True)


def migrate_legacy_database(target_path: str, legacy_path: str = "") -> bool:
    """Create a consistent SQLite backup when moving from source to app data.

    sqlite3.backup also includes committed WAL data and is safer than copying
    the database and its sidecar files independently.
    """
    source_value = (legacy_path or os.getenv("QAGENT_LEGACY_DATABASE_PATH", "")).strip()
    if not source_value or target_path == ":memory:":
        return False

    source = Path(source_value).expanduser()
    target = Path(target_path).expanduser()
    if not source.is_file() or target.exists() or source.resolve() == target.resolve():
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    source_db = sqlite3.connect(str(source))
    target_db = sqlite3.connect(str(target))
    try:
        source_db.backup(target_db)
    except Exception:
        target_db.close()
        source_db.close()
        target.unlink(missing_ok=True)
        raise
    finally:
        try:
            target_db.close()
        finally:
            source_db.close()
    logger.info("Migrated legacy database to %s", target)
    return True


def create_periodic_backup(database_path: str, backup_dir: str = "", keep: int = 5) -> str:
    """Create at most one consistent backup per day and prune older copies."""
    if database_path == ":memory:":
        return ""

    source = Path(database_path).expanduser()
    if not source.is_file():
        return ""

    selected_dir = backup_dir.strip() if backup_dir else os.getenv("QAGENT_BACKUP_DIR", "").strip()
    destination_dir = Path(selected_dir).expanduser() if selected_dir else source.parent / "backups"
    destination_dir.mkdir(parents=True, exist_ok=True)

    today_prefix = f"qagent_pet-{datetime.now().strftime('%Y%m%d')}"
    if any(destination_dir.glob(f"{today_prefix}-*.db")):
        return ""

    destination = destination_dir / f"{today_prefix}-{datetime.now().strftime('%H%M%S')}.db"
    source_db = sqlite3.connect(str(source))
    backup_db = sqlite3.connect(str(destination))
    try:
        source_db.backup(backup_db)
    except Exception:
        backup_db.close()
        source_db.close()
        destination.unlink(missing_ok=True)
        raise
    finally:
        try:
            backup_db.close()
        finally:
            source_db.close()

    backups = sorted(destination_dir.glob("qagent_pet-*.db"), key=lambda item: item.stat().st_mtime, reverse=True)
    for stale in backups[max(1, keep):]:
        stale.unlink(missing_ok=True)
    logger.info("Created database backup at %s", destination)
    return str(destination)


def _set_db_file_permissions():
    """限制数据库文件权限，仅所有者可读写（L-1）"""
    try:
        if os.path.exists(DATABASE_PATH):
            os.chmod(DATABASE_PATH, 0o600)
    except Exception as e:
        logger.warning("Failed to set database file permissions: %s", e)


async def init_database():
    _ensure_database_parent()
    migrate_legacy_database(DATABASE_PATH)
    create_periodic_backup(DATABASE_PATH)
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

        # 主动陪伴：统一事件队列与用户策略。字段保持扁平，便于 SQLite
        # 在桌面端进行原子领取；message_context_json 只保存最小结构化上下文。
        await db.execute("""
            CREATE TABLE IF NOT EXISTS proactive_events (
                event_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                source_type TEXT NOT NULL CHECK(source_type IN ('schedule','concern','emotion_followup','inactivity','pet_initiated')),
                source_ref_id TEXT,
                dedupe_key TEXT UNIQUE,
                scheduled_at_utc DATETIME NOT NULL,
                expires_at_utc DATETIME,
                priority INTEGER NOT NULL DEFAULT 50 CHECK(priority BETWEEN 0 AND 100),
                sensitivity TEXT NOT NULL DEFAULT 'low' CHECK(sensitivity IN ('low','medium','high')),
                bubble_text TEXT NOT NULL,
                message_context_json TEXT,
                rendered_message TEXT,
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','claimed','delivered','opened','snoozed','completed','cancelled','expired','failed')),
                attempt_count INTEGER NOT NULL DEFAULT 0,
                claim_token TEXT,
                claim_expires_at_utc DATETIME,
                delivered_at_utc DATETIME,
                opened_at_utc DATETIME,
                completed_at_utc DATETIME,
                last_error TEXT,
                created_at_utc DATETIME NOT NULL,
                updated_at_utc DATETIME NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (session_id) REFERENCES pet_sessions(session_id)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_proactive_due ON proactive_events(user_id, session_id, status, scheduled_at_utc)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_proactive_source ON proactive_events(source_type, source_ref_id)")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS proactive_settings (
                user_id TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
                timezone_policy TEXT NOT NULL DEFAULT 'fixed_instant',
                quiet_start TEXT NOT NULL DEFAULT '23:00',
                quiet_end TEXT NOT NULL DEFAULT '08:00',
                max_general_per_day INTEGER NOT NULL DEFAULT 1,
                min_interval_minutes INTEGER NOT NULL DEFAULT 120,
                schedule_enabled INTEGER NOT NULL DEFAULT 1,
                concern_enabled INTEGER NOT NULL DEFAULT 1,
                emotion_followup_enabled INTEGER NOT NULL DEFAULT 0,
                inactivity_enabled INTEGER NOT NULL DEFAULT 1,
                pet_initiated_enabled INTEGER NOT NULL DEFAULT 1,
                privacy_level TEXT NOT NULL DEFAULT 'generic',
                created_at_utc DATETIME NOT NULL,
                updated_at_utc DATETIME NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS schedule_candidates (
                candidate_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                content TEXT NOT NULL,
                scheduled_at_local DATETIME,
                timezone TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                ambiguity_reason TEXT,
                source_message_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','confirmed','rejected','expired')),
                expires_at_utc DATETIME NOT NULL,
                created_at_utc DATETIME NOT NULL,
                updated_at_utc DATETIME NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (session_id) REFERENCES pet_sessions(session_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS concern_items (
                concern_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('future_event','emotion','unresolved_topic')),
                subject TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                source_message_id TEXT,
                sensitivity TEXT NOT NULL DEFAULT 'low' CHECK(sensitivity IN ('low','medium','high')),
                consent_state TEXT NOT NULL DEFAULT 'pending' CHECK(consent_state IN ('explicit','confirmed','pending','denied')),
                status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','active','snoozed','resolved','dismissed','expired')),
                next_followup_at_utc DATETIME,
                followup_count INTEGER NOT NULL DEFAULT 0,
                max_followups INTEGER NOT NULL DEFAULT 1,
                resolution_summary TEXT,
                retention_expires_at_utc DATETIME,
                created_at_utc DATETIME NOT NULL,
                updated_at_utc DATETIME NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (session_id) REFERENCES pet_sessions(session_id)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_concerns_user ON concern_items(user_id, session_id, status)")

        # 精确时间与生命周期字段；旧数据保留并按 needs_confirmation 迁移。
        for col_sql in [
            "ALTER TABLE schedules ADD COLUMN scheduled_at_utc DATETIME",
            "ALTER TABLE schedules ADD COLUMN timezone TEXT DEFAULT 'Asia/Shanghai'",
            "ALTER TABLE schedules ADD COLUMN status TEXT DEFAULT 'pending'",
            "ALTER TABLE schedules ADD COLUMN reminder_offset_minutes INTEGER DEFAULT 0",
            "ALTER TABLE schedules ADD COLUMN origin TEXT DEFAULT 'chat_explicit'",
            "ALTER TABLE schedules ADD COLUMN source_message_id TEXT",
            "ALTER TABLE schedules ADD COLUMN completed_at_utc DATETIME",
        ]:
            try:
                await db.execute(col_sql)
            except Exception as e:
                if "duplicate column name" not in str(e).lower():
                    raise
        await db.execute("UPDATE schedules SET status = CASE WHEN is_triggered = 1 THEN 'completed' ELSE COALESCE(status, 'needs_confirmation') END WHERE status IS NULL OR status = ''")
        await db.execute("UPDATE schedules SET status='needs_confirmation' WHERE scheduled_at_utc IS NULL AND is_triggered=0")

        # 摸鱼中心（仅内置模块）。
        await db.execute("""
            CREATE TABLE IF NOT EXISTS leisure_modules (
                module_id TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                icon TEXT NOT NULL DEFAULT '',
                module_type TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'builtin' CHECK(source = 'builtin'),
                status TEXT NOT NULL DEFAULT 'enabled' CHECK(status IN ('enabled','disabled')),
                manifest_json TEXT NOT NULL,
                created_at_utc DATETIME NOT NULL,
                updated_at_utc DATETIME NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS novel_books (
                book_id TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '', cover_url TEXT NOT NULL DEFAULT '',
                content_source TEXT NOT NULL DEFAULT 'builtin' CHECK(content_source = 'builtin'),
                content_version TEXT NOT NULL DEFAULT '1.0.0',
                status TEXT NOT NULL DEFAULT 'published' CHECK(status IN ('published','hidden')),
                created_at_utc DATETIME NOT NULL, updated_at_utc DATETIME NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS novel_chapters (
                chapter_id TEXT PRIMARY KEY, book_id TEXT NOT NULL, chapter_index INTEGER NOT NULL,
                title TEXT NOT NULL, content TEXT NOT NULL, word_count INTEGER NOT NULL DEFAULT 0,
                created_at_utc DATETIME NOT NULL, updated_at_utc DATETIME NOT NULL,
                UNIQUE(book_id, chapter_index), FOREIGN KEY(book_id) REFERENCES novel_books(book_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS novel_shelves (
                user_id TEXT NOT NULL, book_id TEXT NOT NULL, added_at_utc DATETIME NOT NULL,
                updated_at_utc DATETIME NOT NULL, PRIMARY KEY(user_id, book_id),
                FOREIGN KEY(user_id) REFERENCES users(user_id), FOREIGN KEY(book_id) REFERENCES novel_books(book_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS novel_progress (
                user_id TEXT NOT NULL, book_id TEXT NOT NULL, last_chapter_id TEXT,
                position INTEGER NOT NULL DEFAULT 0, percent REAL NOT NULL DEFAULT 0 CHECK(percent BETWEEN 0 AND 1),
                status TEXT NOT NULL DEFAULT 'reading' CHECK(status IN ('reading','paused','completed')),
                content_version TEXT NOT NULL DEFAULT '1.0.0', last_read_at_utc DATETIME,
                updated_at_utc DATETIME NOT NULL, request_id TEXT, PRIMARY KEY(user_id, book_id),
                FOREIGN KEY(user_id) REFERENCES users(user_id), FOREIGN KEY(book_id) REFERENCES novel_books(book_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS leisure_sessions (
                session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, module_id TEXT NOT NULL,
                content_ref_id TEXT, status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','closed','crashed')),
                started_at_utc DATETIME NOT NULL, last_resumed_at_utc DATETIME,
                paused_at_utc DATETIME, closed_at_utc DATETIME, accumulated_seconds INTEGER NOT NULL DEFAULT 0,
                close_reason TEXT, created_at_utc DATETIME NOT NULL, updated_at_utc DATETIME NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id), FOREIGN KEY(module_id) REFERENCES leisure_modules(module_id)
            )
        """)
        await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_leisure_active_user ON leisure_sessions(user_id) WHERE status = 'active'")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS leisure_settings (
                user_id TEXT PRIMARY KEY, pet_interaction_enabled INTEGER NOT NULL DEFAULT 1,
                interaction_frequency TEXT NOT NULL DEFAULT 'normal', save_progress_enabled INTEGER NOT NULL DEFAULT 1,
                privacy_level TEXT NOT NULL DEFAULT 'private', updated_at_utc DATETIME NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        """)
        # 静态内置模块与最小合法测试内容；使用 INSERT OR IGNORE 保证迁移幂等。
        now_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        await db.execute("""INSERT OR IGNORE INTO leisure_modules(module_id,version,title,description,icon,module_type,source,status,manifest_json,created_at_utc,updated_at_utc)
                          VALUES('builtin.novel','1.0.0','小说','读一小段故事，随时从上次的位置继续。','📖','novel','builtin','enabled','{"module_id":"builtin.novel","version":"1.0.0","source":"builtin","required_permissions":[],"entrypoint":"builtin.novel"}',?,?)""", (now_utc, now_utc))
        await db.execute("""INSERT OR IGNORE INTO novel_books(book_id,title,author,description,content_source,content_version,status,created_at_utc,updated_at_utc)
                          VALUES('builtin.first-light','《第一束光》','QAgent','一篇适合短暂休息时阅读的内置短篇。','builtin','1.0.0','published',?,?)""", (now_utc, now_utc))
        await db.execute("""INSERT OR IGNORE INTO novel_chapters(chapter_id,book_id,chapter_index,title,content,word_count,created_at_utc,updated_at_utc)
                          VALUES('builtin.first-light.1','builtin.first-light',1,'第一章 早安','窗帘缝里漏进一束光。小桌宠伸了伸懒腰，把今天的故事翻到第一页：先休息一会儿，再继续出发。',44,?,?)""", (now_utc, now_utc))
        await db.execute("""INSERT OR IGNORE INTO novel_chapters(chapter_id,book_id,chapter_index,title,content,word_count,created_at_utc,updated_at_utc)
                          VALUES('builtin.first-light.2','builtin.first-light',2,'第二章 风来','风从窗边经过，带来一点树叶的声音。故事没有催促谁，下一页什么时候打开，都由你决定。',39,?,?)""", (now_utc, now_utc))

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
