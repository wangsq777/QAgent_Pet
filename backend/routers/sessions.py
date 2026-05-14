import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException
from backend.database import get_db
from backend.schemas import SessionCreateRequest, SessionResponse, SimulateTimeRequest, SimulateTimeResponse, ErrorResponse, MemoryPanelResponse, UserProfileUpdateRequest
from backend.services.llm_service import llm_service
from backend.services.memory_service import memory_service
from backend import prompts

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def get_intimacy_level(intimacy: int) -> str:
    if intimacy <= 20:
        return "陌生"
    elif intimacy <= 50:
        return "熟悉"
    elif intimacy <= 80:
        return "亲密"
    else:
        return "挚友"


@router.post("", response_model=SessionResponse)
async def create_session(request: SessionCreateRequest):
    user_id = request.user_id
    pet_type = request.pet_type

    # 支持自定义宠物类型
    valid_pet_types = ["hot_dog", "cold_cat", "mouse", "custom"]
    if pet_type not in valid_pet_types:
        raise HTTPException(status_code=400, detail="Invalid pet type")

    async with get_db() as db:
        # 查找该用户是否已有该宠物的 session
        cursor = await db.execute(
            "SELECT session_id FROM pet_sessions WHERE user_id = ? AND pet_type = ?",
            (user_id, pet_type)
        )
        existing = await cursor.fetchone()

        if existing:
            # 复用已有 session，直接返回欢迎消息（不重新生成）
            session_id = existing[0]
            cursor = await db.execute(
                "SELECT intimacy FROM pet_sessions WHERE session_id = ?",
                (session_id,)
            )
            session = await cursor.fetchone()
            intimacy = session[0] if session else 0

            return SessionResponse(
                session_id=session_id,
                pet_type=pet_type,
                welcome_message=None,  # 已有session不返回欢迎语
                intimacy=intimacy,
                is_existing=True  # 标记为已有session
            )

        # 创建新 session
        session_id = str(uuid.uuid4())

    async with get_db() as db:
        user_row = await db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        user_exists = await user_row.fetchone()

        if not user_exists:
            nickname = request.nickname or "主人"
            await db.execute(
                "INSERT INTO users (user_id, nickname, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (user_id, nickname, datetime.now(), datetime.now())
            )
            profile_id = str(uuid.uuid4())
            await db.execute(
                "INSERT INTO user_profiles (profile_id, user_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (profile_id, user_id, datetime.now(), datetime.now())
            )

        await db.execute(
            """
            INSERT INTO pet_sessions (session_id, user_id, pet_type, intimacy, total_chats, last_interaction_at, pet_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, user_id, pet_type, 0, 0, datetime.now(), "normal", datetime.now(), datetime.now())
        )
        await db.commit()

    pet_prompts = {
        "hot_dog": prompts.hot_dog,
        "cold_cat": prompts.cold_cat,
        "mouse": prompts.mouse
    }

    # 自定义宠物使用不同的欢迎语逻辑
    if pet_type == "custom":
        # 自定义宠物的欢迎语由前端配置，这里使用默认欢迎语
        from backend.prompts.custom_pet import generate_welcome_messages
        pet_name = request.nickname or "小可爱"
        welcome_messages = generate_welcome_messages(
            pet_name=pet_name,
            pet_type="dog",
            personality_tags=["活泼"],
            catchphrase=None
        )
        welcome_content = welcome_messages[0] if welcome_messages else f"你好！我是你的专属宠物{pet_name}！"
    else:
        pet_info = pet_prompts.get(pet_type)
        welcome_content = await llm_service.generate_welcome_message(
            pet_type,
            pet_info.PET_NAME,
            pet_info.PET_PERSONALITY
        )

    await memory_service.save_message(session_id, "assistant", welcome_content, is_proactive=True)

    return SessionResponse(
        session_id=session_id,
        pet_type=pet_type,
        welcome_message={
            "role": "assistant",
            "content": welcome_content,
            "created_at": datetime.now().isoformat()
        },
        intimacy=0
    )


@router.get("/{session_id}")
async def get_session(session_id: str):
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM pet_sessions WHERE session_id = ?",
            (session_id,)
        )
        session = await cursor.fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        return dict(session)


async def generate_share_daily_message(pet_type: str, pet_name: str) -> str:
    """生成宠物分享日常的消息"""
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
    
    import random
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


@router.post("/{session_id}/share-daily")
async def share_daily(session_id: str):
    """
    分享日常 API
    - 前端调用：用户打开页面时概率触发（随机数整除3）
    - 内部调用：模拟隔天后必定触发
    """
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
        pet_status = session_dict["pet_status"]

        # 如果宠物在躲藏状态，不分享日常
        if pet_status == "hiding":
            return {"message": None, "reason": "pet_hiding"}

        pet_prompts = {
            "hot_dog": prompts.hot_dog,
            "cold_cat": prompts.cold_cat,
            "mouse": prompts.mouse
        }
        pet_info = pet_prompts.get(pet_type)

        # 生成日常分享消息
        daily_content = await generate_share_daily_message(pet_type, pet_info.PET_NAME)
        
        # 保存消息
        await memory_service.save_message(session_id, "assistant", daily_content, is_proactive=True)
        
        return {"message": {"role": "assistant", "content": daily_content}}


@router.post("/{session_id}/share-daily-random")
async def share_daily_random(session_id: str):
    """
    概率触发分享日常
    生成随机数，如果能整除3（约33%概率），则分享日常
    """
    import random
    rand_num = random.randint(1, 100)
    
    if rand_num % 3 == 0:
        # 触发分享日常
        result = await share_daily(session_id)
        return {"triggered": True, **result}
    else:
        return {"triggered": False, "message": None}


@router.post("/{session_id}/simulate-time", response_model=SimulateTimeResponse)
async def simulate_time(session_id: str, request: SimulateTimeRequest):
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
        pet_status = session_dict["pet_status"]
        last_interaction = session_dict.get("last_interaction_at")

        pet_prompts = {
            "hot_dog": prompts.hot_dog,
            "cold_cat": prompts.cold_cat,
            "mouse": prompts.mouse
        }
        pet_info = pet_prompts.get(pet_type)

        proactive_message = None
        new_status = pet_status

        # 默认回复
        default_messages = {
            "hot_dog": "汪！主人，我好想你呀！",
            "cold_cat": "......哼。",
            "mouse": "鼠鼠我啊......鼓起勇气来见主人了......"
        }

        if request.mode == "next_day":
            # 首先检查是否有待触发的日程
            cursor = await db.execute(
                "SELECT * FROM schedules WHERE session_id = ? AND is_triggered = 0",
                (session_id,)
            )
            schedules = await cursor.fetchall()
            
            if schedules and len(schedules) > 0:
                # 有日程，逐一提醒
                all_schedule_contents = "、".join([dict(s)['content'] for s in schedules])
                schedule_content = f"提醒主人：{all_schedule_contents}"
                proactive_content = await llm_service.generate_proactive_message(
                    pet_type, pet_info.PET_NAME, schedule_content
                ) or f"{pet_info.PET_NAME}提醒你：{all_schedule_contents}"
                proactive_message = {"role": "assistant", "content": proactive_content}
                await memory_service.save_message(session_id, "assistant", proactive_content, is_proactive=True)
                
                # 标记所有日程为已触发
                for s in schedules:
                    await db.execute(
                        "UPDATE schedules SET is_triggered = 1 WHERE schedule_id = ?",
                        (dict(s)["schedule_id"],)
                    )
            elif pet_type == "hot_dog":
                proactive_content = await llm_service.generate_proactive_message(
                    pet_type, pet_info.PET_NAME, "主人已经1天没互动了，我很想念主人！"
                ) or default_messages["hot_dog"]
                proactive_message = {"role": "assistant", "content": proactive_content}
                await memory_service.save_message(session_id, "assistant", proactive_content, is_proactive=True)

            elif pet_type == "cold_cat":
                import random
                if random.random() < 0.5:
                    proactive_message = None
                else:
                    proactive_content = await llm_service.generate_proactive_message(
                        pet_type, pet_info.PET_NAME, "主人已经3天没互动了，我假装不在意但其实有点想主人。"
                    ) or default_messages["cold_cat"]
                    proactive_message = {"role": "assistant", "content": proactive_content}
                    await memory_service.save_message(session_id, "assistant", proactive_content, is_proactive=True)

            elif pet_type == "mouse":
                proactive_content = await llm_service.generate_proactive_message(
                    pet_type, pet_info.PET_NAME, "主人已经2天没互动了，鼠鼠鼓起勇气打招呼。"
                ) or default_messages["mouse"]
                proactive_message = {"role": "assistant", "content": proactive_content}
                await memory_service.save_message(session_id, "assistant", proactive_content, is_proactive=True)
            
            # 模拟隔天后必定分享日常（即使宠物没有主动发消息）
            if pet_status != "hiding" and proactive_message is None:
                daily_content = await generate_share_daily_message(pet_type, pet_info.PET_NAME)
                proactive_message = {"role": "assistant", "content": daily_content}
                await memory_service.save_message(session_id, "assistant", daily_content, is_proactive=True)

        elif request.mode == "schedule_trigger":
            cursor = await db.execute(
                "SELECT * FROM schedules WHERE session_id = ? AND is_triggered = 0 ORDER BY scheduled_time LIMIT 1",
                (session_id,)
            )
            schedule = await cursor.fetchone()

            if schedule:
                schedule_dict = dict(schedule)
                schedule_content = f"提醒：{schedule_dict['content']}（时间: {schedule_dict['scheduled_time']}）"
                proactive_content = await llm_service.generate_proactive_message(
                    pet_type, pet_info.PET_NAME, schedule_content
                ) or f"{pet_info.PET_NAME}提醒你：{schedule_dict['content']}"
                proactive_message = {"role": "assistant", "content": proactive_content}
                await memory_service.save_message(session_id, "assistant", proactive_content, is_proactive=True)

                await db.execute(
                    "UPDATE schedules SET is_triggered = 1 WHERE schedule_id = ?",
                    (schedule_dict["schedule_id"],)
                )

        await db.execute(
            "UPDATE pet_sessions SET last_interaction_at = ?, pet_status = ?, updated_at = ? WHERE session_id = ?",
            (datetime.now(), new_status, datetime.now(), session_id)
        )
        await db.commit()

        return SimulateTimeResponse(
            proactive_message=proactive_message,
            pet_status=new_status,
            schedule_reminder=None
        )


@router.get("/{session_id}/memory", response_model=MemoryPanelResponse)
async def get_memory_panel(session_id: str):
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM pet_sessions WHERE session_id = ?",
            (session_id,)
        )
        session = await cursor.fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        session_dict = dict(session)
        intimacy = session_dict["intimacy"]
        total_chats = session_dict["total_chats"]

        intimacy_level = get_intimacy_level(intimacy)

        long_term_memories = await memory_service.get_long_term_memories(session_id)
        recent_messages_count = await memory_service.get_message_count(session_id)

        user_profile = await memory_service.get_user_profile(session_dict["user_id"]) or {}

        return MemoryPanelResponse(
            intimacy=intimacy,
            intimacy_level=intimacy_level,
            total_chats=total_chats,
            long_term_memories=long_term_memories,
            recent_messages_count=recent_messages_count,
            user_profile={
                "region": user_profile.get("region"),
                "identity": user_profile.get("identity"),
                "interests": user_profile.get("interests", "").split(",") if user_profile.get("interests") else [],
                "extra_info": user_profile.get("extra_info")
            }
        )


@router.put("/{session_id}/profile", response_model=UserProfileUpdateRequest)
async def update_user_profile(session_id: str, request: UserProfileUpdateRequest):
    """
    更新用户画像（用户手动编辑）
    """
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT user_id FROM pet_sessions WHERE session_id = ?",
            (session_id,)
        )
        session = await cursor.fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        user_id = dict(zip([d[0] for d in cursor.description], session))["user_id"]

        profile_data = {
            "region": request.region if request.region else "未知",
            "identity": request.identity if request.identity else "未知",
            "interests": request.interests if request.interests else "未知",
            "extra_info": request.extra_info
        }

        await memory_service.save_user_profile(user_id, profile_data)

        return UserProfileUpdateRequest(**profile_data)