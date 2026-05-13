import re
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException
from backend.database import get_db
from backend.schemas import ChatRequest, ChatResponse, MessageListResponse
from backend.services.llm_service import llm_service
from backend.services.memory_service import memory_service
from backend.services.weather_service import weather_service
from backend.services.tool_executor import tool_executor
from backend.services.user_profile_agent import user_profile_agent
from backend import prompts

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


async def build_context(session_id: str, pet_type: str) -> dict:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM pet_sessions WHERE session_id = ?",
            (session_id,)
        )
        session = await cursor.fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        session_dict = dict(session)

        pet_prompts = {
            "hot_dog": prompts.hot_dog,
            "cold_cat": prompts.cold_cat,
            "mouse": prompts.mouse
        }
        pet_info = pet_prompts.get(pet_type)

        long_term_memories = await memory_service.get_long_term_memories(session_id)
        long_term_text = "\n".join([m["summary"] for m in long_term_memories])

        user_profile = await memory_service.get_user_profile(session_dict["user_id"]) or {}

        short_term_messages = await memory_service.get_short_term_messages(session_id, limit=40)
        conversation_text = "\n".join([
            f"{'主人' if m.role == 'user' else pet_info.PET_NAME}: {m.content}"
            for m in short_term_messages
        ])

        now = datetime.now()
        time_str = now.strftime("现在是%Y年%m月%d日 %H:%M")

        context = {
            "system_prompt": pet_info.get_system_prompt(),
            "long_term_memory": long_term_text or "（暂无长期记忆）",
            "user_profile": f"地区: {user_profile.get('region', '未知')}; 身份: {user_profile.get('identity', '未知')}; 兴趣: {user_profile.get('interests', '未知')}",
            "intimacy_info": f"亲密度: {session_dict['intimacy']} ({get_intimacy_level(session_dict['intimacy'])}); 共聊天: {session_dict['total_chats']}轮",
            "skills": f"当前时间: {time_str}",
            "conversation": conversation_text or "（暂无对话）"
        }

        return context


async def execute_tools_and_build_final_prompt(
    reply: str, 
    original_prompt: str, 
    pet_type: str
) -> tuple[str, dict]:
    """
    解析并执行 LLM 返回的工具调用，然后将工具结果反馈给 LLM 生成最终回复
    
    返回: (最终回复, 工具结果字典)
    """
    tool_calls = tool_executor.parse_tool_calls(reply)
    
    if not tool_calls:
        return reply, {}
    
    # 执行所有工具调用
    tool_results = {}
    for call in tool_calls:
        tool_name = call['tool']
        args = call['args']
        print(f"[Tool] 调用工具: {tool_name}, 参数: {args}")
        
        result = await tool_executor.execute(tool_name, args)
        if result.success:
            tool_results[tool_name] = result.result
            print(f"[Tool] {tool_name} 执行成功: {result.result}")
        else:
            tool_results[tool_name] = f"错误: {result.error}"
            print(f"[Tool] {tool_name} 执行失败: {result.error}")
    
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
请直接输出最终回复内容，不要重复工具调用格式。"""
    
    final_reply = await llm_service.chat([{"role": "user", "content": second_prompt}], caller="tool_feedback")
    
    # 如果 LLM 生成回复成功，返回结果（并清理可能的 TOOL_CALL 标记）
    if final_reply:
        # 再次清理可能的 TOOL_CALL 标记
        cleaned_final = tool_executor.remove_tool_calls(final_reply)
        return cleaned_final, tool_results
    
    # LLM 调用失败时，生成包含工具结果的 fallback 回复
    if tool_results:
        # 从工具结果中提取关键信息
        weather_info = tool_results.get("query_weather", "")
        fallback_replys = {
            "hot_dog": f"汪汪！帮你查到了：{weather_info}",
            "cold_cat": f"哼...{weather_info}",
            "mouse": f"鼠鼠查到啦：{weather_info}"
        }
        return fallback_replys.get(pet_type, f"查询结果：{weather_info}"), tool_results
    
    # 没有工具结果时使用原始回复
    return cleaned_reply or reply, tool_results


@router.post("/{session_id}/chat", response_model=ChatResponse)
async def chat(session_id: str, request: ChatRequest):
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM pet_sessions WHERE session_id = ?",
            (session_id,)
        )
        session = await cursor.fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        session_dict = dict(session)
        pet_type = session_dict["pet_type"]

        if session_dict["pet_status"] == "hiding":
            status_until = session_dict.get("status_until")
            if status_until and datetime.now() < datetime.fromisoformat(status_until):
                return ChatResponse(
                    reply="（鼠鼠躲起来了，暂时不敢出来...）",
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

        # 提前获取 pet_info（懒说话分支需要用到）
        _pet_prompts = {"hot_dog": prompts.hot_dog, "cold_cat": prompts.cold_cat, "mouse": prompts.mouse}
        pet_info = _pet_prompts.get(pet_type)

        if pet_type == "cold_cat" and session_dict["total_chats"] > 0:
            import random
            if random.random() < 0.3:
                # 懒说话时仍需检查是否需要分享日常
                daily_share = None
                if random.randint(1, 100) % 3 == 0:
                    daily_content = await generate_share_daily_message(pet_type, pet_info.PET_NAME)
                    await memory_service.save_message(session_id, "assistant", daily_content, is_proactive=True)
                    daily_share = {"role": "assistant", "content": daily_content}
                    print(f"[DEBUG] Daily share triggered (cold_cat lazy): {daily_content}")
                
                return ChatResponse(
                    reply="......",
                    emotion_tag="neutral",
                    intimacy=session_dict["intimacy"],
                    total_chats=session_dict["total_chats"],
                    schedule_extracted=None,
                    memory_compressed=False,
                    daily_share=daily_share
                )

    await memory_service.save_message(session_id, "user", request.content)

    context = await build_context(session_id, pet_type)
    
    # 获取用户画像中的地区（作为备用提示给 Agent）
    user_profile = await memory_service.get_user_profile(session_dict.get("user_id", ""))
    saved_region = user_profile.get("region") if user_profile else None

    # 构建位置提示 - 让 LLM Agent 自己从对话中识别城市
    if saved_region:
        location_hint = f"（根据历史记录，用户可能在 {saved_region}）"
    else:
        location_hint = "（暂无用户位置信息）"

    skills_section = f"""{context['skills']}

【可用工具】
- query_weather: 查询天气
  用法: 当用户询问天气且你知道用户所在城市时调用
  参数: location (城市名，支持全球城市，如"北京"、"东京"、"纽约"等)

【重要】
Agent 需要自主从用户消息中识别位置信息：
- 如果用户提到城市名（如"我在苏州"、"去北京"），请记住这个位置
- 如果用户询问天气但你不知道在哪，请先询问用户
{location_hint}
"""

    full_prompt = f"""<system>
{context['system_prompt']}
:</system>

<long_term_memory>
{context['long_term_memory']}
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

<conversation>
{context['conversation']}

主人: {request.content}
</conversation>

【重要规则】
1. 如果用户询问天气，你需要知道用户在哪：
   - 如果 <skills> 中显示"用户地区: 未知"，请先询问用户所在城市
   - 如果用户指定了地点，使用用户指定的地点
   - 如果有已知地区，使用已知地区
2. 只有在知道用户所在城市后才能调用 query_weather 工具
3. 如果需要调用工具，请在回复中包含：
   [TOOL_CALL]
   {{"tool": "query_weather", "args": {{"location": "城市名"}}}}
   [/TOOL_CALL]
4. 如果用户的消息包含日程安排，在回复末尾添加：[SCHEDULE: 日程内容 | YYYY-MM-DD HH:MM]
5. 如果没有日程或不需要工具，不要添加任何标记
6. 调用工具后，系统会返回工具执行结果，请根据结果回复用户

请用{pet_type}的性格风格回复，直接输出回复内容。"""

    reply = await llm_service.chat([{"role": "user", "content": full_prompt}], caller="main_chat")
    if not reply:
        fallback_replies = {
            "hot_dog": "汪？主人，我突然不知道说什么了...",
            "cold_cat": "......不想说话。",
            "mouse": "鼠鼠我啊......突然不知道怎么回答了......"
        }
        reply = fallback_replies.get(pet_type, "突然不知道说什么了...")
    
    # 执行工具调用并生成最终回复（ReAct 模式）
    reply, tool_results = await execute_tools_and_build_final_prompt(
        reply, full_prompt, pet_type
    )

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
        print(f"[DEBUG] Schedule saved: {schedule_extracted}")

    # 后台更新用户画像（使用用户画像总结 Agent）
    user_profile_updated = False
    try:
        conversation_for_profile = context['conversation']
        existing_profile = await memory_service.get_user_profile(session_dict.get("user_id", ""))
        extracted_profile = await user_profile_agent.analyze_and_extract(
            conversation_for_profile, 
            existing_profile
        )
        if extracted_profile:
            await memory_service.merge_user_profile(session_dict["user_id"], extracted_profile)
            user_profile_updated = True
            print(f"[DEBUG] User profile updated by agent: {extracted_profile}")
    except Exception as e:
        print(f"[DEBUG] User profile agent error: {e}")

    emotion_tag = await llm_service.extract_emotion(request.content, pet_type)

    await memory_service.save_message(session_id, "assistant", reply, emotion_tag=emotion_tag)

    intimacy_change = calculate_intimacy_change(emotion_tag)
    new_intimacy = min(100, session_dict["intimacy"] + intimacy_change)
    new_total_chats = session_dict["total_chats"] + 1

    message_count = await memory_service.get_message_count(session_id)
    memory_compressed = False
    if message_count > 20 and message_count % 20 == 0:
        short_term_messages = await memory_service.get_short_term_messages(session_id, limit=40)
        pet_prompts = {"hot_dog": prompts.hot_dog, "cold_cat": prompts.cold_cat, "mouse": prompts.mouse}
        pet_info = pet_prompts.get(pet_type)
        await memory_service.compress_to_long_term(session_id, short_term_messages, pet_info.PET_NAME)
        memory_compressed = True

    async with get_db() as db:
        await db.execute(
            "UPDATE pet_sessions SET intimacy = ?, total_chats = ?, last_interaction_at = ?, updated_at = ? WHERE session_id = ?",
            (new_intimacy, new_total_chats, datetime.now(), datetime.now(), session_id)
        )
        await db.commit()
    
    # 随机分享日常（约33%概率）
    daily_share = None
    pet_prompts = {"hot_dog": prompts.hot_dog, "cold_cat": prompts.cold_cat, "mouse": prompts.mouse}
    pet_info = pet_prompts.get(pet_type)
    
    import random
    if random.randint(1, 100) % 3 == 0 and session_dict.get("pet_status") != "hiding":
        daily_content = await generate_share_daily_message(pet_type, pet_info.PET_NAME)
        await memory_service.save_message(session_id, "assistant", daily_content, is_proactive=True)
        daily_share = {"role": "assistant", "content": daily_content}
        print(f"[DEBUG] Daily share triggered: {daily_content}")

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
async def get_messages(session_id: str):
    messages = await memory_service.get_short_term_messages(session_id, limit=100)
    return MessageListResponse(messages=messages, total=len(messages))
