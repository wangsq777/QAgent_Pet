"""Memory regressions use isolated SQLite files and stubbed models, never user data or network."""
import asyncio
import json
import tempfile
import unittest
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from backend import database
from backend.config import settings
from backend.services.memory_service import memory_service
from backend.services.memory_store import memory_store, now
from backend.services.memory_writer import memory_writer
from backend.services.memory_retriever import memory_retriever, VectorIndex
from backend.services.memory_context import context_builder
from backend.services.memory_worker import MemoryWorker
from backend.services.memory_text import tokens
from backend.services.llm_service import llm_service
from main import app


class MemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        for target,name,value in ((database,'DATABASE_PATH',str(Path(temp.name)/'test.db')),
                                  (settings,'LLM_API_KEY',''),(settings,'EMBEDDING_API_URL',''),
                                  (settings,'API_KEY','')):
            stub = patch.object(target,name,value)
            stub.start()
            self.addCleanup(stub.stop)
        memory_service._profile_cache.clear()
        await database.init_database()
        self.user = uuid.uuid4().hex
        self.other = uuid.uuid4().hex
        self.dog,self.cat,self.stranger = [str(uuid.uuid4()) for _ in range(3)]
        async with database.get_db() as db:
            await db.executemany('INSERT INTO users(user_id,nickname) VALUES(?,?)',[(self.user,'test'),(self.other,'other')])
            await db.executemany('INSERT INTO pet_sessions(session_id,user_id,pet_type) VALUES(?,?,?)',
                                [(self.dog,self.user,'hot_dog'),(self.cat,self.user,'cold_cat'),(self.stranger,self.other,'mouse')])
            await db.commit()
        self.identity = await memory_store.identity(self.dog)
        self.cat_identity = await memory_store.identity(self.cat)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=True,
                                            client=(self.user,123)),base_url='http://127.0.0.1',headers={'X-User-Id':self.user})
        self.addAsyncCleanup(self.client.aclose)

    async def say(self,text,session=None):
        sid = session or self.dog
        source = await memory_service.save_message(sid,'user',text)
        ids = await memory_writer.observe(sid,source)
        return source,ids

    async def query(self,sql,params=()):
        async with database.get_db() as db:
            return [dict(r) for r in await (await db.execute(sql,params)).fetchall()]

    async def test_travel_does_not_change_residence(self):
        await self.say('我住北京，下周去上海面试')
        self.assertEqual((await memory_store.profile(self.identity))['region'],'北京')
        await self.say('我打算下个月搬到深圳')
        self.assertEqual((await memory_store.profile(self.identity))['region'],'北京')

    async def test_correction_keeps_historical_fact_and_sources(self):
        await self.say('我住北京')
        source,ids = await self.say('我已经搬到上海了')
        self.assertEqual((await memory_store.profile(self.identity))['region'],'上海')
        old = await self.query("SELECT * FROM memory_entries WHERE status='superseded'")
        self.assertEqual(old[0]['value'],'北京')
        self.assertTrue(old[0]['valid_to'])
        detail = await memory_store.get(self.identity,ids[0])
        self.assertEqual(detail['sources'][0]['source_id'],source)
        history = await memory_retriever.search(self.identity,'以前我住的城市')
        self.assertEqual({m['value'] for m in history},{'北京','上海'})

    async def test_third_party_hypothetical_and_quoted_facts_are_not_profile(self):
        for text in ('我朋友是医生','假如我是医生','他说“我住上海”'):
            _,ids = await self.say(text)
            self.assertFalse(ids)
        self.assertIsNone((await memory_store.profile(self.identity))['occupation'])

    async def test_assistant_suggestions_are_not_user_facts(self):
        mid = await memory_service.save_message(self.dog,'assistant','你喜欢咖啡，我记住了')
        self.assertEqual(await memory_writer.observe(self.dog,mid,extract=True),[])

    async def test_duplicate_facts_merge_supporting_sources(self):
        await self.say('我喜欢科幻')
        await self.say('我喜欢科幻')
        entries = await memory_store.list(self.identity)
        self.assertEqual(len(entries['items']),1)
        detail = await memory_store.get(self.identity,entries['items'][0]['memory_id'])
        self.assertEqual(len(detail['sources']),2)

    async def test_shared_basics_and_private_experiences(self):
        await self.say('我住北京',self.cat)
        source = await memory_service.save_message(self.cat,'user','只告诉你，我的面试失败了')
        mid = await memory_store.write(self.cat_identity,dict(kind='episode',predicate='experience',value='面试失败',
                                        evidence='我的面试失败了',scope='pet'),source_id=source,source_text='只告诉你，我的面试失败了')
        self.assertEqual((await memory_store.profile(self.identity))['region'],'北京')
        with self.assertRaises(KeyError):
            await memory_store.get(self.identity,mid)
        self.assertNotIn('面试',await memory_retriever.history(self.identity,'面试失败',2000))

    async def test_privacy_marker_overrides_basic_sharing(self):
        await self.say('只告诉你，我住上海',self.cat)
        self.assertEqual((await memory_store.profile(self.cat_identity))['region'],'上海')
        self.assertIsNone((await memory_store.profile(self.identity))['region'])

    async def test_late_extraction_cannot_revert_correction(self):
        old = await memory_service.save_message(self.dog,'user','我住北京')
        await self.say('我搬到上海了')
        await memory_writer.observe(self.dog,old)
        self.assertEqual((await memory_store.profile(self.identity))['region'],'上海')

    async def test_full_partition_retrieval_survives_1000_new_entries(self):
        _,ids = await self.say('我住北京')
        stamp = now()
        async with database.get_db() as db:
            await db.executemany("""INSERT INTO memory_entries(memory_id,user_id,pet_key,scope,kind,predicate,value,content,
                observed_at,valid_from,fingerprint,created_at,updated_at) VALUES(?,?,?,'pet','episode','experience',?,?,?,?,?,?,?)""",
                [(f'noise{i}',self.user,self.identity['pet_key'],f'无关事件{i}',f'无关事件{i}',stamp,stamp,f'noise{i}',stamp,stamp) for i in range(1005)])
            await db.executemany('INSERT INTO memory_embeddings VALUES(?,1,0,?,2,?)',
                                [(ids[0],settings.EMBEDDING_MODEL,'[1,0]')]+[(f'noise{i}',settings.EMBEDDING_MODEL,'[0,1]') for i in range(1005)])
            await db.commit()
        hits = await memory_retriever.search(self.identity,'我住在哪个城市',query_vector=[1,0])
        self.assertEqual(hits[0]['memory_id'],ids[0])

    async def test_embedding_failure_has_lexical_fallback(self):
        await self.say('我住北京')
        mid = await memory_service.save_message(self.dog,'user','我现在住在哪个城市')
        with patch.object(settings,'EMBEDDING_API_URL','https://invalid.test/embeddings'), \
             patch('backend.services.embedding_service.embedding_service.embed',AsyncMock(return_value=None)):
            context = await context_builder.build(self.identity,mid,'我现在住在哪个城市')
        self.assertIn('北京',context['memories'])

    async def test_incompatible_embedding_models_and_dimensions_excluded(self):
        _,ids = await self.say('我住北京')
        async with database.get_db() as db:
            await db.execute('INSERT INTO memory_embeddings VALUES(?,1,0,?,3,?)',(ids[0],settings.EMBEDDING_MODEL,'[1,0,0]'))
            await db.execute('INSERT INTO memory_embeddings VALUES(?,1,0,?,2,?)',(ids[0],'old-model','[1,0]'))
            await db.commit()
        self.assertEqual(await VectorIndex().search(self.identity,[1,0],settings.EMBEDDING_MODEL),{})

    async def test_retry_and_restart_resume_durable_extraction(self):
        source = await memory_service.save_message(self.dog,'user','我住北京')
        with patch.object(memory_writer,'observe',AsyncMock(side_effect=RuntimeError('offline'))):
            await MemoryWorker().once()
        job = (await self.query('SELECT * FROM memory_jobs WHERE source_id=?',(source,)))[0]
        self.assertEqual(job['status'],'retry')
        async with database.get_db() as db:
            await db.execute("UPDATE memory_jobs SET available_at='2000-01-01' WHERE source_id=?",(source,))
            await db.commit()
        await MemoryWorker().once()
        job = (await self.query('SELECT * FROM memory_jobs WHERE source_id=?',(source,)))[0]
        self.assertEqual(job['status'],'done')
        self.assertEqual((await memory_store.profile(self.identity))['region'],'北京')

    async def test_expired_lease_can_be_reclaimed(self):
        source = await memory_service.save_message(self.dog,'user','我喜欢科幻')
        async with database.get_db() as db:
            await db.execute("UPDATE memory_jobs SET status='running',lease_until='2000-01-01' WHERE source_id=?",(source,))
            await db.commit()
        await MemoryWorker().once()
        self.assertEqual((await memory_store.profile(self.identity))['interests'],'科幻')

    async def test_forget_clears_derived_state_and_prevents_backfill_resurrection(self):
        source,ids = await self.say('我住北京')
        await memory_store.forget(self.identity,ids[0])
        self.assertEqual(await memory_writer.observe(self.dog,source,extract=True),[])
        self.assertIsNone((await memory_store.profile(self.identity))['region'])
        self.assertEqual(await memory_retriever.search(self.identity,'住北京'),[])
        self.assertEqual(await memory_retriever.history(self.identity,'住北京',2000),'')
        await database.init_database()
        self.assertEqual(await memory_writer.observe(self.dog,source),[])

    async def test_inflight_embedding_cannot_recreate_forgotten_index(self):
        _,ids = await self.say('我住北京')
        async def embed(_):
            await memory_store.forget(self.identity,ids[0])
            return [1.,0.]
        with patch.object(settings,'EMBEDDING_API_URL','https://invalid.test'), \
             patch('backend.services.embedding_service.embedding_service.embed',AsyncMock(side_effect=embed)):
            await MemoryWorker().embed(self.identity,ids[0])
        self.assertEqual(await self.query('SELECT * FROM memory_embeddings'),[])

    async def test_private_scope_change_survives_old_job_and_raw_history(self):
        source,ids = await self.say('我住北京')
        await memory_store.edit(self.identity,ids[0],{'scope':'pet'})
        await memory_writer.observe(self.dog,source)
        self.assertIsNone((await memory_store.profile(self.cat_identity))['region'])
        self.assertEqual((await memory_store.profile(self.identity))['region'],'北京')
        self.assertEqual((await self.query("SELECT COUNT(*) n FROM memory_entries WHERE scope='user'"))[0]['n'],0)

    async def test_current_message_occurs_once_and_budget_is_respected(self):
        await self.say('我喜欢科幻')
        await memory_service.save_message(self.dog,'assistant','好的，我记住了')
        query = '这是本轮唯一的新输入'
        mid = await memory_service.save_message(self.dog,'user',query)
        context = await context_builder.build(self.identity,mid,query)
        messages = context_builder.messages('受控人格与规则',context,query)
        self.assertEqual(messages[0]['role'],'system')
        self.assertEqual(sum(m['content'].count(query) for m in messages),1)
        self.assertTrue(any(m['role']=='assistant' for m in messages))
        self.assertLessEqual(sum(tokens(m['content'])+16 for m in messages),
                             settings.MEMORY_CONTEXT_TOKENS-settings.MEMORY_OUTPUT_TOKENS-settings.MEMORY_SAFETY_TOKENS)

    async def test_compaction_advances_cursor_and_preserves_pending_constraint(self):
        await self.say('请记住，不要替我报名')
        for i in range(12):
            await memory_service.save_message(self.dog,'user',f'普通聊天{i} '+('天气很好。'*25))
            await memory_service.save_message(self.dog,'assistant','嗯，听到了。')
        with patch.object(settings,'MEMORY_SHORT_TOKENS',1800):
            self.assertTrue(await context_builder.compact(self.identity))
            cp = (await self.query('SELECT * FROM conversation_checkpoints'))[0]
            self.assertGreater(cp['through_seq'],0)
            self.assertIn('不要替我报名',cp['state_json'])
            for _ in range(10):
                if not await context_builder.compact(self.identity):
                    break
                newer = (await self.query('SELECT * FROM conversation_checkpoints'))[0]
                self.assertGreater(newer['through_seq'],cp['through_seq'])
                cp = newer
            else:
                self.fail('Compaction did not drain the finite backlog')

    async def test_unknown_fact_returns_no_irrelevant_memories(self):
        await self.say('我住北京')
        self.assertEqual(await memory_retriever.search(self.identity,'我的血型是什么'),[])

    async def test_api_memory_crud_sources_isolation_and_history_pagination(self):
        _,ids = await self.say('我住北京')
        base=f'/api/sessions/{self.dog}/memories/{ids[0]}'
        detail=await self.client.get(base)
        self.assertEqual(detail.status_code,200,detail.text)
        self.assertTrue(detail.json()['sources'])
        response=await self.client.patch(base,json={'value':'上海'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual((await memory_store.profile(self.identity))['region'],'上海')
        page=await self.client.get(f'/api/sessions/{self.dog}/memories?history=true&limit=1')
        self.assertTrue(page.json()['next_cursor'])
        new_id=response.json()['memory_id']
        response=await self.client.get(f'/api/sessions/{self.stranger}/memories/{new_id}')
        self.assertEqual(response.status_code,404)
        self.assertEqual((await self.client.delete(f'/api/sessions/{self.dog}/memories/{new_id}')).status_code,200)
        self.assertIsNone((await memory_store.profile(self.identity))['region'])

    async def test_profile_edit_uses_canonical_facts(self):
        response=await self.client.put(f'/api/sessions/{self.dog}/profile',json={'region':'北京','extra_info':'只告诉狗的秘密'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual((await memory_store.profile(self.cat_identity))['region'],'北京')
        self.assertIsNone((await memory_store.profile(self.cat_identity))['extra_info'])

    async def test_chat_past_old_compression_threshold_succeeds(self):
        for i in range(42):
            await memory_service.save_message(self.dog,'user',f'旧消息{i}')
        reply=json.dumps({'reply':'我知道你现在住上海。','emotion':'neutral','need':'unknown','intensity':1,'risk_level':'none'},ensure_ascii=False)
        with patch('backend.routers.chat.llm_service.chat',AsyncMock(return_value=reply)) as llm, patch('random.random',return_value=1):
            response=await self.client.post(f'/api/sessions/{self.dog}/chat',json={'content':'我已经搬到上海了'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual((await memory_store.profile(self.identity))['region'],'上海')
        self.assertEqual(llm.await_args.args[0][0]['role'],'system')
        self.assertEqual(llm.await_count,1)

    async def test_messages_are_paginated_without_losing_old_history(self):
        for i in range(6):
            await memory_service.save_message(self.dog,'user',f'消息{i}')
        first=await self.client.get(f'/api/sessions/{self.dog}/messages?limit=3')
        self.assertEqual(first.json()['total'],6)
        second=await self.client.get(f"/api/sessions/{self.dog}/messages?limit=3&before={first.json()['next_cursor']}")
        self.assertEqual([m['content'] for m in second.json()['messages']],['消息0','消息1','消息2'])

    async def test_legacy_migration_archives_unsafe_profile_and_is_idempotent(self):
        async with database.get_db() as db:
            await db.execute("INSERT INTO user_profiles(profile_id,user_id,region,extra_info) VALUES(?,?,?,?)",(uuid.uuid4().hex,self.user,'旧城市','旧秘密'))
            await db.execute('INSERT INTO long_term_memories(memory_id,session_id,summary) VALUES(?,?,?)',(uuid.uuid4().hex,self.cat,'猫的旧经历'))
            await db.execute("DELETE FROM memory_meta WHERE key='schema_v2'")
            await db.commit()
        await database.init_database()
        await database.init_database()
        self.assertEqual((await self.query('SELECT region FROM user_profiles WHERE user_id=?',(self.user,)))[0]['region'],None)
        legacy=await self.query('SELECT profile_json FROM memory_legacy_profiles WHERE user_id=?',(self.user,))
        self.assertIn('旧秘密',legacy[0]['profile_json'])
        self.assertEqual(len((await memory_store.list(self.cat_identity))['items']),1)
        self.assertEqual((await memory_store.list(self.identity))['items'],[])

    async def test_worker_batches_model_calls_and_preserves_per_message_evidence(self):
        sources=[]
        for text in ('今天面试失败了','准备下周再试一次'):
            sources.append(await memory_service.save_message(self.dog,'user',text))
        result={'memories':[dict(source_id=sources[0],kind='episode',subject='user',predicate='experience',
                                value='今天面试失败了',evidence='今天面试失败了',scope='pet',sensitivity='high')]}
        with patch.object(settings,'LLM_API_KEY','test-only'), \
             patch.object(llm_service,'chat',AsyncMock(return_value=json.dumps(result,ensure_ascii=False))) as llm:
            await MemoryWorker().once()
        self.assertEqual(llm.await_count,1)
        jobs=await self.query("SELECT * FROM memory_jobs WHERE job_type='extract'")
        self.assertEqual({j['status'] for j in jobs},{'done'})
        entries=(await memory_store.list(self.identity))['items']
        self.assertEqual(len(entries),1)
        self.assertEqual((await memory_store.get(self.identity,entries[0]['memory_id']))['sources'][0]['source_id'],sources[0])

    async def test_bad_model_output_cannot_promote_third_party_to_user_profile(self):
        source=await memory_service.save_message(self.dog,'user','我朋友是医生')
        bad=[dict(kind='fact',subject='user',predicate='extra_info',value='用户是医生',evidence='我朋友是医生',scope='user')]
        with patch.object(settings,'LLM_API_KEY','test-only'):
            self.assertEqual(await memory_writer.observe(self.dog,source,extract=True,inferred=bad),[])

    async def test_mood_snapshots_are_pet_scoped(self):
        from backend.services.event_service import event_service
        from backend.services.mood_agent import mood_agent
        for _ in range(3):
            await event_service.append_event(self.user,self.cat,'emotion_observed',{'emotion':'sad','intensity':3})
        await mood_agent.analyze_mood_tendency(self.user,self.cat)
        self.assertIn('低落',(await memory_store.profile(self.cat_identity))['mood_tendency'])
        self.assertIsNone((await memory_store.profile(self.identity))['mood_tendency'])

    async def test_support_preference_is_immediate_private_and_correctable(self):
        await self.say('我倾诉时希望先听我说完')
        await self.say('我倾诉时希望先给我建议')
        values=await self.query("SELECT * FROM memory_entries WHERE predicate='support_preference' AND status='active'")
        self.assertEqual(len(values),1)
        self.assertEqual(values[0]['scope'],'pet')
        self.assertIn('建议',values[0]['value'])
        self.assertEqual((await memory_store.list(self.cat_identity))['items'],[])

    async def test_cold_cat_lazy_reply_still_records_memory(self):
        async with database.get_db() as db:
            await db.execute('UPDATE pet_sessions SET total_chats=1 WHERE session_id=?',(self.cat,))
            await db.commit()
        with patch('random.random',side_effect=[.1,1]):
            response=await self.client.post(f'/api/sessions/{self.cat}/chat',json={'content':'我住北京'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual((await memory_store.profile(self.cat_identity))['region'],'北京')
        self.assertEqual(response.json()['total_chats'],2)

    async def test_no_fts_build_still_retrieves_using_lexical_scan(self):
        _,ids=await self.say('我喜欢科幻')
        async with database.get_db() as db:
            await db.execute('DROP TABLE memory_fts')
            await db.commit()
        self.assertEqual((await memory_retriever.search(self.identity,'我喜欢什么'))[0]['memory_id'],ids[0])

    async def test_embedding_model_change_queues_reindex(self):
        _,ids=await self.say('我住北京')
        async with database.get_db() as db:
            await db.execute("UPDATE memory_jobs SET status='done' WHERE job_type='embed'")
            await db.commit()
        with patch.object(settings,'EMBEDDING_API_URL','https://invalid.test'),patch.object(settings,'EMBEDDING_MODEL','new-model'):
            await database.init_database()
        job=(await self.query("SELECT * FROM memory_jobs WHERE source_id=? AND job_type='embed'",(ids[0],)))[0]
        self.assertEqual(job['status'],'pending')

    async def test_long_raw_evidence_is_recalled_without_truncating_negation(self):
        await memory_service.save_message(self.dog,'user','无关的普通事情。'*100+'我不喜欢恐怖片。'+'日常琐事。'*100)
        text=await memory_retriever.history(self.identity,'恐怖片',700)
        self.assertIn('我不喜欢恐怖片',text)
        self.assertLessEqual(tokens(text),700)

    async def test_shared_city_source_does_not_disclose_district(self):
        _,ids=await self.say('我住在北京市朝阳区')
        item=await memory_store.get(self.cat_identity,ids[0])
        self.assertEqual(item['value'],'北京市')
        self.assertNotIn('朝阳区',json.dumps(item['sources'],ensure_ascii=False))

    async def test_tool_feedback_obeys_same_context_budget(self):
        previous=[{'role':'system','content':'规则。'*1000},
                  {'role':'user','content':'历史。'*1000},{'role':'assistant','content':'回复。'*1000},
                  {'role':'user','content':'当前问题。'*400}]
        messages=context_builder.tool_messages(previous,'工具调用。'*1000,'工具结果。'*1000)
        self.assertEqual(messages[-3],previous[-1])
        self.assertLessEqual(sum(tokens(m['content'])+16 for m in messages),
                            settings.MEMORY_CONTEXT_TOKENS-settings.MEMORY_OUTPUT_TOKENS-settings.MEMORY_SAFETY_TOKENS)

    async def test_explicit_dont_tell_another_pet_prevents_sharing(self):
        await self.say('我住上海，但别跟狗说',self.cat)
        self.assertIsNone((await memory_store.profile(self.identity))['region'])
        self.assertEqual((await memory_store.profile(self.cat_identity))['region'],'上海')

    async def test_application_lifespan_runs_and_stops_memory_worker(self):
        from backend.services.memory_worker import memory_worker
        async with app.router.lifespan_context(app):
            self.assertIsNotNone(memory_worker.task)
            source=await memory_service.save_message(self.dog,'user','我住北京')
            memory_worker.notify()
            for _ in range(100):
                jobs=await self.query('SELECT status FROM memory_jobs WHERE source_id=?',(source,))
                if jobs[0]['status']=='done':
                    break
                await asyncio.sleep(.01)
            else:
                self.fail('Lifespan worker did not process its durable outbox')
        self.assertIsNone(memory_worker.task)

    async def test_old_job_cannot_undo_a_manually_corrected_interest(self):
        source,ids=await self.say('我喜欢科幻')
        await memory_store.edit(self.identity,ids[0],{'value':'足球'})
        await memory_writer.observe(self.dog,source)
        self.assertEqual((await memory_store.profile(self.identity))['interests'],'足球')

    async def test_manual_reconfirmation_allows_learning_without_unblocking_old_sources(self):
        source,ids=await self.say('我住北京')
        await memory_store.forget(self.identity,ids[0])
        await memory_writer.manual_profile(self.dog,{'region':'北京'})
        self.assertEqual((await memory_store.profile(self.identity))['region'],'北京')
        self.assertEqual(await memory_writer.observe(self.dog,source),[])

    async def test_shared_fact_cannot_smuggle_private_model_description(self):
        source=await memory_service.save_message(self.dog,'user','我住北京')
        item=dict(kind='fact',predicate='current_city',value='北京',content='北京；某个不应共享的私事',
                  evidence='我住北京',scope='user')
        mid=await memory_store.write(self.identity,item,source_id=source,source_text='我住北京')
        self.assertEqual((await memory_store.get(self.cat_identity,mid))['content'],'北京')

    async def test_historical_statement_does_not_overwrite_current_city(self):
        await self.say('我住上海')
        source=await memory_service.save_message(self.dog,'user','以前我住北京')
        with patch.object(settings,'LLM_API_KEY','test-only'):
            await memory_writer.observe(self.dog,source,extract=True,inferred=[dict(kind='fact',subject='user',
                predicate='current_city',value='北京',evidence='我住北京',scope='user')])
        self.assertEqual((await memory_store.profile(self.identity))['region'],'上海')

    async def test_negative_preference_supersedes_positive_and_keeps_negation(self):
        source,_=await self.say('我喜欢恐怖片')
        await self.say('我不再喜欢恐怖片')
        await memory_writer.observe(self.dog,source)
        self.assertIsNone((await memory_store.profile(self.identity))['interests'])
        memories=await memory_retriever.search(self.identity,'恐怖片')
        self.assertEqual(len(memories),1)
        self.assertIn('不喜欢',memories[0]['content'])

    async def test_manual_mood_edit_is_not_overridden_by_an_older_snapshot(self):
        async with database.get_db() as db:
            await db.execute('INSERT INTO pet_mood_snapshots VALUES(?,?,?,?)',
                             (self.user,self.identity['pet_key'],'旧情绪','2000-01-01'))
            await db.commit()
        await memory_writer.manual_profile(self.dog,{'mood_tendency':'最近平静'})
        self.assertEqual((await memory_store.profile(self.identity))['mood_tendency'],'最近平静')

    async def test_concurrent_message_cannot_collide_with_manual_correction_sequence(self):
        delayed=[]
        original=memory_store.write
        async def interleave(*args,**kwargs):
            if kwargs.get('source_type')=='manual' and not delayed:
                delayed.append(await memory_service.save_message(self.dog,'user','我住上海'))
            return await original(*args,**kwargs)
        with patch.object(memory_store,'write',side_effect=interleave):
            await memory_writer.manual_profile(self.dog,{'region':'北京'})
        await memory_writer.observe(self.dog,delayed[0])
        self.assertEqual((await memory_store.profile(self.identity))['region'],'北京')


if __name__=='__main__':
    unittest.main()
