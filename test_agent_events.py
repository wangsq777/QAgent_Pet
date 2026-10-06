"""
Agent 协作优化（事件流 / 信号触发 / 信任闸门）纯逻辑单元测试

运行：python test_agent_events.py
覆盖不依赖数据库的部分：profile_update 解析、情绪信号规则、规则聚合、信任闸门过滤。
"""
import asyncio
import unittest

from backend.routers.chat import parse_emotional_reply
from backend.services.mood_agent import evaluate_mood_signals, aggregate_mood_by_rules
from backend.services.memory_service import MemoryService


def _event(emotion="neutral", need="unknown", intensity=1, risk_level="none"):
    return {
        "event_type": "emotion_observed",
        "payload": {"emotion": emotion, "need": need,
                    "intensity": intensity, "risk_level": risk_level},
        "created_at": "2026-09-10 12:00:00",
    }


class TestProfileUpdateParsing(unittest.TestCase):
    def test_profile_update_parsed(self):
        raw = '{"reply": "好呀", "emotion": "happy", "need": "celebration", "intensity": 2, "risk_level": "none", "profile_update": {"region": "上海"}}'
        emo = parse_emotional_reply(raw)
        self.assertEqual(emo.profile_update, {"region": "上海"})

    def test_profile_update_absent(self):
        raw = '{"reply": "嗯", "emotion": "neutral", "need": "unknown", "intensity": 1, "risk_level": "none"}'
        emo = parse_emotional_reply(raw)
        self.assertIsNone(emo.profile_update)

    def test_profile_update_invalid_type_dropped(self):
        raw = '{"reply": "嗯", "emotion": "neutral", "profile_update": "上海"}'
        emo = parse_emotional_reply(raw)
        self.assertIsNone(emo.profile_update)

    def test_profile_update_empty_dict_dropped(self):
        raw = '{"reply": "嗯", "emotion": "neutral", "profile_update": {}}'
        emo = parse_emotional_reply(raw)
        self.assertIsNone(emo.profile_update)

    def test_plain_text_fallback_has_no_profile_update(self):
        emo = parse_emotional_reply("这不是 JSON")
        self.assertIsNone(emo.profile_update)


class TestMoodSignals(unittest.TestCase):
    def test_empty_events_no_trigger(self):
        self.assertFalse(evaluate_mood_signals([]))

    def test_high_intensity_triggers(self):
        events = [_event(), _event(emotion="sad", intensity=4)]
        self.assertTrue(evaluate_mood_signals(events))

    def test_risk_level_triggers(self):
        events = [_event(), _event(risk_level="medium")]
        self.assertTrue(evaluate_mood_signals(events))

    def test_consecutive_negative_triggers(self):
        events = [_event("happy"), _event("sad"), _event("anxious"), _event("tired")]
        self.assertTrue(evaluate_mood_signals(events))

    def test_backlog_triggers(self):
        events = [_event("happy"), _event("neutral"), _event("happy"),
                  _event("neutral"), _event("happy")]
        self.assertTrue(evaluate_mood_signals(events))

    def test_calm_few_events_no_trigger(self):
        events = [_event("happy"), _event("neutral", intensity=2), _event("happy")]
        self.assertFalse(evaluate_mood_signals(events))

    def test_negative_streak_broken_by_positive(self):
        events = [_event("sad"), _event("happy"), _event("sad"), _event("sad")]
        # 末尾连续负面只有 2 条，且无高强度信号、积压不足 5 条
        self.assertFalse(evaluate_mood_signals(events))

    def test_bad_intensity_value_tolerated(self):
        events = [_event(intensity="abc")]
        self.assertFalse(evaluate_mood_signals(events))


class TestRuleAggregation(unittest.TestCase):
    def test_dominant_emotion_aggregated(self):
        events = [_event("anxious", need="calming", intensity=3)] * 4 + [_event("happy")]
        result = aggregate_mood_by_rules(events)
        self.assertIsNotNone(result)
        self.assertEqual(result["dominant_emotion"], "anxious")
        self.assertEqual(result["dominant_need"], "calming")
        self.assertEqual(result["mood_tendency"], "近期情绪以焦虑为主")
        self.assertEqual(result["analysis_source"], "rules")

    def test_high_intensity_suffix(self):
        events = [_event("sad", intensity=4)] * 3
        result = aggregate_mood_by_rules(events)
        self.assertIn("强度偏高", result["mood_tendency"])

    def test_too_few_events_returns_none(self):
        self.assertIsNone(aggregate_mood_by_rules([_event("sad")] * 2))

    def test_mixed_emotions_returns_none(self):
        events = [_event("sad"), _event("happy"), _event("anxious"), _event("tired")]
        self.assertIsNone(aggregate_mood_by_rules(events))

    def test_all_unknown_needs(self):
        events = [_event("tired")] * 3
        result = aggregate_mood_by_rules(events)
        self.assertIsNone(result["dominant_need"])


class TestMainAgentProfileGate(unittest.TestCase):
    """信任闸门：白名单字段过滤（merge/事件写入打桩，不触库）"""

    def _run_gate(self, update):
        from backend.services.event_service import event_service

        service = MemoryService()
        merged = {}
        events = []

        async def fake_merge(user_id, data):
            merged.update(data)

        async def fake_append(user_id, session_id, event_type, payload):
            events.append((event_type, payload))

        service.merge_user_profile = fake_merge
        original_append = event_service.append_event
        event_service.append_event = fake_append
        try:
            applied = asyncio.run(service.apply_main_agent_profile_update("u1", update))
        finally:
            event_service.append_event = original_append
        return applied, merged, events

    def test_region_allowed(self):
        applied, merged, events = self._run_gate({"region": "上海"})
        self.assertTrue(applied)
        self.assertEqual(merged, {"region": "上海"})
        # 写入成功时记录 profile_updated 事件，标注来源
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "profile_updated")
        self.assertEqual(events[0][1]["source"], "main_agent")

    def test_non_whitelisted_field_rejected(self):
        applied, merged, _ = self._run_gate({"identity": "老板"})
        self.assertFalse(applied)
        self.assertEqual(merged, {})

    def test_unknown_field_rejected(self):
        applied, merged, _ = self._run_gate({"system_role": "admin"})
        self.assertFalse(applied)
        self.assertEqual(merged, {})

    def test_injection_value_sanitized(self):
        applied, merged, _ = self._run_gate({"region": "上海" + "x" * 500})
        self.assertTrue(applied)
        self.assertEqual(len(merged["region"]), 100)  # FIELD_MAX_LEN["region"]

    def test_non_dict_rejected(self):
        applied, _, _ = self._run_gate("上海")
        self.assertFalse(applied)

    def test_empty_value_filtered(self):
        applied, merged, _ = self._run_gate({"region": "  "})
        self.assertFalse(applied)
        self.assertEqual(merged, {})


class TestProfileCache(unittest.TestCase):
    def test_cache_hit_returns_copy(self):
        service = MemoryService()
        service._profile_cache["u1"] = {"user_id": "u1", "region": "北京"}
        profile = asyncio.run(service.get_user_profile("u1"))
        self.assertEqual(profile["region"], "北京")
        # 返回副本：调用方修改不污染缓存
        profile["region"] = "篡改"
        self.assertEqual(service._profile_cache["u1"]["region"], "北京")


if __name__ == "__main__":
    unittest.main()
