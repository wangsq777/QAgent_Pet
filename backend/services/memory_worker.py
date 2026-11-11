"""Durable outbox worker: leases, retries and restart recovery, owned by app lifespan."""
import asyncio
import json
from datetime import datetime, timezone, timedelta

from backend.config import settings
from backend.database import get_db
from backend.logging_config import get_logger
from backend.services.memory_store import memory_store, now
from backend.services.memory_text import chunks, tokens

logger = get_logger(__name__)


class MemoryWorker:
    def __init__(self):
        self.task = None
        self.wakeup = asyncio.Event()

    async def start(self):
        self.wakeup = asyncio.Event()
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    def notify(self):
        self.wakeup.set()

    async def claim(self):
        stamp = now()
        lease = (datetime.now(timezone.utc)+timedelta(minutes=3)).isoformat()
        async with get_db() as db:
            await db.execute('BEGIN IMMEDIATE')
            row = await (await db.execute("SELECT j.* FROM memory_jobs j WHERE "
                "((j.status IN ('pending','retry') AND j.available_at<=?) OR (j.status='running' AND j.lease_until<?)) "
                "ORDER BY CASE j.job_type WHEN 'extract' THEN 0 ELSE 1 END,j.available_at LIMIT 1",(stamp,stamp))).fetchone()
            if not row:
                return None
            await db.execute("UPDATE memory_jobs SET status='running',attempts=attempts+1,lease_until=? WHERE job_id=?",(lease,row['job_id']))
            await db.commit()
        item = dict(row)
        item['lease_until'] = lease
        item['batch_ids'] = [item['job_id']]
        item['sources'] = [item['source_id']]
        if item['job_type']=='extract':
            async with get_db() as db:
                await db.execute('BEGIN IMMEDIATE')
                cursor = await db.execute("SELECT j.job_id,j.source_id,m.content FROM memory_jobs j JOIN messages m "
                    "ON m.message_id=j.source_id JOIN memory_message_order o ON o.message_id=j.source_id "
                    "WHERE j.session_id=? AND j.job_type='extract' AND j.status IN ('pending','retry') "
                    "AND j.available_at<=? ORDER BY o.seq",(item['session_id'],stamp))
                used=0
                first=await (await db.execute('SELECT content FROM messages WHERE message_id=?',(item['source_id'],))).fetchone()
                used=tokens(first[0])+128 if first else 0
                async for candidate in cursor:
                    cost=tokens(candidate['content'])+128
                    if used+cost>settings.MEMORY_BATCH_TOKENS:
                        break
                    item['batch_ids'].append(candidate['job_id'])
                    item['sources'].append(candidate['source_id'])
                    used+=cost
                await db.executemany("UPDATE memory_jobs SET status='running',attempts=attempts+1,lease_until=? WHERE job_id=?",
                                     [(lease,jid) for jid in item['batch_ids'][1:]])
                await db.commit()
        return item

    async def once(self):
        item = await self.claim()
        if not item:
            return False
        try:
            identity = await memory_store.identity(item['session_id'])
            if item['job_type']=='extract':
                from backend.services.memory_writer import memory_writer
                from backend.services.memory_context import context_builder
                try:
                    await memory_writer.batch(item['session_id'],item['sources'])
                finally:
                    await context_builder.compact(identity)
            elif item['job_type']=='embed':
                await self.embed(identity,item['source_id'])
            async with get_db() as db:
                await db.executemany("UPDATE memory_jobs SET status='done',lease_until=NULL,last_error=NULL "
                                 "WHERE job_id=? AND lease_until=? AND status='running'",[(jid,item['lease_until']) for jid in item['batch_ids']])
                await db.commit()
        except asyncio.CancelledError:
            async with get_db() as db:
                await db.executemany("UPDATE memory_jobs SET status='retry',lease_until=NULL WHERE job_id=? AND lease_until=?",
                                 [(jid,item['lease_until']) for jid in item['batch_ids']])
                await db.commit()
            raise
        except Exception as exc:
            delay = min(3600,5*2**min(item['attempts'],9))
            available = (datetime.now(timezone.utc)+timedelta(seconds=delay)).isoformat()
            async with get_db() as db:
                await db.executemany("UPDATE memory_jobs SET status='retry',lease_until=NULL,available_at=?,last_error=? "
                                 'WHERE job_id=? AND lease_until=?',[(available,type(exc).__name__,jid,item['lease_until']) for jid in item['batch_ids']])
                await db.commit()
            logger.warning('Memory job will retry: type=%s error=%s',item['job_type'],type(exc).__name__)
        return True

    async def embed(self, identity, memory_id):
        from backend.services.embedding_service import embedding_service
        item = await memory_store.get(identity,memory_id)
        if item['status']!='active':
            return
        if not settings.EMBEDDING_API_URL:
            return  # Explicit configuration avoids posting embeddings to an Anthropic messages endpoint.
        vectors = []
        for index,part in enumerate(chunks(item['content'],settings.MEMORY_BATCH_TOKENS)):
            vector = await embedding_service.embed(part)
            if vector is None:
                raise RuntimeError('Embedding unavailable')
            vectors.append((memory_id,item['revision'],index,settings.EMBEDDING_MODEL,len(vector),json.dumps(vector)))
        async with get_db() as db:
            await db.execute('BEGIN IMMEDIATE')
            current = await (await db.execute('SELECT status,revision FROM memory_entries WHERE memory_id=?',(memory_id,))).fetchone()
            if current and current['status']=='active' and current['revision']==item['revision']:
                await db.execute('DELETE FROM memory_embeddings WHERE memory_id=?',(memory_id,))
                await db.executemany('INSERT OR REPLACE INTO memory_embeddings VALUES(?,?,?,?,?,?)',vectors)
            await db.commit()

    async def run(self):
        while True:
            self.wakeup.clear()
            try:
                if await self.once():
                    await asyncio.sleep(0)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning('Memory worker retrying after %s',type(exc).__name__)
            try:
                await asyncio.wait_for(self.wakeup.wait(),timeout=max(.1,settings.MEMORY_WORKER_INTERVAL))
            except asyncio.TimeoutError:
                pass


memory_worker = MemoryWorker()
