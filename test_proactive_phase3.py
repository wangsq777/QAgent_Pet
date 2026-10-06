"""
Phase 3 主动陪伴纯逻辑与物化行为单元测试

运行：python test_proactive_phase3.py
不依赖真实网络/LLM：天气与 LLM 全部打桩；数据库用内存 SQLite。
"""
import asyncio
import unittest
from datetime import datetime, timezone

import aiosqlite

from backend.services import proactive_service as ps
from backend.services.disturbance_policy import DEFAULT_PRIORITY, decide_event
from backend.services.weather_service import build_outfit_advice, evaluate_weather_significance

UTC = timezone.utc

# 测试中打开的连接统一由 _run 在同一个事件循环内关闭，
# 否则 aiosqlite 的工作线程会让解释器在退出时挂起（Python 3.9 非 daemon 线程 join）。
_OPEN_DBS = []


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        # 逐个在同一循环内关闭测试中打开的内存库连接，
        # 否则 aiosqlite 的工作线程会让解释器在退出时挂起（Python 3.9 非 daemon 线程 join）。
        for db in _OPEN_DBS:
            if db is not None:
                loop.run_until_complete(db.close())
        _OPEN_DBS.clear()
        loop.close()


# ---------- 内存库骨架 ----------

CREATE_PROACTIVE_EVENTS = """
CREATE TABLE proactive_events (
    event_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK(source_type IN ('schedule','concern','emotion_followup','inactivity','pet_initiated','sedentary','hydration','sleep','learning_nudge','learning_celebrate','weather')),
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
    updated_at_utc DATETIME NOT NULL
)
"""

CREATE_SETTINGS = """
CREATE TABLE proactive_settings (
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
    sedentary_enabled INTEGER NOT NULL DEFAULT 1,
    hydration_enabled INTEGER NOT NULL DEFAULT 1,
    sleep_enabled INTEGER NOT NULL DEFAULT 1,
    learning_enabled INTEGER NOT NULL DEFAULT 1,
    weather_enabled INTEGER NOT NULL DEFAULT 1,
    privacy_level TEXT NOT NULL DEFAULT 'generic',
    created_at_utc DATETIME NOT NULL,
    updated_at_utc DATETIME NOT NULL
)
"""

CREATE_PET_SESSIONS = """
CREATE TABLE pet_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    pet_type TEXT NOT NULL,
    custom_pet_id TEXT,
    last_interaction_at DATETIME,
    created_at DATETIME,
    updated_at DATETIME
)
"""

CREATE_LEARNING_SESSIONS = """
CREATE TABLE learning_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    pet_id TEXT NOT NULL,
    pet_source TEXT NOT NULL DEFAULT 'preset',
    status TEXT NOT NULL DEFAULT 'active',
    updated_at DATETIME
)
"""

CREATE_USER_PROFILES = "CREATE TABLE user_profiles (user_id TEXT UNIQUE NOT NULL, region TEXT)"

# materialize 开头会清理这两张表的过期草稿，测试骨架提供最小结构
CREATE_CONCERN_ITEMS = ("CREATE TABLE concern_items (user_id TEXT, session_id TEXT, status TEXT, "
                        "retention_expires_at_utc DATETIME, updated_at_utc DATETIME)")
CREATE_SCHEDULE_CANDIDATES = ("CREATE TABLE schedule_candidates (user_id TEXT, session_id TEXT, status TEXT, "
                              "expires_at_utc DATETIME, updated_at_utc DATETIME)")


async def _make_db():
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    for ddl in (CREATE_PROACTIVE_EVENTS, CREATE_SETTINGS, CREATE_PET_SESSIONS,
                CREATE_LEARNING_SESSIONS, CREATE_USER_PROFILES,
                CREATE_CONCERN_ITEMS, CREATE_SCHEDULE_CANDIDATES):
        await db.execute(ddl)
    _OPEN_DBS.append(db)
    return db


async def _seed(db, *, user="u1", session="s1", settings_overrides=None, profile_region=None):
    now = datetime(2026, 10, 3, 8, 30, tzinfo=UTC)
    now_text = "2026-10-03T08:30:00Z"
    await db.execute(
        "INSERT INTO pet_sessions(session_id,user_id,pet_type,last_interaction_at,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        (session, user, "hot_dog", now_text, now_text, now_text))
    settings = {"user_id": user, "timezone": "UTC", "quiet_start": "23:00", "quiet_end": "08:00",
                "created_at_utc": now_text, "updated_at_utc": now_text}
    settings.update(settings_overrides or {})
    cols = ",".join(settings.keys())
    await db.execute(f"INSERT INTO proactive_settings({cols}) VALUES({','.join('?' * len(settings))})",
                     tuple(settings.values()))
    if profile_region is not None:
        await db.execute("INSERT INTO user_profiles(user_id,region) VALUES(?,?)", (user, profile_region))
    await db.commit()
    return now


async def _events_by_source(db, source):
    cursor = await db.execute("SELECT * FROM proactive_events WHERE source_type=?", (source,))
    return [dict(r) for r in await cursor.fetchall()]


# ---------- 天气显著性判定 ----------

class TestWeatherSignificance(unittest.TestCase):
    def test_rain_threshold(self):
        ok, reason = evaluate_weather_significance(None, {"precip_probability": 40, "temp_max": 20, "temp_min": 10})
        self.assertTrue(ok)
        self.assertEqual(reason, "rain")
        ok, _ = evaluate_weather_significance(None, {"precip_probability": 39, "temp_max": 20, "temp_min": 10})
        self.assertFalse(ok)

    def test_cooling(self):
        today = {"temp_max": 25}
        ok, reason = evaluate_weather_significance(today, {"temp_max": 20, "temp_min": 15, "precip_probability": 0})
        self.assertTrue(ok)
        self.assertEqual(reason, "cooling")
        ok, _ = evaluate_weather_significance(today, {"temp_max": 21, "temp_min": 15, "precip_probability": 0})
        self.assertFalse(ok)

    def test_hot_and_cold(self):
        ok, reason = evaluate_weather_significance(None, {"temp_max": 33, "temp_min": 20, "precip_probability": 0})
        self.assertEqual((ok, reason), (True, "hot"))
        ok, reason = evaluate_weather_significance(None, {"temp_max": 5, "temp_min": 0, "precip_probability": 0})
        self.assertEqual((ok, reason), (True, "cold"))

    def test_not_significant(self):
        ok, reason = evaluate_weather_significance({"temp_max": 20}, {"temp_max": 24, "temp_min": 12, "precip_probability": 10})
        self.assertEqual((ok, reason), (False, None))

    def test_rain_takes_precedence(self):
        # 同时满足高温和降水时优先 rain（气泡带伞）
        _, reason = evaluate_weather_significance(None, {"temp_max": 35, "temp_min": 25, "precip_probability": 60})
        self.assertEqual(reason, "rain")


class TestOutfitAdviceTemplate(unittest.TestCase):
    def test_five_tiers(self):
        self.assertIn("防晒", build_outfit_advice({"temp_max": 35, "temp_min": 26, "precip_probability": 0}))
        self.assertIn("轻薄", build_outfit_advice({"temp_max": 28, "temp_min": 20, "precip_probability": 0}))
        self.assertIn("薄外套", build_outfit_advice({"temp_max": 20, "temp_min": 12, "precip_probability": 0}))
        self.assertIn("毛衣", build_outfit_advice({"temp_max": 10, "temp_min": 3, "precip_probability": 0}))
        self.assertIn("羽绒服", build_outfit_advice({"temp_max": 2, "temp_min": -4, "precip_probability": 0}))

    def test_rain_addon(self):
        advice = build_outfit_advice({"temp_max": 20, "temp_min": 12, "precip_probability": 55, "precip_sum": 3})
        self.assertIn("带伞", advice)

    def test_missing_temp_falls_back(self):
        advice = build_outfit_advice({"temp_max": None, "precip_probability": 0, "text": "多云"})
        self.assertIn("洋葱", advice)


# ---------- dedupe 键 ----------

class TestDedupeKeys(unittest.TestCase):
    def test_hydration_bucket_hour_granularity(self):
        a = ps.hydration_bucket_key(datetime(2026, 10, 3, 8, 5, tzinfo=UTC))
        b = ps.hydration_bucket_key(datetime(2026, 10, 3, 8, 59, tzinfo=UTC))
        c = ps.hydration_bucket_key(datetime(2026, 10, 3, 9, 0, tzinfo=UTC))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(a, "2026-10-03 08")

    def test_iso_week_key(self):
        # 2026-10-03 是 ISO 第 40 周；跨年到 2027-01-01 是第 53 周
        self.assertEqual(ps.iso_week_key(datetime(2026, 10, 3, tzinfo=UTC)), "2026-W40")
        self.assertEqual(ps.iso_week_key(datetime(2027, 1, 1, tzinfo=UTC)), "2026-W53")


# ---------- create_event 隐私气泡 ----------

class TestPrivacyBubble(unittest.TestCase):
    async def _scenario(self):
        db = await _make_db()
        await _seed(db)
        return db

    def test_generic_replaces_bubble(self):
        async def go():
            db = await self._scenario()
            when = datetime(2026, 10, 3, 9, tzinfo=UTC)
            cases = [
                ("schedule", "开会啦", "提醒"),
                ("concern", "体检报告", "问问"),
                ("emotion_followup", "上次吵架", "问问"),
                ("inactivity", "想你", "想你"),
                ("pet_initiated", "想聊", "想聊"),
                ("sedentary", "起来", "休息"),
                ("hydration", "喝水", "喝水"),
                ("sleep", "睡觉", "睡觉"),
                ("learning_nudge", "学习", "学习"),
                ("learning_celebrate", "真棒", "真棒"),
                ("weather", "带伞", "穿衣"),
            ]
            for source, passed, expected in cases:
                event = await ps.create_event(db, user_id="u1", session_id="s1", source_type=source,
                                              scheduled_at_utc=when, bubble_text=passed)
                self.assertEqual(event["bubble_text"], expected, source)
        _run(go())

    def test_privacy_topic_preserves_bubble(self):
        async def go():
            db = await self._scenario()
            event = await ps.create_event(db, user_id="u1", session_id="s1", source_type="sedentary",
                                          scheduled_at_utc=datetime(2026, 10, 3, 9, tzinfo=UTC),
                                          bubble_text="起来", privacy_level="topic")
            self.assertEqual(event["bubble_text"], "起来")
        _run(go())

    def test_medium_sensitivity_beats_privacy_topic(self):
        async def go():
            db = await self._scenario()
            event = await ps.create_event(db, user_id="u1", session_id="s1", source_type="concern",
                                          scheduled_at_utc=datetime(2026, 10, 3, 9, tzinfo=UTC),
                                          bubble_text="体检", sensitivity="medium", privacy_level="topic")
            self.assertEqual(event["bubble_text"], "问问")
        _run(go())

    def test_no_settings_row_defaults_generic(self):
        async def go():
            db = await _make_db()
            await db.execute("INSERT INTO pet_sessions(session_id,user_id,pet_type) VALUES('s1','u1','hot_dog')")
            await db.commit()
            event = await ps.create_event(db, user_id="u1", session_id="s1", source_type="schedule",
                                          scheduled_at_utc=datetime(2026, 10, 3, 9, tzinfo=UTC),
                                          bubble_text="开会")
            self.assertEqual(event["bubble_text"], "提醒")
        _run(go())

    def test_unsupported_source_rejected(self):
        async def go():
            db = await self._scenario()
            with self.assertRaises(ValueError):
                await ps.create_event(db, user_id="u1", session_id="s1", source_type="bogus",
                                      scheduled_at_utc=datetime(2026, 10, 3, 9, tzinfo=UTC))
        _run(go())


# ---------- 物化：idle_state 三源 ----------

class TestIdleMaterialize(unittest.TestCase):
    def test_idle_state_absent_skips_silently(self):
        async def go():
            db = await _make_db()
            await _seed(db)
            count = await ps.materialize_due_sources(db, user_id="u1", session_id="s1",
                                                     now=datetime(2026, 10, 3, 8, 30, tzinfo=UTC))
            for source in ("sedentary", "hydration", "sleep"):
                self.assertEqual(await _events_by_source(db, source), [])
            self.assertEqual(count, 0)
        _run(go())

    def test_sedentary_once_per_day(self):
        async def go():
            db = await _make_db()
            await _seed(db)
            now = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
            idle = {"idle_seconds": 0, "active_streak_minutes": 60}
            made = await ps.materialize_due_sources(db, user_id="u1", session_id="s1", now=now, idle_state=idle)
            # streak 60 同时满足喝水(>=45)与久坐(>=60)，各物化一条
            self.assertEqual(made, 2)
            events = await _events_by_source(db, "sedentary")
            self.assertEqual(len(events), 1)
            # 物化路径直插任务书指定的气泡「起来」（隐私泛化映射只作用于 create_event 调用方）
            self.assertEqual(events[0]["bubble_text"], "起来")
            self.assertEqual(events[0]["priority"], DEFAULT_PRIORITY["sedentary"])
            # 同一天再次物化不重复
            made = await ps.materialize_due_sources(db, user_id="u1", session_id="s1", now=now, idle_state=idle)
            self.assertEqual(made, 0)
            self.assertEqual(len(await _events_by_source(db, "sedentary")), 1)
            # 阈值以下不触发
            db2 = await _make_db()
            await _seed(db2)
            await ps.materialize_due_sources(db2, user_id="u1", session_id="s1", now=now,
                                             idle_state={"idle_seconds": 0, "active_streak_minutes": 59})
            self.assertEqual(await _events_by_source(db2, "sedentary"), [])
        _run(go())

    def test_hydration_window_and_dedupe(self):
        async def go():
            db = await _make_db()
            await _seed(db)
            idle = {"idle_seconds": 0, "active_streak_minutes": 45}
            t0 = datetime(2026, 10, 3, 10, 50, tzinfo=UTC)
            await ps.materialize_due_sources(db, user_id="u1", session_id="s1", now=t0, idle_state=idle)
            self.assertEqual(len(await _events_by_source(db, "hydration")), 1)
            # 30 分钟后：跨越时段键但不足 45 分钟，仍不重复
            await ps.materialize_due_sources(db, user_id="u1", session_id="s1",
                                             now=datetime(2026, 10, 3, 11, 20, tzinfo=UTC), idle_state=idle)
            self.assertEqual(len(await _events_by_source(db, "hydration")), 1)
            # 50 分钟后：新时段键且超过 45 分钟
            await ps.materialize_due_sources(db, user_id="u1", session_id="s1",
                                             now=datetime(2026, 10, 3, 11, 40, tzinfo=UTC), idle_state=idle)
            self.assertEqual(len(await _events_by_source(db, "hydration")), 2)
        _run(go())

    def test_sleep_only_in_quiet_hours(self):
        async def go():
            db = await _make_db()
            await _seed(db)
            idle = {"idle_seconds": 0, "active_streak_minutes": 15}
            # 白天不在安静时段
            await ps.materialize_due_sources(db, user_id="u1", session_id="s1",
                                             now=datetime(2026, 10, 3, 20, 0, tzinfo=UTC), idle_state=idle)
            self.assertEqual(await _events_by_source(db, "sleep"), [])
            # 凌晨 01:00 处于 23:00-08:00 安静时段
            made = await ps.materialize_due_sources(db, user_id="u1", session_id="s1",
                                                    now=datetime(2026, 10, 3, 1, 0, tzinfo=UTC), idle_state=idle)
            self.assertEqual(made, 1)
            events = await _events_by_source(db, "sleep")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["bubble_text"], "睡觉")
            # quiet_start 置空则跳过
            db2 = await _make_db()
            await _seed(db2, settings_overrides={"quiet_start": "", "quiet_end": ""})
            await ps.materialize_due_sources(db2, user_id="u1", session_id="s1",
                                             now=datetime(2026, 10, 3, 1, 0, tzinfo=UTC), idle_state=idle)
            self.assertEqual(await _events_by_source(db2, "sleep"), [])
        _run(go())

    def test_disabled_switches(self):
        async def go():
            db = await _make_db()
            await _seed(db, settings_overrides={"sedentary_enabled": 0, "hydration_enabled": 0, "sleep_enabled": 0})
            now = datetime(2026, 10, 3, 1, 0, tzinfo=UTC)
            idle = {"idle_seconds": 0, "active_streak_minutes": 120}
            made = await ps.materialize_due_sources(db, user_id="u1", session_id="s1", now=now, idle_state=idle)
            self.assertEqual(made, 0)
        _run(go())


# ---------- 物化：学习停滞 ----------

class TestLearningNudge(unittest.TestCase):
    async def _seeded(self, updated_at, settings_overrides=None):
        db = await _make_db()
        await _seed(db, settings_overrides=settings_overrides)
        await db.execute(
            "INSERT INTO learning_sessions(id,user_id,pet_id,pet_source,status,updated_at) VALUES('ls1','u1','hot_dog','preset','active',?)",
            (updated_at,))
        await db.commit()
        return db

    def test_stale_session_triggers_weekly_nudge(self):
        async def go():
            db = await self._seeded("2026-09-29T00:00:00+00:00")  # 4 天前
            now = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
            made = await ps.materialize_due_sources(db, user_id="u1", session_id="s1", now=now)
            self.assertEqual(made, 1)
            events = await _events_by_source(db, "learning_nudge")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["bubble_text"], "学习")
            self.assertIn("2026-W40", events[0]["dedupe_key"])
            # 同周再次物化不重复
            made = await ps.materialize_due_sources(db, user_id="u1", session_id="s1", now=now)
            self.assertEqual(made, 0)
        _run(go())

    def test_recent_or_inactive_session_skips(self):
        async def go():
            db = await self._seeded("2026-10-02T00:00:00+00:00")  # 1 天前
            await ps.materialize_due_sources(db, user_id="u1", session_id="s1",
                                             now=datetime(2026, 10, 3, 10, 0, tzinfo=UTC))
            self.assertEqual(await _events_by_source(db, "learning_nudge"), [])
            db2 = await self._seeded("2026-09-29T00:00:00+00:00")
            await db2.execute("UPDATE learning_sessions SET status='paused' WHERE id='ls1'")
            await db2.commit()
            await ps.materialize_due_sources(db2, user_id="u1", session_id="s1",
                                             now=datetime(2026, 10, 3, 10, 0, tzinfo=UTC))
            self.assertEqual(await _events_by_source(db2, "learning_nudge"), [])
        _run(go())

    def test_learning_switch_off(self):
        async def go():
            db = await self._seeded("2026-09-29T00:00:00+00:00", settings_overrides={"learning_enabled": 0})
            made = await ps.materialize_due_sources(db, user_id="u1", session_id="s1",
                                                    now=datetime(2026, 10, 3, 10, 0, tzinfo=UTC))
            self.assertEqual(made, 0)
        _run(go())


# ---------- 物化：早晨天气 ----------

class TestWeatherMaterialize(unittest.TestCase):
    FORECAST_RAIN = {
        "city": "上海", "country": "中国", "timezone": "Asia/Shanghai",
        "today": {"date": "2026-10-03", "temp_max": 24.0, "temp_min": 18.0, "precip_probability": 10,
                  "precip_sum": 0.0, "weathercode": 2, "text": "多云"},
        "tomorrow": {"date": "2026-10-04", "temp_max": 22.0, "temp_min": 17.0, "precip_probability": 60,
                     "precip_sum": 5.0, "weathercode": 63, "text": "中雨"},
    }
    FORECAST_CALM = {
        "city": "上海", "country": "中国", "timezone": "Asia/Shanghai",
        "today": {"date": "2026-10-03", "temp_max": 24.0, "temp_min": 18.0, "precip_probability": 10,
                  "precip_sum": 0.0, "weathercode": 2, "text": "多云"},
        "tomorrow": {"date": "2026-10-04", "temp_max": 24.0, "temp_min": 18.0, "precip_probability": 10,
                     "precip_sum": 0.0, "weathercode": 2, "text": "多云"},
    }

    def _stub_forecast(self, result):
        async def fake(city):
            return result
        original = ps.weather_service.get_daily_forecast
        ps.weather_service.get_daily_forecast = fake
        self.addCleanup(setattr, ps.weather_service, "get_daily_forecast", original)

    def test_significant_rain_creates_umbrella_event(self):
        async def go():
            self._stub_forecast(self.FORECAST_RAIN)
            db = await _make_db()
            await _seed(db, profile_region="上海")
            made = await ps.materialize_due_sources(db, user_id="u1", session_id="s1",
                                                    now=datetime(2026, 10, 3, 8, 30, tzinfo=UTC))
            self.assertEqual(made, 1)
            events = await _events_by_source(db, "weather")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["bubble_text"], "带伞")
            ctx = __import__("json").loads(events[0]["message_context_json"])
            self.assertEqual(ctx, {"kind": "weather_outfit", "city": "上海"})
            self.assertIn("点开看看", events[0]["rendered_message"])
            # 当天去重
            made = await ps.materialize_due_sources(db, user_id="u1", session_id="s1",
                                                    now=datetime(2026, 10, 3, 8, 45, tzinfo=UTC))
            self.assertEqual(made, 0)
        _run(go())

    def test_calm_or_outside_window_or_no_region_skips(self):
        async def go():
            self._stub_forecast(self.FORECAST_CALM)
            db = await _make_db()
            await _seed(db, profile_region="上海")
            made = await ps.materialize_due_sources(db, user_id="u1", session_id="s1",
                                                    now=datetime(2026, 10, 3, 8, 30, tzinfo=UTC))
            self.assertEqual(made, 0)

            self._stub_forecast(self.FORECAST_RAIN)
            db2 = await _make_db()
            await _seed(db2, profile_region="上海")
            # 10:00 超出 08:00-09:00 窗口
            made = await ps.materialize_due_sources(db2, user_id="u1", session_id="s1",
                                                    now=datetime(2026, 10, 3, 10, 0, tzinfo=UTC))
            self.assertEqual(made, 0)

            db3 = await _make_db()
            await _seed(db3)  # 无 region
            made = await ps.materialize_due_sources(db3, user_id="u1", session_id="s1",
                                                    now=datetime(2026, 10, 3, 8, 30, tzinfo=UTC))
            self.assertEqual(made, 0)
        _run(go())

    def test_weather_switch_off(self):
        async def go():
            self._stub_forecast(self.FORECAST_RAIN)
            db = await _make_db()
            await _seed(db, profile_region="上海", settings_overrides={"weather_enabled": 0})
            made = await ps.materialize_due_sources(db, user_id="u1", session_id="s1",
                                                    now=datetime(2026, 10, 3, 8, 30, tzinfo=UTC))
            self.assertEqual(made, 0)
        _run(go())


# ---------- 每日上限：每源独立计数 ----------

class TestPerSourceDailyLimit(unittest.TestCase):
    def _settings(self, **overrides):
        base = {"enabled": 1, "timezone": "UTC", "quiet_start": "23:00", "quiet_end": "08:00",
                "max_general_per_day": 1, "min_interval_minutes": 1}  # 1 分钟：0 会被 decide_event 的 or 回退成 120
        base.update(overrides)
        return base

    def _event(self, source):
        return {"source_type": source, "status": "pending", "expires_at_utc": None,
                "consecutive_ignored": 0}

    def test_same_source_snoozes_other_source_delivers(self):
        now = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
        delivered_today = [{"source_type": "hydration", "delivered_at_utc": "2026-10-03T09:00:00Z"}]
        # 同源的第二条被日上限压住
        decision = decide_event(self._event("hydration"), self._settings(), delivered_today, now=now)
        self.assertEqual((decision.decision, decision.reason), ("snooze", "daily_limit"))
        # 不同源不受限（旧全源口径会把新源全饿死）
        decision = decide_event(self._event("sedentary"), self._settings(), delivered_today, now=now)
        self.assertEqual(decision.decision, "deliver")

    def test_schedule_not_counted_in_general_limit(self):
        now = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
        delivered_today = [{"source_type": "schedule", "delivered_at_utc": "2026-10-03T09:00:00Z"}]
        decision = decide_event(self._event("hydration"), self._settings(), delivered_today, now=now)
        self.assertEqual(decision.decision, "deliver")

    def test_learning_celebrate_uses_learning_switch(self):
        now = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
        off = self._settings(learning_enabled=0)
        decision = decide_event(self._event("learning_celebrate"), off, [], now=now)
        self.assertEqual((decision.decision, decision.reason), ("suppress", "disabled"))
        decision = decide_event(self._event("learning_nudge"), off, [], now=now)
        self.assertEqual((decision.decision, decision.reason), ("suppress", "disabled"))
        on = self._settings(learning_enabled=1)
        self.assertEqual(decide_event(self._event("learning_celebrate"), on, [], now=now).decision, "deliver")


# ---------- sleep 提醒豁免 quiet hours ----------

class TestSleepExemptsQuietHours(unittest.TestCase):
    QUIET_NOW = datetime(2026, 10, 3, 1, 0, tzinfo=UTC)  # 23:00-08:00 安静时段内

    def _settings(self, **overrides):
        base = {"enabled": 1, "timezone": "UTC", "quiet_start": "23:00", "quiet_end": "08:00",
                "max_general_per_day": 1, "min_interval_minutes": 1}
        base.update(overrides)
        return base

    def _event(self, source):
        return {"source_type": source, "status": "pending", "expires_at_utc": None,
                "consecutive_ignored": 0}

    def test_sleep_delivers_during_quiet_hours(self):
        # sleep 只在安静时段物化，豁免 quiet hours 压制，不再 +2h snooze 到过期
        decision = decide_event(self._event("sleep"), self._settings(), [], now=self.QUIET_NOW)
        self.assertEqual((decision.decision, decision.reason), ("deliver", "eligible"))

    def test_other_sources_still_snoozed_in_quiet_hours(self):
        decision = decide_event(self._event("hydration"), self._settings(), [], now=self.QUIET_NOW)
        self.assertEqual((decision.decision, decision.reason), ("snooze", "quiet_hours"))
        self.assertIsNotNone(decision.next_attempt_at_utc)

    def test_sleep_switch_off_still_suppresses(self):
        decision = decide_event(self._event("sleep"), self._settings(sleep_enabled=0), [], now=self.QUIET_NOW)
        self.assertEqual((decision.decision, decision.reason), ("suppress", "disabled"))

    def test_sleep_daily_limit_still_applies(self):
        delivered = [{"source_type": "sleep", "delivered_at_utc": "2026-10-03T00:30:00Z"}]
        decision = decide_event(self._event("sleep"), self._settings(), delivered, now=self.QUIET_NOW)
        self.assertEqual((decision.decision, decision.reason), ("snooze", "daily_limit"))

    def test_sleep_rate_limit_still_applies(self):
        # 跨源 min_interval：1 分钟前刚送过喝水，sleep 仍被限频
        delivered = [{"source_type": "hydration", "delivered_at_utc": "2026-10-03T00:59:30Z"}]
        decision = decide_event(self._event("sleep"), self._settings(), delivered, now=self.QUIET_NOW)
        self.assertEqual((decision.decision, decision.reason), ("snooze", "rate_limit"))


# ---------- 章节完成庆祝事件 ----------

class TestLearningCelebrate(unittest.TestCase):
    def _stub_chat(self, result=None, exc=None):
        async def fake(messages, **kwargs):
            if exc:
                raise exc
            return result
        original = ps.llm_service.chat
        ps.llm_service.chat = fake
        self.addCleanup(setattr, ps.llm_service, "chat", original)

    def test_celebrate_with_llm_text(self):
        async def go():
            self._stub_chat(result="汪汪！主人又拿下一张地图！")
            db = await _make_db()
            await _seed(db)
            event = await ps.create_learning_celebrate_event(
                db, user_id="u1", learning_session_id="ls1", pet_id="hot_dog", pet_source="preset",
                chapter_id=2, chapter_title="核心模块", now=datetime(2026, 10, 3, 10, 0, tzinfo=UTC))
            self.assertIsNotNone(event)
            self.assertEqual(event["source_type"], "learning_celebrate")
            self.assertEqual(event["bubble_text"], "真棒")
            self.assertEqual(event["rendered_message"], "汪汪！主人又拿下一张地图！")
            import json
            ctx = json.loads(event["message_context_json"])
            self.assertEqual(ctx["kind"], "learning_celebrate")
            self.assertEqual(ctx["chapter_id"], 2)
            self.assertEqual(ctx["chapter_title"], "核心模块")
        _run(go())

    def test_celebrate_llm_failure_falls_back(self):
        async def go():
            self._stub_chat(exc=RuntimeError("boom"))
            db = await _make_db()
            await _seed(db)
            event = await ps.create_learning_celebrate_event(
                db, user_id="u1", learning_session_id="ls1", pet_id="hot_dog", pet_source="preset",
                chapter_id=1, chapter_title="项目整体介绍", now=datetime(2026, 10, 3, 10, 0, tzinfo=UTC))
            self.assertEqual(event["rendered_message"], "太棒了！又攻下一章 🎉")
        _run(go())

    def test_celebrate_without_session_returns_none(self):
        async def go():
            self._stub_chat(result="hi")
            db = await _make_db()
            await db.execute("INSERT INTO proactive_settings(user_id,created_at_utc,updated_at_utc) VALUES('u1','2026-10-03T08:30:00Z','2026-10-03T08:30:00Z')")
            await db.commit()
            event = await ps.create_learning_celebrate_event(
                db, user_id="u1", learning_session_id="ls1", pet_id="hot_dog", pet_source="preset",
                chapter_id=1, chapter_title="x", now=datetime(2026, 10, 3, 10, 0, tzinfo=UTC))
            self.assertIsNone(event)
        _run(go())


if __name__ == "__main__":
    unittest.main()
