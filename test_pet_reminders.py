"""Regression coverage for custom-pet reminder identity and session isolation."""
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from backend import database
from backend.config import settings
from backend.services.llm_service import llm_service
from backend.services.embedding_service import embedding_service
from backend.services.pet_reminder_service import get_reminder_identity
from main import app


class PetReminderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db_patch = patch.object(database, 'DATABASE_PATH', str(Path(self.directory.name) / 'test.db'))
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        await database.init_database()
        self.user = 'reminder-' + uuid.uuid4().hex
        self.panda = str(uuid.uuid4())
        self.dog = str(uuid.uuid4())
        async with database.get_db() as db:
            await db.execute('INSERT INTO users(user_id,nickname) VALUES(?,?)', (self.user, '测试'))
            await db.execute('INSERT INTO custom_pets(pet_id,user_id,pet_name,pet_type,personality_tags,system_prompt,catchphrase) VALUES(?,?,?,?,?,?,?)',
                             ('panda', self.user, '团团', 'panda', '["温柔"]', '你是熊猫团团，喜欢吃竹子，自称滚滚。', '抱抱竹子'))
            for sid, kind, pet_id in [(self.panda, 'custom', 'panda'), (self.dog, 'hot_dog', None)]:
                await db.execute('INSERT INTO pet_sessions(session_id,user_id,pet_type,custom_pet_id) VALUES(?,?,?,?)',
                                 (sid, self.user, kind, pet_id))
            await db.commit()
        headers = {'X-User-Id': self.user}
        if settings.API_KEY:
            headers['Authorization'] = 'Bearer ' + settings.API_KEY
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1', headers=headers)
        self.addAsyncCleanup(self.client.aclose)

    async def test_daily_reminder_uses_panda_persona_and_saves_only_to_panda(self):
        with patch.object(llm_service, 'chat', AsyncMock(return_value='滚滚抱着竹子来陪你啦。')) as llm:
            response = await self.client.post(f'/api/sessions/{self.panda}/share-daily')
        self.assertEqual(response.status_code, 200, response.text)
        messages = llm.call_args.args[0]
        self.assertEqual(messages[0]['role'], 'system')
        self.assertIn('panda', messages[0]['content'])
        self.assertIn('抱抱竹子', messages[0]['content'])
        self.assertNotIn('汪汪', messages[1]['content'])
        panda = await self.client.get(f'/api/sessions/{self.panda}/messages')
        dog = await self.client.get(f'/api/sessions/{self.dog}/messages')
        self.assertEqual(panda.json()['messages'][0]['content'], '滚滚抱着竹子来陪你啦。')
        self.assertEqual(dog.json()['messages'], [])

    async def test_model_failure_has_neutral_custom_fallback_and_preserves_dog_voice(self):
        with patch.object(llm_service, 'chat', AsyncMock(return_value=None)):
            panda = await self.client.post(f'/api/sessions/{self.panda}/share-daily')
            dog = await self.client.post(f'/api/sessions/{self.dog}/share-daily')
        self.assertEqual(panda.status_code, 200, panda.text)
        self.assertNotIn('汪', panda.json()['message']['content'])
        self.assertNotIn('狗窝', panda.json()['message']['content'])
        self.assertIn('汪汪', dog.json()['message']['content'])

    async def test_next_day_supports_custom_pet(self):
        with patch.object(llm_service, 'chat', AsyncMock(return_value='滚滚想你啦。')) as llm:
            result = await self.client.post(f'/api/sessions/{self.panda}/simulate-time', json={'mode': 'next_day'})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['proactive_message']['content'], '滚滚想你啦。')
        self.assertIn('panda', llm.call_args.args[0][0]['content'])

    async def test_chat_daily_share_keeps_custom_identity(self):
        async def respond(messages, **kwargs):
            if kwargs.get('caller') == 'proactive_custom':
                self.assertIn('panda', messages[0]['content'])
                self.assertNotIn('汪汪', messages[-1]['content'])
                return '滚滚抱着竹子来陪你啦。'
            return '{"reply":"你好呀", "emotion":"neutral"}'

        with patch.object(llm_service, 'chat', AsyncMock(side_effect=respond)), \
                patch.object(embedding_service, 'embed', AsyncMock(return_value=None)), \
                patch('random.random', return_value=0):
            result = await self.client.post(f'/api/sessions/{self.panda}/chat', json={'content': '你好呀'})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['daily_share']['content'], '滚滚抱着竹子来陪你啦。')

    async def test_custom_identity_is_scoped_to_owner(self):
        async with database.get_db() as db:
            name, context = await get_reminder_identity(db, {'pet_type': 'custom', 'custom_pet_id': 'panda', 'user_id': 'someone-else'})
        self.assertNotIn('团团', name + context)
        self.assertNotIn('汪', context)


if __name__ == '__main__':
    unittest.main()
