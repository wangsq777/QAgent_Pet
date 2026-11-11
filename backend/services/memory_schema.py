"""Additive, restart-safe migration. Legacy data stays in the local database."""
import json
import uuid
from backend.config import settings


def pet_key(session):
    return ("custom:" + session["custom_pet_id"] if session["pet_type"] == "custom"
            else "preset:" + session["pet_type"])


async def init_memory_schema(db):
    await db.executescript("""
    CREATE TABLE IF NOT EXISTS memory_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS memory_message_order (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT UNIQUE NOT NULL,
        session_id TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_memory_order_session ON memory_message_order(session_id, seq);
    CREATE TABLE IF NOT EXISTS memory_entries (
        memory_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, pet_key TEXT NOT NULL DEFAULT '',
        scope TEXT NOT NULL CHECK(scope IN ('user','pet')),
        kind TEXT NOT NULL, subject TEXT NOT NULL DEFAULT 'user', predicate TEXT NOT NULL,
        value TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
        sensitivity TEXT NOT NULL DEFAULT 'low', evidence_level TEXT NOT NULL DEFAULT 'explicit',
        observed_seq INTEGER NOT NULL DEFAULT 0, observed_at TEXT NOT NULL,
        valid_from TEXT NOT NULL, valid_to TEXT, revision INTEGER NOT NULL DEFAULT 1,
        supersedes_id TEXT, pinned INTEGER NOT NULL DEFAULT 0, fingerprint TEXT UNIQUE NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        CHECK(scope='pet' OR pet_key=''));
    CREATE INDEX IF NOT EXISTS idx_memory_owner ON memory_entries(user_id,scope,pet_key,status,predicate);
    CREATE TABLE IF NOT EXISTS memory_sources (
        memory_id TEXT NOT NULL, source_id TEXT NOT NULL, source_type TEXT NOT NULL,
        session_id TEXT, speaker TEXT NOT NULL, evidence TEXT NOT NULL,
        PRIMARY KEY(memory_id,source_id));
    CREATE TABLE IF NOT EXISTS memory_revisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, memory_id TEXT NOT NULL, operation TEXT NOT NULL,
        revision INTEGER NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS conversation_checkpoints (
        session_id TEXT PRIMARY KEY, summary TEXT NOT NULL DEFAULT '',
        state_json TEXT NOT NULL DEFAULT '{}', through_seq INTEGER NOT NULL DEFAULT 0,
        generation INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS memory_jobs (
        job_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, session_id TEXT NOT NULL,
        job_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0, lease_until TEXT, available_at TEXT NOT NULL,
        last_error TEXT, UNIQUE(job_type,source_id));
    CREATE INDEX IF NOT EXISTS idx_memory_jobs_due ON memory_jobs(status,available_at,lease_until);
    CREATE TABLE IF NOT EXISTS memory_embeddings (
        memory_id TEXT NOT NULL, revision INTEGER NOT NULL, chunk INTEGER NOT NULL,
        model TEXT NOT NULL, dimension INTEGER NOT NULL, embedding TEXT NOT NULL,
        PRIMARY KEY(memory_id,revision,chunk,model));
    CREATE TABLE IF NOT EXISTS memory_suppressions (
        user_id TEXT NOT NULL, pet_key TEXT NOT NULL DEFAULT '', source_id TEXT NOT NULL DEFAULT '',
        value TEXT NOT NULL DEFAULT '', PRIMARY KEY(user_id,pet_key,source_id,value));
    CREATE TABLE IF NOT EXISTS memory_legacy_profiles (
        user_id TEXT PRIMARY KEY, profile_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS memory_scope_overrides (
        user_id TEXT NOT NULL, predicate TEXT NOT NULL, value TEXT NOT NULL,
        pet_key TEXT NOT NULL, PRIMARY KEY(user_id,predicate,value));
    CREATE TABLE IF NOT EXISTS pet_mood_snapshots (
        user_id TEXT NOT NULL, pet_key TEXT NOT NULL, mood_tendency TEXT NOT NULL,
        updated_at TEXT NOT NULL, PRIMARY KEY(user_id,pet_key));
    """)
    try:
        await db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(memory_id UNINDEXED, terms)")
    except Exception:
        # Some packaged SQLite builds omit FTS5; lexical scanning remains available.
        pass
    marker = await (await db.execute("SELECT value FROM memory_meta WHERE key='schema_v2'")).fetchone()
    if not marker:
        # These eight fields had no provenance and could contain another pet's private context.
        cursor = await db.execute("SELECT * FROM user_profiles")
        columns = [d[0] for d in cursor.description]
        for row in await cursor.fetchall():
            profile = dict(zip(columns, row))
            await db.execute("INSERT OR IGNORE INTO memory_legacy_profiles VALUES(?,?)",
                             (profile['user_id'], json.dumps(profile, ensure_ascii=False, default=str)))
        await db.execute("UPDATE user_profiles SET region=NULL,identity=NULL,interests=NULL,occupation=NULL,"
                         "personality_hint=NULL,active_hours=NULL,mood_tendency=NULL,extra_info=NULL")
        cursor = await db.execute("SELECT l.*,s.user_id,s.pet_type,s.custom_pet_id FROM long_term_memories l "
                                  "JOIN pet_sessions s ON s.session_id=l.session_id")
        columns = [d[0] for d in cursor.description]
        for row in await cursor.fetchall():
            item = dict(zip(columns, row))
            mid = str(uuid.uuid4())
            await db.execute("""INSERT OR IGNORE INTO memory_entries
                (memory_id,user_id,pet_key,scope,kind,predicate,value,content,evidence_level,
                 observed_at,valid_from,fingerprint,created_at,updated_at)
                VALUES(?,?,?,'pet','legacy_episode','experience',?,?,'legacy',?,? ,?,?,?)""",
                (mid,item['user_id'],pet_key(item),item['summary'],item['summary'],item['created_at'],
                 item['created_at'],'legacy:'+item['memory_id'],item['created_at'],item['created_at']))
            await db.execute("INSERT OR IGNORE INTO memory_sources VALUES(?,?,'legacy',?,'unknown',?)",
                             (mid,item['memory_id'],item['session_id'],item['summary']))
        await db.execute("INSERT INTO memory_meta VALUES('schema_v2','1')")
    await db.execute("""INSERT OR IGNORE INTO memory_message_order(message_id,session_id)
                        SELECT message_id,session_id FROM messages ORDER BY created_at,rowid""")
    await db.execute("""INSERT OR IGNORE INTO memory_jobs(job_id,source_id,session_id,job_type,available_at)
                        SELECT 'extract:'||message_id,message_id,session_id,'extract',CURRENT_TIMESTAMP
                        FROM messages WHERE role='user'""")
    if settings.EMBEDDING_API_URL:
        await db.execute("""INSERT INTO memory_jobs(job_id,source_id,session_id,job_type,available_at)
            SELECT 'embed:'||m.memory_id,m.memory_id,COALESCE((SELECT session_id FROM memory_sources s
            WHERE s.memory_id=m.memory_id LIMIT 1),''),'embed',CURRENT_TIMESTAMP FROM memory_entries m
            WHERE m.status='active' AND NOT EXISTS(SELECT 1 FROM memory_embeddings e WHERE e.memory_id=m.memory_id
            AND e.revision=m.revision AND e.model=?)
            ON CONFLICT(job_type,source_id) DO UPDATE SET status=CASE WHEN memory_jobs.status='done'
            THEN 'pending' ELSE memory_jobs.status END""",(settings.EMBEDDING_MODEL,))
    await db.commit()
