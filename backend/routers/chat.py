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


def parse_structured_reply(raw: Optional[str]) -> tuple[str, str]:
    """
    解析主 LLM 的结构化输出，返回 (reply_text, emotion_tag)。
    失败时返回 (raw 或空字符串, "neutral")。
    """
    if not raw:
        return "", "neutral"

    valid_emotions = {"happy", "sad", "anxious", "tired", "neutral"}
    try:
        data = json.loads(raw)
        reply = data.get("reply", raw)
        emotion = data.get("emotion", "neutral").strip().lower()
        if emotion not in valid_emotions:
            emotion = "neutral"
        return reply, emotion
    except Exception:
        # 兜底：匹配包含 reply 与 emotion 的 JSON 块，优先取最后一个匹配（更可能是外层结构）
        matches = re.findall(r'\{.*?"reply".*?"emotion".*?\}', raw, re.DOTALL)
        for candidate in reversed(matches):
            try:
                data = json.loads(candidate)
                reply = data.get("reply", "")
                if not reply:
                    continue
                emotion = data.get("emotion", "neutral").strip().lower()
                if emotion not in valid_emotions:
                    emotion = "neutral"
                return reply, emotion
            except Exception:
                continue
        return raw, "neutral"


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


def calculate_intimacy_change(emotion_tag: str) -> int:
    if emotion_tag == "sad":
        return 3
    return 1


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


async def get_catchphrase_async(pet_type: str, custom_pet_id: str = None) -> str:
    """异步获取宠物的口头禅文本（从数据库查询自定义宠物）"""
    catchphrases = {
        "hot_dog": "汪汪，我好想你。",
        "cold_cat": "哼。本咪才不会关心你。",
        "mouse": "鼠鼠我啊......"
    }

    if pet_type != "custom" or not custom_pet_id:
        return catchphrases.get(pet_type, "")

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT catchphrase FROM custom_pets WHERE pet_id = ?",
            (custom_pet_id,)
        )
        row = await cursor.fetchone()

    if row and row["catchphrase"]:
        return row["catchphrase"]

    return ""


async def get_custom_pet_info(custom_pet_id: str) -> dict | None:
    """从数据库查询自定义宠物信息，返回 {pet_name, system_prompt, catchphrase} 或 None"""
    async with get_db() as db:
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
            custom_pet_info = await get_custom_pet_info(pet_id)
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
) -> tuple[str, dict, str]:
    """
    解析并执行 LLM 返回的工具调用，然后将工具结果反馈给 LLM 生成最终回复

    返回: (最终回复, 工具结果字典, 情绪标签)
    """
    tool_calls = tool_executor.parse_tool_calls(reply)

    if not tool_calls:
        return reply, {}, "neutral"
    
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
{{"reply": "你的回复内容", "emotion": "用户情绪标签(happy/sad/anxious/tired/neutral)"}}
其中 emotion 是你对当前用户消息情绪的判断，不是宠物自己的情绪。"""

    raw_final = await llm_service.chat([{"role": "user", "content": second_prompt}], caller="tool_feedback")

    # 如果 LLM 生成回复成功，返回结果（并清理可能的 TOOL_CALL 标记）
    if raw_final:
        # 解析结构化输出；工具轮次也提取 emotion 供调用方使用
        parsed_final, tool_emotion = parse_structured_reply(raw_final)
        # 再次清理可能的 TOOL_CALL 标记
        cleaned_final = tool_executor.remove_tool_calls(parsed_final)
        return cleaned_final, tool_results, tool_emotion

    # LLM 调用失败时，生成包含工具结果的 fallback 回复
    if tool_results:
        # 从工具结果中提取关键信息
        weather_info = tool_results.get("query_weather", "")
        fallback_replys = {
            "hot_dog": f"汪汪！帮你查到了：{weather_info}",
            "cold_cat": f"哼...{weather_info}",
            "mouse": f"鼠鼠查到啦：{weather_info}"
        }
        return fallback_replys.get(pet_type, f"查询结果：{weather_info}"), tool_results, "neutral"

    # 没有工具结果时使用原始回复
    return cleaned_reply or reply, tool_results, "neutral"


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
        
        # 自定义宠物使用自定义名称
        if pet_type == "custom" and custom_pet_id:
            custom_pet_info = await get_custom_pet_info(custom_pet_id)
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

    # 口头禅概率控制
    catchphrase = await get_catchphrase_async(pet_type, custom_pet_id)
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
{{"reply": "你的回复内容", "emotion": "用户情绪标签(happy/sad/anxious/tired/neutral)"}}
其中 emotion 是你对当前用户消息情绪的判断，不是宠物自己的情绪。"""

    raw_reply = await llm_service.chat([{"role": "user", "content": full_prompt}], caller="main_chat", timeout=90.0)
    if not raw_reply:
        fallback_replies = {
            "hot_dog": "汪？主人，我突然不知道说什么了...",
            "cold_cat": "......不想说话。",
            "mouse": "鼠鼠我啊......突然不知道怎么回答了......",
            "custom": f"{pet_name}啊......突然不知道怎么回答了......"
        }
        raw_reply = fallback_replies.get(pet_type, "突然不知道说什么了...")

    reply, emotion_tag = parse_structured_reply(raw_reply)

    # 执行工具调用并生成最终回复（ReAct 模式）
    reply, tool_results, tool_emotion = await execute_tools_and_build_final_prompt(
        reply, full_prompt, pet_type
    )

    # 如果工具路径的二次 LLM 给出了有意义的情绪标签，则覆盖首轮情绪
    if tool_emotion and tool_emotion != "neutral":
        emotion_tag = tool_emotion

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

    assistant_msg_id = await memory_service.save_message(session_id, "assistant", reply, emotion_tag=emotion_tag)

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

    intimacy_change = calculate_intimacy_change(emotion_tag)
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
