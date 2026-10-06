"""Pet-specific daily sharing used by chat and proactive reminder routes."""

from backend.services.llm_service import llm_service


async def get_reminder_identity(db, session: dict) -> tuple[str, str]:
    """Resolve reminder identity from this session and its owner's custom pet."""
    from backend import prompts

    preset = {"hot_dog": prompts.hot_dog, "cold_cat": prompts.cold_cat, "mouse": prompts.mouse}.get(session["pet_type"])
    if preset:
        return preset.PET_NAME, preset.PET_PERSONALITY
    cursor = await db.execute(
        "SELECT pet_name, pet_type, system_prompt, catchphrase FROM custom_pets WHERE pet_id=? AND user_id=?",
        (session.get("custom_pet_id"), session["user_id"]),
    )
    row = await cursor.fetchone()
    if not row:
        return "小可爱", "你是用户的自定义宠物，使用中性的自称和语气。"
    pet = dict(row)
    context = f"名字：{pet['pet_name']}；物种：{pet['pet_type']}。\n{pet.get('system_prompt') or ''}"
    if pet.get("catchphrase"):
        context += f"\n口头禅：{pet['catchphrase']}"
    return pet["pet_name"], context


async def generate_share_daily_message(pet_type: str, pet_name: str, pet_context: str = "") -> str:
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

    topic = random.choice(daily_topics.get(pet_type, [
        "今天找了个舒服的地方休息，想和你分享这份轻松。",
        "刚刚看了会儿窗外的风景，想来陪你聊聊天。",
        "今天过得很悠闲，想听听你有什么新鲜事。",
    ]))

    # 用 LLM 生成更自然的表达
    llm_content = await llm_service.generate_proactive_message(
        pet_type, pet_name, f"分享日常生活：{topic}", pet_context=pet_context
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
