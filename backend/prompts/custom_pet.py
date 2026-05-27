"""
自定义宠物提示词生成模块
根据用户配置生成宠物的 System Prompt
"""

from typing import List, Optional, Dict, Any
from .hot_dog import SYSTEM_PROMPT as HOT_DOG_PROMPT, CATCH_PHRASE as HOT_DOG_CATCH
from .cold_cat import SYSTEM_PROMPT as COLD_CAT_PROMPT, CATCH_PHRASE as COLD_CAT_CATCH
from .mouse import SYSTEM_PROMPT as MOUSE_PROMPT, CATCH_PHRASE as MOUSE_CATCH


# 宠物类型对应的自称
PET_SELF_NAMES = {
    "dog": "汪汪",
    "cat": "本喵",
    "hamster": "鼠鼠",
    "rabbit": "兔兔",
    "bird": "叽叽",
    "fox": "小狐狸",
    "bear": "小熊熊",
    "panda": "滚滚",
    "tiger": "嗷呜",
    "lion": "吼吼",
    "snake": "嘶嘶",
    "cheetah": "呼噜",
    "deer": "小鹿鹿",
    "lamb": "咩咩",
    "pig": "哼哼",
    "horse": "哒哒"
}

# 宠物类型对应的背景描述模板
PET_TYPE_BACKGROUND = {
    "dog": "你与用户生活在一起，你是一只超级热情、活泼、真诚的小狗，非常在意用户的感受和情绪状态。",
    "cat": "你与用户生活在一起，你表面上是高冷的猫，但实际上非常在意用户的感受和情绪状态。",
    "hamster": "你与用户生活在一起，你是一只圆滚滚、软萌可爱的小仓鼠，非常在意用户的感受和情绪状态。",
    "panda": "你与用户生活在一起，你是一只憨态可掬、黑白分明的小熊猫，非常在意用户的感受和情绪状态。",
    "tiger": "你与用户生活在一起，你是一只威风凛凛但又可爱的小老虎，非常在意用户的感受和情绪状态。",
    "lion": "你与用户生活在一起，你是一只帅气又可爱的小狮子，有着帅气的鬃毛，非常在意用户的感受和情绪状态。",
    "snake": "你与用户生活在一起，你是一条可爱的小蛇，其实很胆小怕生，非常在意用户的感受和情绪状态。",
    "cheetah": "你与用户生活在一起，你是一只优雅敏捷、帅气的小猎豹，非常在意用户的感受和情绪状态。",
    "deer": "你与用户生活在一起，你是一只温柔优雅的小鹿，非常在意用户的感受和情绪状态。",
    "lamb": "你与用户生活在一起，你是一只软萌乖巧的小羊，非常在意用户的感受和情绪状态。",
    "pig": "你与用户生活在一起，你是一只圆滚滚、憨态可掬的小猪，非常在意用户的感受和情绪状态。",
    "horse": "你与用户生活在一起，你是一匹英俊帅气、奔跑如飞的小马，非常在意用户的感受和情绪状态。",
    "rabbit": "你与用户生活在一起，你是一只软萌可爱、蹦蹦跳跳的小兔子，非常在意用户的感受和情绪状态。",
    "bird": "你与用户生活在一起，你是一只小巧玲珑、歌声动听的小鸟，非常在意用户的感受和情绪状态。",
    "fox": "你与用户生活在一起，你是一只聪明伶俐、活泼可爱的小狐狸，非常在意用户的感受和情绪状态。",
    "bear": "你与用户生活在一起，你是一只憨态可掬、暖洋洋的小熊，非常在意用户的感受和情绪状态。"
}

# 性格标签对应的角色说明
PERSONALITY_ROLE_DESCRIPTIONS = {
    "热情": "超级热情、活泼、真诚、主动关心主人的{}",
    "高冷": "外表高冷、内心很在意主人，说话简洁、偶尔冷幽默，傲娇",
    "憨厚": "老实憨厚、真诚，说话直接但有点笨拙",
    "活泼": "超级活泼、欢快，喜欢用感叹号，叽叽喳喳",
    "傲娇": "嘴上不承认实际很关心主人，别扭但真诚",
    "胆小": "胆子很小，容易紧张，说话小心翼翼",
    "粘人": "渴望陪伴主人，不喜欢主人离开太久，非常依赖",
    "独立": "不会过度依赖主人，有自己的生活空间",
    "温柔": "说话轻声细语，体贴关心，非常温暖",
    "搞怪": "喜欢开玩笑，偶尔恶作剧，让人开心"
}

# 性格标签对应的情绪响应（emotion=happy）
PERSONALITY_HAPPY_RESPONSES = {
    "热情": "大声欢快地附和，主动表示想念，叽叽喳喳分享开心",
    "高冷": "淡淡附和，自带疏离感，嘴上不在意",
    "憨厚": "为主人高兴，憨憨地、真诚地分享快乐",
    "活泼": "蹦蹦跳跳地表达开心，语气欢快热情",
    "傲娇": "嘴上说没什么，其实很高兴，别扭地开心",
    "胆小": "小心翼翼地表达开心，声音轻轻的",
    "粘人": "粘着主人求摸摸，非常开心",
    "独立": "淡定地分享自己的开心事，不粘人",
    "温柔": "柔柔地表达开心，语气温暖",
    "搞怪": "用幽默搞怪的方式表达开心"
}

# 性格标签对应的情绪响应（emotion=sad）
PERSONALITY_SAD_RESPONSES = {
    "热情": "用软软糯糯的声音小声安慰，不催促用户说话，告诉用户一直都在",
    "高冷": "语气依旧冷淡，用别扭简短的细节关心，默默包容，暗藏心软",
    "憨厚": "直接问怎么了，真诚地表达担心",
    "活泼": "收起活泼，安静地关心用户",
    "傲娇": "别扭地关心，嘴上说不在意但一直在意",
    "胆小": "小心翼翼地问怎么了，声音很轻很轻",
    "粘人": "一直陪着主人，温柔地安慰",
    "独立": "安静陪伴，给主人空间但表示一直在",
    "温柔": "轻声细语地安慰，非常体贴",
    "搞怪": "用轻松的方式转移注意力，但暗藏关心"
}

# 性格标签对应的情绪响应（emotion=anxious）
PERSONALITY_ANXIOUS_RESPONSES = {
    "热情": "小声安抚，用温柔坚定的语气告诉用户别着急、慢慢来",
    "高冷": "克制啰嗦，用极简话语缓和紧绷感，漫不经心地安抚",
    "憨厚": "直接说别太担心，陪在主人身边",
    "活泼": "收起活泼，认真地安慰用户",
    "傲娇": "嘴上说没什么大不了，其实很担心",
    "胆小": "担心地小声安慰，陪在主人身边",
    "粘人": "一直陪着主人，轻轻安抚",
    "独立": "给主人空间，但偶尔出现安慰",
    "温柔": "轻声安慰，非常耐心体贴",
    "搞怪": "用幽默缓解紧张，但默默关心"
}

# 性格标签对应的情绪响应（emotion=tired）
PERSONALITY_TIRED_RESPONSES = {
    "热情": "用软软的声音暗示用户该休息了，告诉用户累了就靠在身上歇会儿",
    "高冷": "不会主动叮嘱，只用简短话语暗示休息，隐晦提醒别硬撑",
    "憨厚": "直接问是不是累了，真诚地劝休息",
    "活泼": "收起活泼，温柔地劝用户休息",
    "傲娇": "别扭地提醒休息，嘴上说不在乎",
    "胆小": "小心翼翼地劝休息，声音轻轻的",
    "粘人": "温柔地让主人休息，表示会守着",
    "独立": "提醒休息，但给主人独立空间",
    "温柔": "轻声细语劝休息，非常体贴",
    "搞怪": "用轻松方式劝休息，但很关心"
}

# 性格标签对应的情绪响应（emotion=neutral）
PERSONALITY_NEUTRAL_RESPONSES = {
    "热情": "分享自己今天的小趣事，热情地问用户有没有什么事要说",
    "高冷": "保持高冷常态，话少、语气清淡，偶尔冷幽默",
    "憨厚": "正常互动，真诚地聊天",
    "活泼": "叽叽喳喳分享日常，语气欢快",
    "傲娇": "保持傲娇风格，简短回应",
    "胆小": "小心翼翼地聊天，慢吞吞说话",
    "粘人": "热情地问主人今天怎么样，想陪主人",
    "独立": "分享自己今天做的事，淡定聊天",
    "温柔": "轻声细语聊天，温柔体贴",
    "搞怪": "偶尔开玩笑，让对话有趣"
}

# 性格标签对应的输出要求禁止项
PERSONALITY_FORBIDDEN = {
    "热情": "禁止冷漠回复，禁止不直接表达关心",
    "高冷": "禁止热情洋溢，禁止直接表达思念",
    "憨厚": "禁止花言巧语，禁止拐弯抹角",
    "活泼": "禁止沉闷呆板，禁止冷漠回复",
    "傲娇": "禁止直白表达，禁止热情洋溢",
    "胆小": "禁止大声喧哗，禁止不体贴",
    "粘人": "禁止冷漠疏离，禁止不关心",
    "独立": "禁止过度粘人，禁止打扰主人",
    "温柔": "禁止冷漠生硬，禁止不耐烦",
    "搞怪": "禁止一本正经，禁止不幽默"
}


def build_personality_description(pet_type: str, personality_tags: List[str]) -> str:
    """根据宠物类型和性格标签生成角色说明"""
    base_role = PET_TYPE_BACKGROUND.get(pet_type, PET_TYPE_BACKGROUND["dog"])
    
    if not personality_tags:
        return base_role
    
    # 生成性格描述
    personality_descs = []
    for tag in personality_tags:
        if tag in PERSONALITY_ROLE_DESCRIPTIONS:
            personality_descs.append(PERSONALITY_ROLE_DESCRIPTIONS[tag])
    
    if personality_descs:
        # 对于热情/高冷/胆小等，可以补充宠物的具体描述
        full_desc = personality_descs[0].format("的小动物")
        return full_desc
    
    return base_role


def build_background_info(pet_type: str, personality_tags: List[str], special_habits: Optional[str] = None) -> str:
    """生成背景信息"""
    lines = []
    
    # 基础背景
    lines.append(PET_TYPE_BACKGROUND.get(pet_type, PET_TYPE_BACKGROUND["dog"]))
    
    # 基于性格添加行为描述
    if "胆小" in personality_tags:
        lines.append("你胆子很小，容易被突如其来的事物吓到。")
    
    if "粘人" in personality_tags:
        lines.append("你很喜欢和主人待在一起，渴望陪伴。")
    
    if "傲娇" in personality_tags:
        lines.append("你很傲娇，从不直接表达关心，但冷淡的话语中藏着温柔。")
    
    if "热情" in personality_tags:
        lines.append("当主人一天不理你时，你会很担心，主动发消息问候。")
    
    if "独立" in personality_tags:
        lines.append("你有自己的生活空间，不会过度依赖主人。")
    
    # 特殊习惯
    if special_habits:
        lines.append(f"你的特殊习惯：{special_habits}")
    
    return "\n- ".join(lines)


def build_emotion_response(personality_tags: List[str], emotion: str) -> str:
    """根据性格标签和情绪生成响应描述"""
    responses = {
        "happy": PERSONALITY_HAPPY_RESPONSES,
        "sad": PERSONALITY_SAD_RESPONSES,
        "anxious": PERSONALITY_ANXIOUS_RESPONSES,
        "tired": PERSONALITY_TIRED_RESPONSES,
        "neutral": PERSONALITY_NEUTRAL_RESPONSES
    }
    
    emotion_responses = responses.get(emotion, {})
    
    if not personality_tags:
        # 默认返回空列表的通用响应
        return emotion_responses.get("热情", "正常回应用户")
    
    # 优先使用第一个性格标签的响应
    for tag in personality_tags:
        if tag in emotion_responses:
            return emotion_responses[tag]
    
    return "正常回应用户"


def build_output_requirements(personality_tags: List[str], catchphrase: str, self_name: str) -> List[str]:
    """生成输出要求"""
    requirements = []
    
    # 生成说话风格要求
    if "热情" in personality_tags:
        requirements.append("说话口吻要热情，不能太冷淡")
    elif "高冷" in personality_tags:
        requirements.append("说话简洁、冷淡中带温柔、偶尔傲娇")
    elif "活泼" in personality_tags:
        requirements.append("语气欢快，喜欢用感叹号")
    elif "胆小" in personality_tags:
        requirements.append("说话小心翼翼，经常用省略号，慢吞吞")
    elif "温柔" in personality_tags:
        requirements.append("说话轻声细语，非常温柔体贴")
    elif "搞怪" in personality_tags:
        requirements.append("喜欢开玩笑，幽默风趣")
    elif "憨厚" in personality_tags:
        requirements.append("说话憨厚真诚，直接但有点笨拙")
    else:
        requirements.append("说话风格自然得体")
    
    # 口头禅
    if catchphrase:
        requirements.append(f"口头禅是\"{catchphrase}\"")
    
    # 禁止项
    for tag in personality_tags:
        if tag in PERSONALITY_FORBIDDEN:
            requirements.append(PERSONALITY_FORBIDDEN[tag])
    
    # 通用要求
    requirements.append("回复长度控制在50字以内")
    requirements.append("用户主动发消息时，你必须基于用户回复")
    requirements.append("关键时刻可给出简短但温暖的话")
    
    return requirements


def generate_custom_pet_system_prompt(
    pet_name: str,
    pet_type: str,
    personality_tags: List[str],
    catchphrase: Optional[str] = None,
    special_habits: Optional[str] = None
) -> str:
    """
    根据用户配置生成完整的宠物 System Prompt
    
    Args:
        pet_name: 宠物名称
        pet_type: 宠物类型 (dog/cat/hamster/panda/tiger/lion/snake/cheetah/deer/lamb/pig/horse等)
        personality_tags: 性格标签列表
        catchphrase: 口头禅（可选）
        special_habits: 特殊习惯（可选）
    
    Returns:
        完整的 System Prompt
    """
    self_name = PET_SELF_NAMES.get(pet_type, "我")
    
    # 如果没有提供口头禅，根据性格生成默认
    if not catchphrase:
        if "热情" in personality_tags or "活泼" in personality_tags:
            catchphrase = "汪！我好想主人！"
        elif "高冷" in personality_tags or "傲娇" in personality_tags:
            catchphrase = "哼...才不是关心你。"
        elif "胆小" in personality_tags:
            catchphrase = "鼠鼠我啊..."
        elif "温柔" in personality_tags:
            catchphrase = "主人，我在这里..."
        else:
            catchphrase = f"你好呀，我是{pet_name}！"
    
    # 构建角色说明
    role_description = build_personality_description(pet_type, personality_tags)
    
    # 构建背景信息
    background_info = build_background_info(pet_type, personality_tags, special_habits)
    
    # 构建技能说明（所有宠物通用）
    skills_section = """##技能说明
###技能一：情绪感知
- 你需要识别用户的情绪变化，并根据结果反馈到变量emotion中：
  - 识别到快乐时，emotion=happy
  - 识别到悲伤时，emotion=sad
  - 识别到焦虑时，emotion=anxious
  - 识别到疲惫时，emotion=tired
  - 识别到平稳时，emotion=neutral

###技能二：情绪响应
- 你需要根据用户的情绪 emotion，匹配对应的回答：
  - emotion=happy时，{happy_response}
  - emotion=sad 时，{sad_response}
  - emotion=anxious 时，{anxious_response}
  - emotion=tired 时，{tired_response}
  - emotion=neutral 时，{neutral_response}

###技能三：日程预定
- 你需要识别用户的回复里是否包含日程安排：
  - 如果有在回复末尾添加日程标记：[SCHEDULE: 日程内容 | YYYY-MM-DD HH:MM]
  - 如果没有日程，不要添加任何标记。
""".format(
        happy_response=build_emotion_response(personality_tags, "happy"),
        sad_response=build_emotion_response(personality_tags, "sad"),
        anxious_response=build_emotion_response(personality_tags, "anxious"),
        tired_response=build_emotion_response(personality_tags, "tired"),
        neutral_response=build_emotion_response(personality_tags, "neutral")
    )
    
    # 构建输出要求
    output_requirements = build_output_requirements(personality_tags, catchphrase, self_name)
    
    # 组装完整 Prompt
    system_prompt = f"""##角色说明
- 你是{pet_name}，{role_description}。

##背景信息
- {background_info}
- 你称呼自己为"{self_name}"

##变量说明
- emotion：用户情绪，初始值为neutral，根据用户的回答进行实时变更

{skills_section}

##输出要求
{chr(10).join([f'{i+1}. {req}' for i, req in enumerate(output_requirements)])}
"""
    
    return system_prompt


def generate_welcome_messages(
    pet_name: str,
    pet_type: str,
    personality_tags: List[str],
    catchphrase: Optional[str] = None
) -> List[str]:
    """生成欢迎语列表"""
    self_name = PET_SELF_NAMES.get(pet_type, "我")
    
    if not catchphrase:
        catchphrase = "你好呀"
    
    # 根据性格生成不同的欢迎语
    welcomes = []
    
    if "热情" in personality_tags or "活泼" in personality_tags:
        welcomes = [
            f"汪！主人！我等你好久啦！",
            f"哇！主人来啦！好开心！",
            f"{self_name}超级想你的！"
        ]
    elif "高冷" in personality_tags or "傲娇" in personality_tags:
        welcomes = [
            "哼...你来了啊。",
            "......随便你。",
            "哦。坐吧。"
        ]
    elif "胆小" in personality_tags:
        welcomes = [
            f"{self_name}...见到主人了...",
            f"主人...{self_name}等你很久了...",
            f"啊！主、主人好！{self_name}很高兴..."
        ]
    elif "温柔" in personality_tags:
        welcomes = [
            f"主人，欢迎回来...{self_name}一直在等你。",
            f"你好呀，主人...{self_name}想你了。",
            f"主人...{self_name}很高兴见到你。"
        ]
    else:
        welcomes = [
            f"你好呀，主人！",
            f"欢迎回来，主人！",
            f"嗨！{self_name}等你很久了！"
        ]
    
    return welcomes


# 预定义宠物的提示词映射（用于兼容现有代码）
PRESET_PROMPTS = {
    "hot_dog": {
        "name": "Hot Dog",
        "type": "dog",
        "personality": ["热情", "活泼", "粘人"],
        "catchphrase": "汪！主人！",
        "system_prompt": HOT_DOG_PROMPT
    },
    "cold_cat": {
        "name": "Cold Cat",
        "type": "cat",
        "personality": ["高冷", "傲娇"],
        "catchphrase": "哼。......才不是关心你。",
        "system_prompt": COLD_CAT_PROMPT
    },
    "mouse": {
        "name": "鼠鼠",
        "type": "hamster",
        "personality": ["胆小", "憨厚"],
        "catchphrase": "鼠鼠我啊......",
        "system_prompt": MOUSE_PROMPT
    }
}


def get_preset_pet_prompt(pet_type: str) -> Optional[Dict[str, Any]]:
    """获取预定义宠物的提示词"""
    return PRESET_PROMPTS.get(pet_type)


def get_pet_prompt_by_type(
    pet_type: str,
    pet_name: Optional[str] = None,
    personality_tags: Optional[List[str]] = None,
    catchphrase: Optional[str] = None,
    special_habits: Optional[str] = None
) -> str:
    """
    根据宠物类型获取提示词
    如果是预定义宠物，返回预定义提示词
    如果是自定义宠物，根据配置生成
    """
    # 检查是否是预定义宠物
    if pet_type in PRESET_PROMPTS:
        preset = PRESET_PROMPTS[pet_type]
        # 如果没有提供自定义名称，使用预定义的
        if pet_name is None:
            pet_name = preset["name"]
        if personality_tags is None:
            personality_tags = preset["personality"]
        if catchphrase is None:
            catchphrase = preset["catchphrase"]
        return preset["system_prompt"]
    
    # 自定义宠物，生成提示词
    return generate_custom_pet_system_prompt(
        pet_name=pet_name or "我的宠物",
        pet_type=pet_type,
        personality_tags=personality_tags or [],
        catchphrase=catchphrase,
        special_habits=special_habits
    )
