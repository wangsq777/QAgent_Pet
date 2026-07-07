import json
import re
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from backend.database import get_db
from backend.schemas import ChatRequest, ChatResponse, MessageListResponse
from backend.services.llm_service import llm_service
from backend.services.memory_service import memory_service
from backend.services.weather_service import weather_service
from backend.services.tool_executor import tool_executor
from backend.services.user_profile_agent import user_profile_agent
from backend.services.mood_agent import mood_agent
from backend import prompts
from backend.services.embedding_service import embedding_service
from backend.prompts.custom_pet import _sanitize_user_input
from backend.logging_config import get_logger

limiter = Limiter(key_func=get_remote_address)

logger = get_logger(__name__)

# session_id / visit_id / pet_id 等 UUID 格式校验
UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE
)


def _validate_uuid(value: str, field_name: str = "id") -> None:
    if not value or not UUID_PATTERN.match(value):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name} format")


# 情感捕捉 Phase 0：情绪/情感需求/强度/风险枚举（非法值降级到安全默认）
VALID_EMOTIONS = {"happy", "sad", "anxious", "tired", "neutral"}
VALID_NEEDS = {
    "companionship", "venting", "validation", "encouragement", "advice",
    "calming", "distraction", "celebration", "reflection", "crisis_support", "unknown"
}
VALID_RISK_LEVELS = {"none", "low", "medium", "high"}


def _clamp_intensity(value) -> int:
    """强度合法范围 1-5，非法或越界降级为 1"""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return 1
    if v < 1:
        return 1
    if v > 5:
        return 5
    return v


def _normalize_emotion(value, default="neutral") -> str:
    v = (str(value).strip().lower()) if value is not None else default
    return v if v in VALID_EMOTIONS else default


def _normalize_need(value, default="unknown") -> str:
    v = (str(value).strip().lower()) if value is not None else default
    return v if v in VALID_NEEDS else default


def _normalize_risk(value, default="none") -> str:
    v = (str(value).strip().lower()) if value is not None else default
    return v if v in VALID_RISK_LEVELS else default


class EmotionalReply:
    """主 LLM 结构化情感输出的统一结果对象（内部使用，不直接暴露给前端）"""
    __slots__ = ("reply", "emotion", "need", "intensity", "risk_level")

    def __init__(self, reply: str, emotion: str, need: str, intensity: int, risk_level: str):
        self.reply = reply
        self.emotion = emotion
        self.need = need
        self.intensity = intensity
        self.risk_level = risk_level


def _parse_emotion_data(data: dict, raw: str) -> EmotionalReply:
    """从已解析的 dict 构造 EmotionalReply，缺字段走安全默认"""
    reply = data.get("reply")
    if not reply or not str(reply).strip():
        reply = raw  # 解析出 JSON 但 reply 为空时，退回原文兜底
    return EmotionalReply(
        reply=str(reply),
        emotion=_normalize_emotion(data.get("emotion")),
        need=_normalize_need(data.get("need")),
        intensity=_clamp_intensity(data.get("intensity", 1)),
        risk_level=_normalize_risk(data.get("risk_level")),
    )


def parse_emotional_reply(raw: Optional[str]) -> EmotionalReply:
    """
    解析主 LLM 的结构化情感输出，返回 EmotionalReply。
    兼容：
      - 新格式: {"reply","emotion","need","intensity","risk_level"}
      - 旧格式: {"reply","emotion"}（need/need/unknown, intensity=1, risk_level=none）
      - 异常格式: 解析失败时回复退回原文，情感字段降级为安全默认值。
    三层兜底：直接 JSON 解析 → 正则提取最外层 JSON → 纯文本原文。
    """
    if not raw:
        return EmotionalReply("", "neutral", "unknown", 1, "none")

    # 层 1：直接解析
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return _parse_emotion_data(data, raw)
    except Exception:
        pass

    # 层 2：正则提取包含 reply 的 JSON 块，从后向前（更可能是外层结构）
    matches = re.findall(r'\{.*?"reply".*?\}', raw, re.DOTALL)
    for candidate in reversed(matches):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                parsed = _parse_emotion_data(data, raw)
                if parsed.reply and parsed.reply != raw:
                    return parsed
        except Exception:
            continue

    # 层 3：纯文本兜底，不丢弃用户体验
    return EmotionalReply(raw, "neutral", "unknown", 1, "none")


def parse_structured_reply(raw: Optional[str]) -> tuple[str, str]:
    """
    旧接口保留兼容：返回 (reply_text, emotion_tag)。
    新代码应直接使用 parse_emotional_reply。
    """
    parsed = parse_emotional_reply(raw)
    return parsed.reply, parsed.emotion


router = APIRouter(prefix="/api/sessions", tags=["chat"])

# 注册工具
tool_executor.register("query_weather", weather_service.query_weather_tool)


def get_intimacy_level(intimacy: int) -> str:
    if intimacy <= 20:
        return "陌生"
    elif intimacy <= 50:
        return "熟悉"
    elif intimacy <= 80:
        return "亲密"
    else:
        return "挚友"


def calculate_intimacy_change(emotion_tag: str, need: str = "unknown", intensity: int = 1) -> int:
    """
    亲密度增长：结合 emotion + need + intensity，不再只对 sad 加权。
    负面情绪或高强度情感表达意味着用户更投入、更需要陪伴，亲密度增长更高（上限 3）。
    """
    base = 1
    # 情绪维度：sad/anxious/tired 偏负面，倾向于陪伴投入
    if emotion_tag in ("sad", "anxious"):
        base = 2
    elif emotion_tag == "tired":
        base = 1

    # 情感需求维度：需要陪伴/倾诉/认可/鼓励/安抚时，亲密度增长略高
    need_boost = 1 if need in (
        "companionship", "venting", "validation", "encouragement", "calming", "crisis_support"
    ) else 0

    # 强度维度：强度越高，亲密度增长越大
    intensity_bonus = max(0, intensity - 2)  # intensity<=2 不额外加，3 加1，4 加2，5 加3

    return min(3, base + need_boost + intensity_bonus)


def get_catchphrase(pet_type: str, custom_pet_id: str = None) -> str:
    """获取宠物的口头禅文本"""
    catchphrases = {
        "hot_dog": "汪汪，我好想你。",
        "cold_cat": "哼。本咪才不会关心你。",
        "mouse": "鼠鼠我啊......"
    }

    if pet_type != "custom" or not custom_pet_id:
        return catchphrases.get(pet_type, "")

    # 同步辅助：从数据库查询（需要在异步上下文中调用 async 版本）
    # 这里保留同步版本作为 fallback，实际调用优先用 get_catchphrase_async
    return catchphrases.get(pet_type, "")


async def get_catchphrase_async(pet_type: str, custom_pet_id: str = None, user_id: str = None) -> str:
    """异步获取宠物的口头禅文本（从数据库查询自定义宠物，带 user_id 归属校验）"""
    catchphrases = {
        "hot_dog": "汪汪，我好想你。",
        "cold_cat": "哼。本咪才不会关心你。",
        "mouse": "鼠鼠我啊......"
    }

    if pet_type != "custom" or not custom_pet_id:
        return catchphrases.get(pet_type, "")

    async with get_db() as db:
        # 带 user_id 归属校验：未传 user_id 时退化为仅按 pet_id 查（仅用于历史兼容，
        # 新调用方应始终传入 user_id），防止越权读取他人自定义宠物
        if user_id:
            cursor = await db.execute(
                "SELECT catchphrase FROM custom_pets WHERE pet_id = ? AND user_id = ?",
                (custom_pet_id, user_id)
            )
        else:
            cursor = await db.execute(
                "SELECT catchphrase FROM custom_pets WHERE pet_id = ?",
                (custom_pet_id,)
            )
        row = await cursor.fetchone()

    if row and row["catchphrase"]:
        return row["catchphrase"]

    return ""


async def get_custom_pet_info(custom_pet_id: str, user_id: str = None) -> dict | None:
    """从数据库查询自定义宠物信息，返回 {pet_name, system_prompt, catchphrase} 或 None

    带 user_id 归属校验：未传 user_id 时退化为仅按 pet_id 查（仅历史兼容），
    新调用方应始终传入 request.state.user_id，防止越权读取他人宠物。
    """
    async with get_db() as db:
        if user_id:
            cursor = await db.execute(
                "SELECT pet_name, system_prompt, catchphrase FROM custom_pets WHERE pet_id = ? AND user_id = ?",
                (custom_pet_id, user_id)
            )
        else:
            cursor = await db.execute(
                "SELECT pet_name, system_prompt, catchphrase FROM custom_pets WHERE pet_id = ?",
                (custom_pet_id,)
            )
        row = await cursor.fetchone()

    if not row:
        return None

    row_dict = dict(row)
    return {
        "pet_name": row_dict["pet_name"],
        "system_prompt": row_dict["system_prompt"],
        "catchphrase": row_dict["catchphrase"] or ""
    }


def detect_catchphrase_in_history(recent_messages: list, catchphrase: str) -> bool:
    """
    检测口头禅在最近消息中是否出现过
    使用简单子串匹配，覆盖 LLM 可能的微调变体
    """
    if not catchphrase:
        return False

    for msg in recent_messages:
        if msg.role == "assistant" and catchphrase in msg.content:
            return True

    return False


async def generate_safe_crisis_reply(pet_type: str, pet_name: str) -> str:
    """
    risk_level=high 时的安全回应生成：
    在安全规则约束下重新生成回复，保持宠物人格但优先安全。
    失败时返回固定安全模板。
    """
    safe_prompt = f"""你是 {pet_name}，一只陪伴主人的电子宠物。主人此刻表达了强烈的痛苦、绝望或自伤念头。

【安全规则——必须严格遵守】
1. 必须认真、温和、不轻描淡写，绝对不开玩笑、不用口头禅糊弄、不做日常分享。
2. 表达"我在这里陪你"，让主人感到被接住。
3. 鼓励主人联系现实中可以信任的人（家人、朋友、老师、医生）。
4. 如果主人面临即时危险，引导主人拨打当地紧急救援电话（如 110/120/心理援助热线）。
5. 明确说明：你是一只电子宠物，不是专业心理咨询或医疗服务，不能替代专业帮助。
6. 不要追问细节、不要评判、不要说"别这样想"否定感受。

请用 {pet_name} 的口吻写一段简短回复（60字以内），自然地落实以上规则，不要罗列规则本身。
直接输出回复内容，不要任何解释。"""

    result = await llm_service.chat(
        [{"role": "user", "content": safe_prompt}],
        temperature=0.5,
        max_tokens=800,
        caller="crisis_safe_reply",
        timeout=60.0
    )
    if result and len(result.strip()) >= 10:
        return result.strip()

    # 兜底安全模板
    return (
        f"（{pet_name}安静地待在你身边。）主人，我不知道你正在承受什么，但我会一直在这里陪你。"
        "如果你愿意，可以告诉身边信任的人，或者拨打心理援助热线。我只是电子宠物，没办法替代专业的帮助，"
        "但你不是一个人。"
    )


async def generate_share_daily_message(pet_type: str, pet_name: str) -> str:
    """生成宠物分享日常的消息"""
    import random
    
    daily_topics = {
        "hot_dog": [
            "主人不在的时候，汪汪把玩具球玩了一整天呢！",
            "今天发现了一个超好玩的蝴蝶，汪汪追了它好久！",
            "汪汪把最喜欢的狗窝整理了一下，现在超级舒服～",
            "门口的小松鼠又来了，汪汪和它聊了一会儿天！",
            "汪汪今天学会了新技能！主人回来要夸夸汪汪哦！"
        ],
        "cold_cat": [
            "......今天阳光很好，本喵晒了一会儿太阳。",
            "哼，那个逗猫棒被本喵成功捕获了。（才不是开心）",
            "邻居的猫又来挑衅了，本喵懒得理它。",
            "本喵今天睡了一个很舒服的午觉......才不是在等你。",
            "窗外的鸟好吵，本喵决定无视它们。"
        ],
        "mouse": [
            "鼠鼠今天找到了一颗超级好吃的瓜子！",
            "鼠鼠把窝重新装修了一下，现在暖暖的～",
            "鼠鼠鼓起勇气去探索了一下厨房，发现了好多新奇的东西！",
            "今天鼠鼠学会了新舞步，想跳给主人看！",
            "鼠鼠偷偷藏了一些好吃的，想和主人一起分享～"
        ]
    }
    
    topic = random.choice(daily_topics.get(pet_type, daily_topics["hot_dog"]))
    
    # 用 LLM 生成更自然的表达
    llm_content = await llm_service.generate_proactive_message(
        pet_type, pet_name, f"分享日常生活：{topic}"
    )
    
    if llm_content:
        return llm_content
    
    # Fallback：直接返回话题
    prefixes = {
        "hot_dog": "汪汪！告诉主人一个好消息！",
        "cold_cat": "......有个事情。",
        "mouse": "鼠鼠有话想和主人说......"
    }
    return f"{prefixes.get(pet_type, '')}{topic}"


async def build_context(session_id: str, pet_type: str, custom_pet_id: str = None) -> dict:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM pet_sessions WHERE session_id = ?",
            (session_id,)
        )
        session = await cursor.fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        session_dict = dict(session)

        pet_id = custom_pet_id or session_dict.get("custom_pet_id")

        pet_prompts = {
            "hot_dog": prompts.hot_dog,
            "cold_cat": prompts.cold_cat,
            "mouse": prompts.mouse
        }
        pet_info = pet_prompts.get(pet_type)
        pet_name = pet_info.PET_NAME if pet_info else "小可爱"
        system_prompt = ""

        if pet_type == "custom" and pet_id:
            custom_pet_info = await get_custom_pet_info(pet_id, session_dict.get("user_id"))
            if custom_pet_info:
                pet_name = custom_pet_info["pet_name"]
                system_prompt = custom_pet_info["system_prompt"]
            else:
                system_prompt = f"你是 {pet_name}，一只可爱的小宠物。"

        if not system_prompt:
            system_prompt = pet_info.get_system_prompt() if pet_info else "你是我的宠物。"

        # 用户画像（8 字段全量注入）
        user_profile = await memory_service.get_user_profile(session_dict["user_id"]) or {}
        profile_text = (
            f"地区: {user_profile.get('region', '未知')}; "
            f"身份: {user_profile.get('identity', '未知')}; "
            f"职业: {user_profile.get('occupation', '未知')}; "
            f"兴趣: {user_profile.get('interests', '未知')}; "
            f"性格: {user_profile.get('personality_hint', '未知')}; "
            f"活跃时段: {user_profile.get('active_hours', '未知')}; "
            f"情绪倾向: {user_profile.get('mood_tendency', '未知')}; "
            f"其他: {user_profile.get('extra_info', '未知')}"
        )

        now = datetime.now()
        time_str = now.strftime("现在是%Y年%m月%d日 %H:%M")
        intimacy_info = f"亲密度: {session_dict['intimacy']} ({get_intimacy_level(session_dict['intimacy'])}); 共聊天: {session_dict['total_chats']}轮"

        return {
            "system_prompt": system_prompt,
            "pet_name": pet_name,
            "user_profile": profile_text,
            "intimacy_info": intimacy_info,
            "skills": f"当前时间: {time_str}",
            "user_id": session_dict["user_id"],
        }


async def execute_tools_and_build_final_prompt(
    reply: str,
    original_prompt: str,
    pet_type: str
) -> tuple[str, dict, EmotionalReply]:
    """
    解析并执行 LLM 返回的工具调用，然后将工具结果反馈给 LLM 生成最终回复

    返回: (最终回复, 工具结果字典, 情感对象)
    """
    tool_calls = tool_executor.parse_tool_calls(reply)

    if not tool_calls:
        return reply, {}, EmotionalReply(reply, "neutral", "unknown", 1, "none")
    
    # 执行所有工具调用
    tool_results = {}
    for call in tool_calls:
        tool_name = call['tool']
        args = call['args']
        logger.info("调用工具: %s, 参数: %s", tool_name, args)
        
        result = await tool_executor.execute(tool_name, args)
        if result.success:
            tool_results[tool_name] = result.result
            logger.info("%s 执行成功: %s", tool_name, result.result)
        else:
            tool_results[tool_name] = f"错误: {result.error}"
            logger.warning("%s 执行失败: %s", tool_name, result.error)
    
    # 构建工具结果反馈 prompt
    tool_results_text = "\n".join([
        f"- {name}: {result}" for name, result in tool_results.items()
    ])
    
    # 清理回复中的工具调用部分
    cleaned_reply = tool_executor.remove_tool_calls(reply)
    
    # 始终将工具结果反馈给 LLM 生成最终回复（无论原始回复是否有文本）
    second_prompt = f"""{original_prompt}

【工具执行结果】
{tool_results_text}

请根据以上工具执行结果，用{pet_type}的性格风格回复。
原始回复中可能已包含一些文字，你可以在此基础上结合工具结果完善回复。
不要重复工具调用格式。以 JSON 格式输出，格式严格如下（不要 markdown 代码块，不要多余字段）：
{{"reply": "你的回复内容", "emotion": "用户情绪(happy/sad/anxious/tired/neutral)", "need": "情感需求(companionship/venting/validation/encouragement/advice/calming/distraction/celebration/reflection/crisis_support/unknown)", "intensity": 1, "risk_level": "none"}}
字段为系统内部判断，【不要】在 reply 里告诉用户"你现在是某某情绪"。risk_level=high 时回复必须认真严肃、不开玩笑、引导现实求助。"""

    raw_final = await llm_service.chat([{"role": "user", "content": second_prompt}], caller="tool_feedback", max_tokens=2000)

    # 如果 LLM 生成回复成功，返回结果（并清理可能的 TOOL_CALL 标记）
    if raw_final:
        # 解析结构化情感输出；工具轮次也提取情感字段供调用方使用
        tool_emo = parse_emotional_reply(raw_final)
        # 再次清理可能的 TOOL_CALL 标记
        cleaned_final = tool_executor.remove_tool_calls(tool_emo.reply)
        return cleaned_final, tool_results, tool_emo

    # LLM 调用失败时，生成包含工具结果的 fallback 回复
    if tool_results:
        # 从工具结果中提取关键信息
        weather_info = tool_results.get("query_weather", "")
        fallback_replys = {
            "hot_dog": f"汪汪！帮你查到了：{weather_info}",
            "cold_cat": f"哼...{weather_info}",
            "mouse": f"鼠鼠查到啦：{weather_info}"
        }
        fb = fallback_replys.get(pet_type, f"查询结果：{weather_info}")
        return fb, tool_results, EmotionalReply(fb, "neutral", "unknown", 1, "none")

    # 没有工具结果时使用原始回复
    final_reply = cleaned_reply or reply
    return final_reply, tool_results, EmotionalReply(final_reply, "neutral", "unknown", 1, "none")


@router.post("/{session_id}/chat", response_model=ChatResponse)
@limiter.limit("20/minute")
async def chat(request: Request, session_id: str, chat_req: ChatRequest, background_tasks: BackgroundTasks):
    _validate_uuid(session_id, "session_id")
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM pet_sessions WHERE session_id = ?",
            (session_id,)
        )
        session = await cursor.fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        session_dict = dict(session)

        # Session 归属验证
        if session_dict.get("user_id") != request.state.user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        pet_type = session_dict["pet_type"]
        custom_pet_id = session_dict.get("custom_pet_id")

        # 获取宠物名称（用于懒说话分支）
        pet_prompts = {
            "hot_dog": prompts.hot_dog,
            "cold_cat": prompts.cold_cat,
            "mouse": prompts.mouse
        }
        pet_info = pet_prompts.get(pet_type)
        pet_name = pet_info.PET_NAME if pet_info else "小可爱"
        
        # 自定义宠物使用自定义名称（带 user_id 归属校验）
        if pet_type == "custom" and custom_pet_id:
            custom_pet_info = await get_custom_pet_info(custom_pet_id, request.state.user_id)
            if custom_pet_info:
                pet_name = custom_pet_info["pet_name"]

        if session_dict["pet_status"] == "hiding":
            status_until = session_dict.get("status_until")
            if status_until and datetime.now() < datetime.fromisoformat(status_until):
                return ChatResponse(
                    reply=f"（{pet_name}躲起来了，暂时不敢出来...）",
                    emotion_tag="neutral",
                    intimacy=session_dict["intimacy"],
                    total_chats=session_dict["total_chats"],
                    schedule_extracted=None,
                    memory_compressed=False
                )
            else:
                await db.execute(
                    "UPDATE pet_sessions SET pet_status = 'normal', updated_at = ? WHERE session_id = ?",
                    (datetime.now(), session_id)
                )
                session_dict["pet_status"] = "normal"

        if pet_type == "cold_cat" and session_dict["total_chats"] > 0:
            import random
            if random.random() < 0.3:
                # 懒说话时仍需检查是否需要分享日常
                daily_share = None
                if random.random() < 0.33:
                    daily_content = await generate_share_daily_message(pet_type, pet_name)
                    await memory_service.save_message(session_id, "assistant", daily_content, is_proactive=True)
                    daily_share = {"role": "assistant", "content": daily_content}
                    logger.debug("Daily share triggered (cold_cat lazy): %s", daily_content)
                
                return ChatResponse(
                    reply="......",
                    emotion_tag="neutral",
                    intimacy=session_dict["intimacy"],
                    total_chats=session_dict["total_chats"],
                    schedule_extracted=None,
                    memory_compressed=False,
                    daily_share=daily_share
                )

    user_msg_id = await memory_service.save_message(session_id, "user", chat_req.content)

    # 为用户消息生成向量（异步，失败不影响主流程）
    user_msg_embedding = await embedding_service.embed(chat_req.content)

    # 对用户输入做安全过滤，防止 prompt 注入
    sanitized_content = _sanitize_user_input(chat_req.content)
    if user_msg_embedding:
        await embedding_service.save_vector(
            session_id=session_id,
            source_type="message",
            source_id=user_msg_id,
            content=chat_req.content,
            embedding=user_msg_embedding
        )

    context = await build_context(session_id, pet_type, custom_pet_id)
    pet_name = context.get("pet_name", "小可爱")

    # --- 双通道 + 向量检索 ---
    # 通道 A: 滑动窗口（最近 10 条）
    recent_messages = await memory_service.get_short_term_messages(session_id, limit=10)
    recent_ids = set(m.message_id for m in recent_messages)
    recent_conversation = "\n".join([
        f"{'主人' if m.role == 'user' else pet_name}: {m.content}"
        for m in recent_messages
    ]) or "（暂无对话）"

    # 口头禅概率控制（带 user_id 归属校验，防止越权读取他人自定义宠物口头禅）
    catchphrase = await get_catchphrase_async(pet_type, custom_pet_id, request.state.user_id)
    catchphrase_rule = ""
    if catchphrase:
        if detect_catchphrase_in_history(recent_messages, catchphrase):
            catchphrase_rule = "7. 本次回复请不要使用口头禅。\n"
        else:
            catchphrase_rule = f"7. 本次回复请使用口头禅：'{catchphrase}'\n"

    # 通道 B: 向量检索相关历史（top-5 消息）
    related_memories = "（暂无相关记忆）"
    if user_msg_embedding:
        related = await embedding_service.search(
            query_vector=user_msg_embedding,
            session_id=session_id,
            top_k=5,
            source_type="message",
            exclude_source_ids=list(recent_ids)
        )
        if related:
            related_memories = "\n".join([
                f"[相关记忆] {item['content'][:200]}"
                for item in related
            ])

    # 长期记忆: 向量检索 top-3
    long_term_memory = "（暂无长期记忆）"
    if user_msg_embedding:
        long_term_related = await embedding_service.search(
            query_vector=user_msg_embedding,
            session_id=session_id,
            top_k=3,
            source_type="long_term"
        )
        if long_term_related:
            long_term_memory = "\n".join([
                item["content"] for item in long_term_related
            ])

    # 位置提示
    saved_region = user_profile.get("region") if (user_profile := await memory_service.get_user_profile(context.get("user_id", ""))) else None
    location_hint = f"（根据历史记录，用户可能在 {saved_region}）" if saved_region else "（暂无用户位置信息）"

    skills_section = f"""{context['skills']}

【可用工具】
- query_weather: 查询天气
  用法: 当用户询问天气且你知道用户所在城市时调用
  参数: location (城市名，支持全球城市)

【重要】
Agent 需要自主从用户消息中识别位置信息：
- 如果用户提到城市名，请记住这个位置
- 如果用户询问天气但你不知道在哪，请先询问用户
{location_hint}
"""

    full_prompt = f"""<system>
{context['system_prompt']}
</system>

<long_term_memory>
{long_term_memory}
</long_term_memory>

<user_profile>
{context['user_profile']}
</user_profile>

<intimacy>
{context['intimacy_info']}
</intimacy>

<skills>
{skills_section}
</skills>

<recent_conversation>
{recent_conversation}
</recent_conversation>

<related_memories>
{related_memories}
</related_memories>

<current_message>
主人: {sanitized_content}
</current_message>

【重要规则】
1. 如果用户询问天气，你需要知道用户在哪：
   - 如果没有位置信息，请先询问用户所在城市
   - 如果用户指定了地点，使用用户指定的地点
2. 只有在知道用户所在城市后才能调用 query_weather 工具
3. 如果需要调用工具，请在回复中包含：
   [TOOL_CALL]
   {{"tool": "query_weather", "args": {{"location": "城市名"}}}}
   [/TOOL_CALL]
4. 如果用户的消息包含日程安排，在回复末尾添加：[SCHEDULE: 日程内容 | YYYY-MM-DD HH:MM]
5. 如果没有日程或不需要工具，不要添加任何标记
6. 调用工具后，系统会返回工具执行结果，请根据结果回复用户
{catchphrase_rule}
请用{pet_type}的性格风格回复，并以 JSON 格式输出，格式严格如下（不要 markdown 代码块，不要多余字段）：
{{"reply": "你的回复内容", "emotion": "用户情绪(happy/sad/anxious/tired/neutral)", "need": "用户此刻情感需求(companionship/venting/validation/encouragement/advice/calming/distraction/celebration/reflection/crisis_support/unknown)", "intensity": 1, "risk_level": "none"}}
字段说明（这些字段是系统内部判断，【不要】在 reply 里告诉用户"你现在是某某情绪/你需要某某"，回复保持自然）：
- emotion：你对当前用户消息情绪的判断，不是宠物自己的情绪。
- need：用户此刻更可能需要的情感支持方式（陪伴/倾诉/认可/鼓励/建议/安抚/转移注意力/庆祝/梳理/危机支持/不确定）。
- intensity：情绪强度 1-5，1 轻微、3 中等、5 极强。
- risk_level：安全风险等级 none/low/medium/high。当用户表达自伤、自杀、伤害他人、极度绝望时取 high。
【安全】当 risk_level=high 时，回复必须认真严肃，不开玩笑、不轻描淡写，鼓励用户联系现实中可信任的人或紧急求助，并说明本产品不是专业心理咨询。"""

    raw_reply = await llm_service.chat([{"role": "user", "content": full_prompt}], caller="main_chat", max_tokens=2000, timeout=90.0)
    if not raw_reply:
        fallback_replies = {
            "hot_dog": "汪？主人，我突然不知道说什么了...",
            "cold_cat": "......不想说话。",
            "mouse": "鼠鼠我啊......突然不知道怎么回答了......",
            "custom": f"{pet_name}啊......突然不知道怎么回答了......"
        }
        raw_reply = fallback_replies.get(pet_type, "突然不知道说什么了...")

    emo = parse_emotional_reply(raw_reply)

    # 执行工具调用并生成最终回复（ReAct 模式）
    reply, tool_results, tool_emo = await execute_tools_and_build_final_prompt(
        emo.reply, full_prompt, pet_type
    )

    # 协调首轮与工具路径的情感字段：
    # 工具路径若给出有意义的 emotion/need/intensity/risk，则覆盖首轮（首轮在工具场景下判断往往不准）
    emotion_tag = emo.emotion
    emotional_need = emo.need
    emotion_intensity = emo.intensity
    risk_level = emo.risk_level
    if tool_emo and (tool_emo.emotion != "neutral" or tool_emo.need != "unknown"
                     or tool_emo.intensity != 1 or tool_emo.risk_level != "none"):
        if tool_emo.emotion != "neutral":
            emotion_tag = tool_emo.emotion
        if tool_emo.need != "unknown":
            emotional_need = tool_emo.need
        if tool_emo.intensity != 1:
            emotion_intensity = tool_emo.intensity
        if tool_emo.risk_level != "none":
            risk_level = tool_emo.risk_level

    # risk_level=high 安全回应策略：在安全规则约束下重新生成回复，
    # 保持宠物人格但优先安全、不开玩笑、引导现实求助、声明非专业服务。
    if risk_level == "high" and emotional_need != "crisis_support":
        safe_reply = await generate_safe_crisis_reply(pet_type, pet_name)
        if safe_reply:
            reply = safe_reply
            emotional_need = "crisis_support"

    # 解析日程标记
    schedule_extracted = None
    schedule_pattern = r'\[SCHEDULE:\s*(.+?)\s*\|\s*(\d{4}-\d{2}-\d{2})(?:\s+\d{2}:\d{2})?\]'
    match = re.search(schedule_pattern, reply)
    if match:
        schedule_extracted = {
            "content": match.group(1).strip(),
            "scheduled_time": match.group(2).strip()
        }
        reply = re.sub(schedule_pattern, '', reply).strip()

    # 保存日程
    if schedule_extracted:
        schedule_id = str(uuid.uuid4())
        async with get_db() as db:
            await db.execute(
                """
                INSERT INTO schedules (schedule_id, session_id, content, scheduled_time, is_triggered, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (schedule_id, session_id, schedule_extracted["content"], schedule_extracted["scheduled_time"], 0, datetime.now())
            )
            await db.commit()
        logger.info("Schedule saved: %s", schedule_extracted)

    # 后台更新用户画像（使用用户画像总结 Agent，不阻塞响应）
    user_profile_updated = False
    async def _update_user_profile():
        try:
            existing_profile = await memory_service.get_user_profile(session_dict.get("user_id", ""))
            extracted_profile = await user_profile_agent.analyze_and_extract(
                recent_conversation,
                existing_profile
            )
            if extracted_profile:
                await memory_service.merge_user_profile(session_dict["user_id"], extracted_profile)
                logger.debug("User profile updated by agent: %s", extracted_profile)
        except Exception as e:
            logger.warning("User profile agent error: %s", e)
    background_tasks.add_task(_update_user_profile)

    assistant_msg_id = await memory_service.save_message(
        session_id, "assistant", reply,
        emotion_tag=emotion_tag,
        emotional_need=emotional_need,
        emotion_intensity=emotion_intensity,
        risk_level=risk_level
    )

    # 为助手回复生成向量
    assistant_embedding = await embedding_service.embed(reply)
    if assistant_embedding:
        await embedding_service.save_vector(
            session_id=session_id,
            source_type="message",
            source_id=assistant_msg_id,
            content=reply,
            embedding=assistant_embedding
        )

    intimacy_change = calculate_intimacy_change(emotion_tag, emotional_need, emotion_intensity)
    new_intimacy = min(100, session_dict["intimacy"] + intimacy_change)
    new_total_chats = session_dict["total_chats"] + 1

    # 话题感知压缩触发
    memory_compressed = False
    recent_for_compress = await memory_service.get_short_term_messages(session_id, limit=10)
    recent_dicts = [{"role": m.role, "content": m.content} for m in recent_for_compress]
    should_compress = await memory_service.should_compress(session_id, recent_dicts, chat_req.content)
    if should_compress:
        all_messages = await memory_service.get_short_term_messages(session_id, limit=100)
        window_ids = set(m.message_id for m in recent_for_compress)
        uncompress_messages = [m for m in all_messages if m.message_id not in window_ids]
        if uncompress_messages:
            await memory_service.compress_to_long_term(session_id, uncompress_messages[:15], pet_name)
            memory_compressed = True

    async with get_db() as db:
        await db.execute(
            "UPDATE pet_sessions SET intimacy = ?, total_chats = ?, last_interaction_at = ?, updated_at = ? WHERE session_id = ?",
            (new_intimacy, new_total_chats, datetime.now(), datetime.now(), session_id)
        )
        await db.commit()
    
    # 随机分享日常（约33%概率）
    daily_share = None

    import random
    if random.random() < 0.33 and session_dict.get("pet_status") != "hiding":
        daily_content = await generate_share_daily_message(pet_type, pet_name)
        await memory_service.save_message(session_id, "assistant", daily_content, is_proactive=True)
        daily_share = {"role": "assistant", "content": daily_content}
        logger.debug("Daily share triggered: %s", daily_content)

    # 每 5 轮触发后台情绪趋势分析（零阻塞）
    if mood_agent.should_trigger(session_id, new_total_chats):
        background_tasks.add_task(
            mood_agent.analyze_mood_tendency,
            user_id=session_dict["user_id"],
            session_id=session_id
        )

    return ChatResponse(
        reply=reply,
        emotion_tag=emotion_tag,
        intimacy=new_intimacy,
        total_chats=new_total_chats,
        schedule_extracted=schedule_extracted,
        memory_compressed=memory_compressed,
        daily_share=daily_share,
        user_profile_updated=user_profile_updated
    )


@router.get("/{session_id}/messages", response_model=MessageListResponse)
async def get_messages(session_id: str, request: Request):
    _validate_uuid(session_id, "session_id")
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT user_id FROM pet_sessions WHERE session_id = ?",
            (session_id,)
        )
        session = await cursor.fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        # Session 归属验证
        if dict(session).get("user_id") != request.state.user_id:
            raise HTTPException(status_code=403, detail="Access denied")

    messages = await memory_service.get_short_term_messages(session_id, limit=100)
    return MessageListResponse(messages=messages, total=len(messages))
