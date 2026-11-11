"""Canonical memory records, provenance, ownership and compatibility projections."""
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from backend.database import get_db
from backend.services.memory_schema import pet_key
from backend.services.memory_text import terms

PROFILE_FIELDS = {
    'current_city': 'region', 'identity': 'identity', 'occupation': 'occupation',
    'interest': 'interests', 'personality_hint': 'personality_hint',
    'active_hours': 'active_hours', 'mood_tendency': 'mood_tendency', 'extra_info': 'extra_info',
}
SHARED_FIELDS = {'current_city', 'identity', 'occupation', 'interest', 'avoidance', 'preferred_name'}
SINGLE_FIELDS = set(PROFILE_FIELDS) - {'interest', 'extra_info'}
SINGLE_FIELDS.add('support_preference')
PRIVATE_SIGNAL = re.compile(r'只[跟和对]你|只告诉你|别告诉|不要告诉|保密|秘密|私密|隐私|'
                            r'(?:别|不要)(?:跟|和|对).{0,12}(?:说|提)|(?:别|不要|不想)让.{0,12}知道|'
                            r'(?:别|不要)(?:分享|转告)|仅限你|我们之间')


def now():
    return datetime.now(timezone.utc).isoformat()


def clean(value):
    return re.sub(r'\s+', '', str(value)).strip('，。！？,.!?；;：:')


class MemoryStore:
    async def identity(self, session_id, user_id=None):
        async with get_db() as db:
            row = await (await db.execute('SELECT * FROM pet_sessions WHERE session_id=?', (session_id,))).fetchone()
        if not row or (user_id is not None and row['user_id'] != user_id):
            raise PermissionError('Session not found or not owned')
        result = dict(row)
        result['pet_key'] = pet_key(result)
        return result

    @staticmethod
    def access(identity, alias=''):
        prefix = alias + '.' if alias else ''
        return (f"{prefix}user_id=? AND ({prefix}scope='user' OR ({prefix}scope='pet' AND {prefix}pet_key=?))",
                (identity['user_id'], identity['pet_key']))

    async def exclusions(self, identity):
        async with get_db() as db:
            rows = await (await db.execute("SELECT source_id,value FROM memory_suppressions WHERE user_id=? "
                                           "AND (pet_key='' OR pet_key=?)",
                                           (identity['user_id'],identity['pet_key']))).fetchall()
            private = await (await db.execute("SELECT value FROM memory_scope_overrides WHERE user_id=? AND pet_key!=?",
                                               (identity['user_id'],identity['pet_key']))).fetchall()
        return [dict(r) for r in rows]+[dict(source_id='',value=r[0]) for r in private]

    @staticmethod
    def redacted(content, source_id, exclusions):
        if any(e['source_id'] and e['source_id'] == source_id for e in exclusions):
            return '（这条消息包含已遗忘内容，已从模型上下文中移除）'
        for item in exclusions:
            if item['value'] and clean(item['value']) in clean(content):
                return '（已遗忘的内容已从模型上下文中移除）'
        return content

    async def get(self, identity, memory_id):
        clause, params = self.access(identity)
        async with get_db() as db:
            row = await (await db.execute(f'SELECT * FROM memory_entries WHERE memory_id=? AND {clause}',
                                          (memory_id,*params))).fetchone()
            if not row:
                raise KeyError(memory_id)
            item = dict(row)
            sources = await (await db.execute('SELECT s.source_id,s.source_type,s.session_id,s.speaker,s.evidence,m.created_at AS source_created_at '
                                              "FROM memory_sources s LEFT JOIN messages m ON m.message_id=s.source_id WHERE s.memory_id=? AND s.evidence!=''", (memory_id,))).fetchall()
            item['sources'] = [dict(s) for s in sources]
            revisions=await (await db.execute('SELECT operation,revision,payload_json,created_at FROM memory_revisions '
                                              'WHERE memory_id=? ORDER BY id',(memory_id,))).fetchall()
            item['revisions']=[dict(operation=r['operation'],revision=r['revision'],payload=json.loads(r['payload_json']),created_at=r['created_at']) for r in revisions]
        return item

    async def list(self, identity, *, before=None, limit=50, history=False):
        clause, params = self.access(identity)
        extra, args = '', list(params)
        if before:
            extra += ' AND rowid < ?'
            args.append(before)
        extra += " AND status IN ('active','superseded')" if history else " AND status='active'"
        exclusions = await self.exclusions(identity)
        items=[]
        async with get_db() as db:
            cursor = await db.execute(f'SELECT rowid AS cursor,* FROM memory_entries WHERE {clause}{extra} ORDER BY rowid DESC',args)
            async for row in cursor:
                if self.redacted(row['content'],'',exclusions)==row['content']:
                    items.append(dict(row))
                if len(items)>limit:
                    break
        return {'items':items[:limit], 'next_cursor':items[limit-1]['cursor'] if len(items)>limit else None}

    async def _index(self, db, memory_id, content):
        try:
            await db.execute('DELETE FROM memory_fts WHERE memory_id=?', (memory_id,))
            await db.execute('INSERT INTO memory_fts(memory_id,terms) VALUES(?,?)',
                             (memory_id,' '.join(sorted(terms(content)))))
        except Exception as exc:
            if 'no such table' not in str(exc):
                raise

    async def _invalidate(self, db, user_id):
        # Increment generation instead of deleting: an in-flight summarizer must fail its CAS.
        await db.execute("UPDATE conversation_checkpoints SET summary='',state_json='{}',through_seq=0,"
                         "generation=generation+1 WHERE session_id IN (SELECT session_id FROM pet_sessions WHERE user_id=?)",
                         (user_id,))

    async def _project(self, db, user_id):
        rows = await (await db.execute("SELECT predicate,value FROM memory_entries WHERE user_id=? "
                                      "AND scope='user' AND status='active' ORDER BY observed_seq,updated_at",
                                      (user_id,))).fetchall()
        values = {field:None for field in PROFILE_FIELDS.values()}
        interests = []
        suppressed = await (await db.execute("SELECT value FROM memory_suppressions WHERE user_id=? AND pet_key='' AND value!=''",
                                             (user_id,))).fetchall()
        for row in rows:
            if any(clean(s['value']) in clean(row['value']) for s in suppressed):
                continue
            field = PROFILE_FIELDS.get(row['predicate'])
            if field == 'interests':
                interests.append(row['value'])
            elif field:
                values[field] = row['value']
        values['interests'] = ','.join(dict.fromkeys(interests)) or None
        await db.execute('INSERT OR IGNORE INTO user_profiles(profile_id,user_id) VALUES(?,?)',
                         (str(uuid.uuid4()),user_id))
        await db.execute('UPDATE user_profiles SET '+','.join(f'{key}=?' for key in values)+',updated_at=? WHERE user_id=?',
                         (*values.values(),now(),user_id))
        from backend.services.memory_service import memory_service
        memory_service._profile_cache.pop(user_id,None)

    async def write(self, identity, candidate, *, source_id, source_type='message', speaker='user',
                    source_text=None, observed_seq=0, observed_at=None, manual=False, replace_id=None):
        predicate = candidate.get('predicate','experience')
        value = str(candidate.get('value','')).strip()
        evidence = str(candidate.get('evidence',value)).strip()
        if not value or len(value)>4000 or not re.fullmatch(r'[a-z_]{1,50}', predicate):
            return None
        if candidate.get('subject','user') != 'user' and predicate in PROFILE_FIELDS:
            return None
        if not manual and (speaker != 'user' or not evidence or not source_text or evidence not in source_text):
            return None
        kind = candidate.get('kind','fact')
        if kind not in {'fact','preference','episode','ongoing','legacy_episode'}:
            return None
        scope = candidate.get('scope','pet')
        sensitive = candidate.get('sensitivity','low')
        if scope != 'user' or predicate not in SHARED_FIELDS or sensitive != 'low' or PRIVATE_SIGNAL.search(source_text or value):
            scope = 'pet'
        async with get_db() as db:
            override = await (await db.execute('SELECT pet_key FROM memory_scope_overrides WHERE user_id=? AND predicate=? AND value=?',
                                              (identity['user_id'],predicate,clean(value)))).fetchone()
        if override:
            scope = 'pet'
            if override[0]!=identity['pet_key']:
                return None
        owner_key = '' if scope == 'user' else identity['pet_key']
        # Do not let an extra model-generated description smuggle private material into a shared fact.
        content = ('不喜欢：'+value) if predicate=='avoidance' else value
        observed_at = observed_at or now()
        fingerprint = hashlib.sha256(json.dumps([identity['user_id'],owner_key,predicate,clean(value)],ensure_ascii=False).encode()).hexdigest()
        async with get_db() as db:
            await db.execute('BEGIN IMMEDIATE')
            if manual and source_type=='manual':
                # Reserve a real observation sequence in the same transaction. MAX(seq)+1
                # computed before the transaction can collide with a concurrent chat message.
                await db.execute('INSERT OR IGNORE INTO memory_message_order(message_id,session_id) VALUES(?,?)',
                                 (source_id,identity['session_id']))
                observed_seq=(await (await db.execute('SELECT seq FROM memory_message_order WHERE message_id=?',
                                                      (source_id,))).fetchone())[0]
            override = await (await db.execute('SELECT pet_key FROM memory_scope_overrides WHERE user_id=? AND predicate=? AND value=?',
                                              (identity['user_id'],predicate,clean(value)))).fetchone()
            if override and (scope!='pet' or override[0]!=owner_key):
                return None
            suppressed = await (await db.execute("SELECT source_id,value FROM memory_suppressions WHERE user_id=? AND (pet_key='' OR pet_key=?)",
                                                 (identity['user_id'],identity['pet_key']))).fetchall()
            if manual and source_type=='manual':
                # Explicit user entry may teach a fact again; old source-message exclusions stay in force.
                for item in suppressed:
                    if item['value'] and clean(item['value'])==clean(value):
                        await db.execute("DELETE FROM memory_suppressions WHERE user_id=? AND value=? AND (pet_key='' OR pet_key=?)",
                                         (identity['user_id'],item['value'],identity['pet_key']))
                suppressed=[r for r in suppressed if not r['value'] or clean(r['value'])!=clean(value)]
            if any((r['source_id'] and r['source_id']==source_id) or
                   (r['value'] and clean(r['value']) in clean(value+' '+evidence)) for r in suppressed):
                return None
            existing = await (await db.execute('SELECT * FROM memory_entries WHERE fingerprint=?', (fingerprint,))).fetchone()
            if existing and existing['status']=='forgotten' and not (manual and source_type=='manual'):
                return None
            if existing and existing['status']=='superseded' and existing['observed_seq']>=observed_seq:
                return None
            # Compare observations even for an exact older value, so late retries cannot revive it.
            latest = await (await db.execute("SELECT * FROM memory_entries WHERE user_id=? AND pet_key=? AND scope=? "
                "AND predicate=? AND status='active' ORDER BY observed_seq DESC,updated_at DESC LIMIT 1",
                (identity['user_id'],owner_key,scope,predicate))).fetchone()
            if predicate in SINGLE_FIELDS and latest and latest['observed_seq'] > observed_seq:
                return None
            opposite = {'interest':'avoidance','avoidance':'interest'}.get(predicate)
            if opposite:
                contrary=await (await db.execute("SELECT * FROM memory_entries WHERE user_id=? AND pet_key=? AND scope=? "
                    "AND predicate=? AND value=? AND status='active'",(identity['user_id'],owner_key,scope,opposite,value))).fetchone()
                if contrary and contrary['observed_seq']>observed_seq:
                    return None
                if contrary:
                    await db.execute("UPDATE memory_entries SET status='superseded',valid_to=?,observed_seq=?,updated_at=? WHERE memory_id=?",
                                     (observed_at,observed_seq,now(),contrary['memory_id']))
                    await self._invalidate(db,identity['user_id'])
            if existing and existing['status']=='active':
                mid = existing['memory_id']
                await db.execute('INSERT OR IGNORE INTO memory_sources VALUES(?,?,?,?,?,?)',
                                 (mid,source_id,source_type,identity['session_id'],speaker,evidence))
                # Reaffirmation advances the watermark without changing the identity of the fact.
                await db.execute('UPDATE memory_entries SET observed_seq=MAX(observed_seq,?),updated_at=? WHERE memory_id=?',
                                 (observed_seq,now(),mid))
                await self._project(db,identity['user_id'])
                if replace_id and replace_id!=mid:
                    await db.execute("UPDATE memory_entries SET status='superseded',valid_to=?,updated_at=?,observed_seq=MAX(observed_seq,?) WHERE memory_id=? AND user_id=?",
                                     (observed_at,now(),observed_seq,replace_id,identity['user_id']))
                    await self._invalidate(db,identity['user_id'])
                    await self._project(db,identity['user_id'])
                await db.commit()
                return mid
            if predicate in SINGLE_FIELDS:
                await db.execute("UPDATE memory_entries SET status='superseded',valid_to=?,updated_at=?,observed_seq=MAX(observed_seq,?) WHERE user_id=? "
                                 "AND pet_key=? AND scope=? AND predicate=? AND status='active'",
                                 (observed_at,now(),observed_seq,identity['user_id'],owner_key,scope,predicate))
            mid = existing['memory_id'] if existing else str(uuid.uuid4())
            revision = (existing['revision']+1) if existing else 1
            if existing:
                await db.execute("UPDATE memory_entries SET status='active',revision=?,observed_seq=?,observed_at=?,"
                                 "valid_from=?,valid_to=NULL,value=?,content=?,updated_at=? WHERE memory_id=?",
                                 (revision,observed_seq,observed_at,observed_at,value,content,now(),mid))
            else:
                await db.execute("""INSERT INTO memory_entries(memory_id,user_id,pet_key,scope,kind,subject,predicate,
                    value,content,sensitivity,evidence_level,observed_seq,observed_at,valid_from,supersedes_id,
                    fingerprint,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (mid,identity['user_id'],owner_key,scope,kind,candidate.get('subject','user'),predicate,value,content,
                     sensitive,('generated' if source_type=='visit' else 'manual') if manual else 'explicit',observed_seq,observed_at,observed_at,
                     latest['memory_id'] if latest and predicate in SINGLE_FIELDS else None,fingerprint,now(),now()))
            await db.execute('INSERT OR IGNORE INTO memory_sources VALUES(?,?,?,?,?,?)',
                             (mid,source_id,source_type,identity['session_id'],speaker,evidence))
            if replace_id and replace_id!=mid:
                await db.execute("UPDATE memory_entries SET status='superseded',valid_to=?,updated_at=?,observed_seq=MAX(observed_seq,?) WHERE memory_id=? AND user_id=?",
                                 (observed_at,now(),observed_seq,replace_id,identity['user_id']))
            await db.execute('INSERT INTO memory_revisions(memory_id,operation,revision,payload_json,created_at) VALUES(?,?,?,?,?)',
                             (mid,'update' if latest else 'add',revision,json.dumps({'value':value,'source_id':source_id},ensure_ascii=False),now()))
            await self._index(db,mid,content+' '+predicate)
            await db.execute("INSERT INTO memory_jobs(job_id,source_id,session_id,job_type,available_at) VALUES(?,?,?,'embed',?) "
                             "ON CONFLICT(job_type,source_id) DO UPDATE SET status='pending',available_at=excluded.available_at",
                             ('embed:'+mid,mid,identity['session_id'],now()))
            await self._project(db,identity['user_id'])
            if (predicate in SINGLE_FIELDS and latest) or replace_id:
                await self._invalidate(db,identity['user_id'])
            await db.commit()
        return mid

    async def profile(self, identity):
        clause, params = self.access(identity)
        async with get_db() as db:
            rows = await (await db.execute(f"SELECT * FROM memory_entries WHERE {clause} AND status='active' "
                                          'ORDER BY observed_seq,updated_at',params)).fetchall()
            mood = await (await db.execute('SELECT mood_tendency,updated_at FROM pet_mood_snapshots WHERE user_id=? AND pet_key=?',
                                          (identity['user_id'],identity['pet_key']))).fetchone()
        result = {field:None for field in PROFILE_FIELDS.values()}
        interests = []
        explicit_mood_at = ''
        exclusions = await self.exclusions(identity)
        for row in rows:
            if self.redacted(row['content'],'',exclusions)!=row['content']:
                continue
            field = PROFILE_FIELDS.get(row['predicate'])
            if field == 'interests':
                interests.append(row['value'])
            elif field:
                result[field] = row['value']
                if field=='mood_tendency':
                    explicit_mood_at=row['updated_at']
        result['interests'] = ','.join(dict.fromkeys(interests)) or None
        if mood and mood['updated_at']>explicit_mood_at:
            result['mood_tendency'] = mood[0]
        return result

    async def forget(self, identity, memory_id):
        item = await self.get(identity,memory_id)
        async with get_db() as db:
            await db.execute('BEGIN IMMEDIATE')
            # Suppress every known supporting message, including reaffirmations, and the value itself.
            for source in item['sources']:
                await db.execute('INSERT OR IGNORE INTO memory_suppressions VALUES(?,?,?,?)',
                                 (identity['user_id'],item['pet_key'],source['source_id'],''))
            await db.execute('INSERT OR IGNORE INTO memory_suppressions VALUES(?,?,?,?)',
                             (identity['user_id'],item['pet_key'],'',item['value']))
            await db.execute("UPDATE memory_entries SET status='forgotten',content='',value='',revision=revision+1,updated_at=? "
                             'WHERE memory_id=?',(now(),memory_id))
            await db.execute('DELETE FROM memory_embeddings WHERE memory_id=?',(memory_id,))
            await db.execute("UPDATE memory_jobs SET status='cancelled' WHERE source_id=? AND job_type='embed'",(memory_id,))
            await db.execute("UPDATE memory_sources SET evidence='' WHERE memory_id=?",(memory_id,))
            await db.execute("UPDATE memory_revisions SET payload_json='{}' WHERE memory_id=?",(memory_id,))
            await db.execute('INSERT INTO memory_revisions(memory_id,operation,revision,payload_json,created_at) VALUES(?,?,?,?,?)',
                             (memory_id,'forget',item['revision']+1,'{}',now()))
            try:
                await db.execute('DELETE FROM memory_fts WHERE memory_id=?',(memory_id,))
            except Exception:
                pass
            await self._invalidate(db,identity['user_id'])
            await self._project(db,identity['user_id'])
            await db.execute('DELETE FROM pet_mood_snapshots WHERE user_id=?',(identity['user_id'],))
            await db.commit()

    async def edit(self, identity, memory_id, changes):
        item = await self.get(identity,memory_id)
        if item['status']=='forgotten':
            raise ValueError('Forgotten memories cannot be restored by editing')
        if 'scope' in changes and changes['scope']=='user' and (
                item['predicate'] not in SHARED_FIELDS or item['sensitivity']!='low'):
            raise ValueError('Only low-sensitivity basic facts can be shared')
        if 'value' in changes and changes['value'] != item['value']:
            # An explicit edit is a new observation; history still points to the old version.
            candidate = dict(item)
            candidate.update(changes)
            candidate['content'] = candidate['value']
            mid = await self.write(identity,candidate,source_id='edit:'+str(uuid.uuid4()),source_type='manual',
                                   manual=True,replace_id=memory_id)
            return mid
        scope = changes.get('scope',item['scope'])
        owner_key = '' if scope=='user' else identity['pet_key']
        fingerprint = hashlib.sha256(json.dumps([identity['user_id'],owner_key,item['predicate'],clean(item['value'])],ensure_ascii=False).encode()).hexdigest()
        async with get_db() as db:
            await db.execute('BEGIN IMMEDIATE')
            await db.execute('UPDATE memory_entries SET scope=?,pet_key=?,fingerprint=?,pinned=?,revision=revision+1,updated_at=? WHERE memory_id=?',
                             (scope,owner_key,fingerprint,int(changes.get('pinned',item['pinned'])),now(),memory_id))
            if scope=='pet' and 'scope' in changes:
                await db.execute('INSERT OR REPLACE INTO memory_scope_overrides VALUES(?,?,?,?)',
                                 (identity['user_id'],item['predicate'],clean(item['value']),owner_key))
            elif scope=='user' and 'scope' in changes:
                await db.execute('DELETE FROM memory_scope_overrides WHERE user_id=? AND predicate=? AND value=?',
                                 (identity['user_id'],item['predicate'],clean(item['value'])))
            await db.execute('INSERT INTO memory_revisions(memory_id,operation,revision,payload_json,created_at) VALUES(?,?,?,?,?)',
                             (memory_id,'edit',item['revision']+1,json.dumps(changes,ensure_ascii=False),now()))
            await self._invalidate(db,identity['user_id'])
            await self._project(db,identity['user_id'])
            await db.execute("INSERT INTO memory_jobs(job_id,source_id,session_id,job_type,available_at) VALUES(?,?,?,'embed',?) "
                             "ON CONFLICT(job_type,source_id) DO UPDATE SET status='pending',available_at=excluded.available_at",
                             ('embed:'+memory_id,memory_id,identity['session_id'],now()))
            await db.commit()
        return memory_id

    async def purge_pet(self, db, user_id, key):
        rows = await (await db.execute("SELECT memory_id FROM memory_entries WHERE user_id=? AND scope='pet' AND pet_key=?",
                                       (user_id,key))).fetchall()
        for row in rows:
            mid = row[0]
            for table in ('memory_sources','memory_revisions','memory_embeddings'):
                await db.execute(f'DELETE FROM {table} WHERE memory_id=?',(mid,))
            await db.execute('DELETE FROM memory_jobs WHERE source_id=?',(mid,))
            try:
                await db.execute('DELETE FROM memory_fts WHERE memory_id=?',(mid,))
            except Exception:
                pass
        await db.execute("DELETE FROM memory_entries WHERE user_id=? AND scope='pet' AND pet_key=?",(user_id,key))
        await db.execute('DELETE FROM pet_mood_snapshots WHERE user_id=? AND pet_key=?',(user_id,key))
        await db.execute('DELETE FROM memory_scope_overrides WHERE user_id=? AND pet_key=?',(user_id,key))


memory_store = MemoryStore()
