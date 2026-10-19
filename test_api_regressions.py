"""HTTP regressions for reminder updates, custom pets and request limits."""
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from backend import database
from backend.config import settings
from backend.services.proactive_service import claim_event
from main import app


class ApiRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        db_patch = patch.object(database, "DATABASE_PATH", str(Path(directory.name) / "test.db"))
        db_patch.start()
        self.addCleanup(db_patch.stop)
        await database.init_database()
        self.user = "regression-" + uuid.uuid4().hex
        self.sid = str(uuid.uuid4())
        async with database.get_db() as db:
            await db.execute("INSERT INTO users(user_id,nickname) VALUES(?,?)", (self.user, "测试"))
            await db.execute("INSERT INTO pet_sessions(session_id,user_id,pet_type) VALUES(?,?,?)", (self.sid, self.user, "hot_dog"))
            await db.commit()
        headers = {"X-User-Id": self.user}
        if settings.API_KEY:
            headers["Authorization"] = "Bearer " + settings.API_KEY
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False, client=(self.user, 123)),
            base_url="http://127.0.0.1", headers=headers,
        )
        self.addAsyncCleanup(self.client.aclose)
        self.base = f"/api/sessions/{self.sid}/schedules"

    async def create_schedule(self):
        response = await self.client.post(self.base, json={
            "content": "测试会议", "scheduled_at_utc": "2026-10-12T04:00:00Z",
            "reminder_offset_minutes": 30,
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["schedule_id"]

    async def event(self, schedule_id):
        async with database.get_db() as db:
            row = await (await db.execute("SELECT * FROM proactive_events WHERE source_ref_id=?", (schedule_id,))).fetchone()
            return dict(row)

    async def test_reschedule_preserves_advance_notice_and_refreshes_expiry(self):
        schedule_id = await self.create_schedule()
        response = await self.client.patch(f"{self.base}/{schedule_id}", json={"scheduled_at_utc": "2026-10-13T04:00:00Z"})
        self.assertEqual(response.status_code, 200, response.text)
        event = await self.event(schedule_id)
        self.assertEqual(event["scheduled_at_utc"], "2026-10-13T03:30:00Z")
        self.assertEqual(event["expires_at_utc"], "2026-10-13T06:00:00Z")
        async with database.get_db() as db:
            with patch("backend.services.proactive_service.materialize_due_sources", AsyncMock()):
                claimed = await claim_event(db, user_id=self.user, session_id=self.sid,
                                            now=datetime(2026, 10, 13, 3, 30, tzinfo=timezone.utc))
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["source_ref_id"], schedule_id)

    async def test_offset_change_resets_claim_lease(self):
        schedule_id = await self.create_schedule()
        async with database.get_db() as db:
            await db.execute("UPDATE proactive_events SET status='claimed',claim_token='old',claim_expires_at_utc='2026-10-12T04:00:00Z' WHERE source_ref_id=?", (schedule_id,))
            await db.commit()
        response = await self.client.patch(f"{self.base}/{schedule_id}", json={"reminder_offset_minutes": 60})
        self.assertEqual(response.status_code, 200, response.text)
        event = await self.event(schedule_id)
        self.assertEqual(event["scheduled_at_utc"], "2026-10-12T03:00:00Z")
        self.assertEqual(event["expires_at_utc"], "2026-10-12T06:00:00Z")
        self.assertEqual(event["status"], "pending")
        self.assertIsNone(event["claim_token"])
        self.assertIsNone(event["claim_expires_at_utc"])

    async def test_finishing_schedule_cancels_reminder_even_when_moving_time(self):
        for status in ("completed", "cancelled"):
            with self.subTest(status=status):
                schedule_id = await self.create_schedule()
                response = await self.client.patch(f"{self.base}/{schedule_id}", json={
                    "status": status, "scheduled_at_utc": "2026-10-13T04:00:00Z",
                })
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual((await self.event(schedule_id))["status"], "cancelled")
        async with database.get_db() as db:
            with patch("backend.services.proactive_service.materialize_due_sources", AsyncMock()):
                claimed = await claim_event(db, user_id=self.user, session_id=self.sid,
                                            now=datetime(2026, 10, 13, 4, tzinfo=timezone.utc))
        self.assertIsNone(claimed)

    async def test_time_edit_does_not_revive_delivered_or_terminal_events(self):
        for status in ("delivered", "opened", "completed", "cancelled", "expired", "failed"):
            with self.subTest(status=status):
                schedule_id = await self.create_schedule()
                async with database.get_db() as db:
                    await db.execute("UPDATE proactive_events SET status=? WHERE source_ref_id=?", (status, schedule_id))
                    await db.commit()
                response = await self.client.patch(f"{self.base}/{schedule_id}", json={"scheduled_at_utc": "2026-10-13T04:00:00Z"})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual((await self.event(schedule_id))["status"], status)

    async def test_null_schedule_fields_rejected_without_mutation(self):
        schedule_id = await self.create_schedule()
        before = await self.event(schedule_id)
        for field in ("content", "status", "reminder_offset_minutes", "scheduled_at", "scheduled_at_utc"):
            with self.subTest(field=field):
                response = await self.client.patch(f"{self.base}/{schedule_id}", json={field: None})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(await self.event(schedule_id), before)

    async def assert_no_custom_sessions(self):
        async with database.get_db() as db:
            count = await (await db.execute("SELECT COUNT(*) FROM pet_sessions WHERE user_id=? AND pet_type='custom'", (self.user,))).fetchone()
        self.assertEqual(count[0], 0)

    async def test_missing_custom_pet_id_rejected_on_every_attempt(self):
        for body in ({"pet_type": "custom"}, {"pet_type": "custom", "custom_pet_id": ""}, {"pet_type": "custom"}):
            response = await self.client.post("/api/sessions", json=body)
            self.assertEqual(response.status_code, 400, response.text)
        await self.assert_no_custom_sessions()

    async def insert_custom_pet(self, owner):
        pet_id = str(uuid.uuid4())
        async with database.get_db() as db:
            if owner != self.user:
                await db.execute("INSERT INTO users(user_id,nickname) VALUES(?,?)", (owner, "其他用户"))
            await db.execute("INSERT INTO custom_pets(pet_id,user_id,pet_name,pet_type,personality_tags,system_prompt,catchphrase) VALUES(?,?,?,?,?,?,?)",
                             (pet_id, owner, "团团", "panda", '["温柔"]', "你是熊猫团团", "抱抱竹子"))
            await db.commit()
        return pet_id

    async def test_unknown_or_other_users_custom_pet_is_rejected(self):
        other_pet = await self.insert_custom_pet("other-" + uuid.uuid4().hex)
        for pet_id in (str(uuid.uuid4()), other_pet):
            response = await self.client.post("/api/sessions", json={"pet_type": "custom", "custom_pet_id": pet_id})
            self.assertEqual(response.status_code, 404, response.text)
        await self.assert_no_custom_sessions()

    async def test_valid_custom_pet_creates_and_reuses_session(self):
        pet_id = await self.insert_custom_pet(self.user)
        with patch("backend.prompts.custom_pet.generate_welcome_messages", AsyncMock(return_value=["你好，我是团团"])) as welcome, \
             patch("backend.routers.sessions.memory_service.save_message", AsyncMock()) as save:
            body = {"pet_type": "custom", "custom_pet_id": pet_id}
            first = await self.client.post("/api/sessions", json=body)
            second = await self.client.post("/api/sessions", json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json()["session_id"], second.json()["session_id"])
        self.assertEqual(first.json()["welcome_message"]["content"], "你好，我是团团")
        self.assertTrue(second.json()["is_existing"])
        welcome.assert_awaited_once()
        save.assert_awaited_once()

    async def test_oversized_request_returns_413_and_health_stays_available(self):
        response = await self.client.post("/api/sessions", content=b"x" * (1024 * 1024 + 1), headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 413, response.text)
        self.assertEqual(response.json()["detail"], "Request too large")
        self.assertEqual((await self.client.get("/health")).status_code, 200)
