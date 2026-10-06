"""
用户事件流服务

user_events 表是各 Agent 之间的事件通道：
- emotion_observed：主 Agent 每轮顺手产出的情绪标签（零额外 LLM 成本）
- mood_analyzed：情绪 Agent 的完整结构化分析结果（mood_tendency 只是其快照）
- profile_updated：画像字段变更（含来源 source，区分主 Agent 同步写 / 画像 Agent 提取）

写入失败一律吞掉记日志：事件流是旁路数据，绝不影响主聊天链路。
"""
import json
import uuid
from typing import Optional, Dict, Any, List
from backend.database import get_db
from backend.logging_config import get_logger

logger = get_logger(__name__)


class EventService:
    async def append_event(
        self,
        user_id: str,
        session_id: Optional[str],
        event_type: str,
        payload: Dict[str, Any]
    ) -> None:
        """追加一条用户事件。所有异常均被捕获，不影响调用方。"""
        try:
            async with get_db() as db:
                await db.execute(
                    """
                    INSERT INTO user_events (event_id, user_id, session_id, event_type, payload_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (str(uuid.uuid4()), user_id, session_id, event_type,
                     json.dumps(payload, ensure_ascii=False))
                )
                await db.commit()
        except Exception as e:
            logger.warning("[event_service] 事件写入失败 type=%s user_id=%s: %s", event_type, user_id, e)

    async def recent_events(
        self,
        user_id: str,
        event_type: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """按时间正序返回最近事件（payload 已反序列化）。查询失败返回空列表。"""
        try:
            async with get_db() as db:
                if event_type:
                    cursor = await db.execute(
                        """
                        SELECT event_type, payload_json, created_at FROM user_events
                        WHERE user_id = ? AND event_type = ?
                        ORDER BY created_at DESC LIMIT ?
                        """,
                        (user_id, event_type, limit)
                    )
                else:
                    cursor = await db.execute(
                        """
                        SELECT event_type, payload_json, created_at FROM user_events
                        WHERE user_id = ?
                        ORDER BY created_at DESC LIMIT ?
                        """,
                        (user_id, limit)
                    )
                rows = await cursor.fetchall()

            events = []
            for row in reversed(rows):
                try:
                    payload = json.loads(row["payload_json"])
                except (json.JSONDecodeError, TypeError):
                    payload = {}
                events.append({
                    "event_type": row["event_type"],
                    "payload": payload,
                    "created_at": row["created_at"],
                })
            return events
        except Exception as e:
            logger.warning("[event_service] 事件查询失败 user_id=%s: %s", user_id, e)
            return []

    async def latest_event(self, user_id: str, event_type: str) -> Optional[Dict[str, Any]]:
        """返回某类型最新一条事件（作为分析水位线），无则 None。"""
        events = await self.recent_events(user_id, event_type=event_type, limit=1)
        return events[-1] if events else None


event_service = EventService()
