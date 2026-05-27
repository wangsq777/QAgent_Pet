"""
自定义宠物管理路由
支持自定义宠物的创建、预览和管理
"""

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse

from backend.schemas import (
    CustomPetConfigRequest,
    CustomPetPreviewRequest,
    CustomPetPreviewResponse,
    CustomPetCreateRequest,
    CustomPetResponse,
    PetTemplateResponse,
    PetTemplateListResponse
)
from backend.prompts.custom_pet import (
    generate_custom_pet_system_prompt,
    generate_welcome_messages,
    get_preset_pet_prompt,
    PRESET_PROMPTS
)

router = APIRouter(prefix="/api/custom-pets", tags=["自定义宠物"])

# 内存存储（Demo阶段用，正式环境应使用数据库）
# 格式: {pet_id: CustomPetResponse}
custom_pets_storage: dict = {}


# ============ 辅助函数 ============

def get_pet_type_display(pet_type: str) -> str:
    """获取宠物类型的中文显示"""
    type_map = {
        "dog": "小狗",
        "cat": "小猫",
        "rabbit": "小兔",
        "bird": "小鸟",
        "hamster": "小仓鼠",
        "fox": "小狐狸",
        "bear": "小熊",
        "panda": "小熊猫",
        "tiger": "小老虎",
        "lion": "小狮子",
        "snake": "小蛇",
        "cheetah": "小猎豹",
        "deer": "小鹿",
        "lamb": "小羊",
        "pig": "小猪",
        "horse": "小马"
    }
    return type_map.get(pet_type, "其他")


def validate_pet_config(config: CustomPetConfigRequest) -> tuple:
    """
    验证宠物配置
    返回 (is_valid, error_message)
    """
    # 验证宠物名称
    if not config.pet_name or len(config.pet_name.strip()) == 0:
        return False, "宠物名称不能为空"
    if len(config.pet_name) > 8:
        return False, "宠物名称不能超过8个字符"
    
    # 验证宠物类型
    valid_types = ["dog", "cat", "rabbit", "bird", "hamster", "fox", "bear", "panda", 
                   "tiger", "lion", "snake", "cheetah", "deer", "lamb", "pig", "horse"]
    if config.pet_type not in valid_types:
        return False, f"宠物类型无效，请选择: {', '.join(valid_types)}"
    
    # 验证性格标签
    valid_personality_tags = [
        "热情", "高冷", "憨厚", "活泼", "傲娇", "胆小", "粘人", "独立", "温柔", "搞怪",
        "热情活泼", "高冷傲娇", "温柔体贴", "调皮捣蛋", "聪明伶俐", "胆小害羞",
        "忠诚可靠", "好奇宝宝", "话唠吐槽", "安静陪伴", "幽默搞笑", "暖心治愈"
    ]
    if not config.personality_tags:
        return False, "请至少选择一个性格标签"
    for tag in config.personality_tags:
        if tag not in valid_personality_tags:
            return False, f"无效的性格标签: {tag}"
    
    # 验证口头禅长度
    if config.catchphrase and len(config.catchphrase) > 20:
        return False, "口头禅不能超过20个字符"
    
    return True, None


# ============ API 接口 ============

@router.get("/templates", response_model=PetTemplateListResponse)
async def get_pet_templates():
    """
    获取所有可选的宠物模板（预置 + 用户自定义）
    
    返回预置宠物的基本信息列表，以及用户已创建的自定义宠物列表
    """
    # 预置宠物列表
    presets = []
    for pet_type, preset in PRESET_PROMPTS.items():
        presets.append(PetTemplateResponse(
            pet_type=pet_type,
            pet_name=preset["name"],
            personality_tags=preset["personality"],
            is_preset=True
        ))
    
    # 用户自定义宠物列表
    customs = []
    for pet_id, pet in custom_pets_storage.items():
        customs.append(PetTemplateResponse(
            pet_type=pet.pet_type,
            pet_name=pet.pet_name,
            personality_tags=pet.personality_tags,
            is_preset=False
        ))
    
    return PetTemplateListResponse(presets=presets, customs=customs)


@router.post("/preview", response_model=CustomPetPreviewResponse)
async def preview_custom_pet(request: CustomPetPreviewRequest):
    """
    预览自定义宠物配置
    根据用户配置生成完整的 System Prompt，支持用户确认或修改
    """
    # 验证配置
    is_valid, error = validate_pet_config(request)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)
    
    # 生成 System Prompt
    system_prompt = generate_custom_pet_system_prompt(
        pet_name=request.pet_name,
        pet_type=request.pet_type,
        personality_tags=request.personality_tags,
        catchphrase=request.catchphrase,
        special_habits=request.special_habits
    )
    
    # 生成欢迎语
    welcome_messages = generate_welcome_messages(
        pet_name=request.pet_name,
        pet_type=request.pet_type,
        personality_tags=request.personality_tags,
        catchphrase=request.catchphrase
    )
    
    return CustomPetPreviewResponse(
        system_prompt=system_prompt,
        pet_name=request.pet_name,
        pet_type=request.pet_type,
        personality_tags=request.personality_tags,
        catchphrase=request.catchphrase or "",
        special_habits=request.special_habits,
        welcome_messages=welcome_messages
    )


@router.post("", response_model=CustomPetResponse, status_code=201)
async def create_custom_pet(request: CustomPetCreateRequest):
    """
    创建自定义宠物
    保存用户自定义宠物的完整配置
    """
    # 验证配置
    is_valid, error = validate_pet_config(request)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)
    
    # 检查名称是否重复
    for pet in custom_pets_storage.values():
        if pet.pet_name == request.pet_name:
            raise HTTPException(
                status_code=400,
                detail=f"宠物名称「{request.pet_name}」已被使用，请更换名称"
            )
    
    # 生成宠物 ID
    pet_id = f"custom_{uuid.uuid4().hex[:8]}"
    
    # 生成 System Prompt
    system_prompt = generate_custom_pet_system_prompt(
        pet_name=request.pet_name,
        pet_type=request.pet_type,
        personality_tags=request.personality_tags,
        catchphrase=request.catchphrase,
        special_habits=request.special_habits
    )
    
    # 生成口头禅（如果未提供）
    catchphrase = request.catchphrase
    if not catchphrase:
        if "热情" in request.personality_tags or "活泼" in request.personality_tags:
            catchphrase = f"你好呀，我是{request.pet_name}！"
        elif "高冷" in request.personality_tags or "傲娇" in request.personality_tags:
            catchphrase = "哼...才不是关心你。"
        elif "胆小" in request.personality_tags:
            catchphrase = f"{request.pet_name}我啊..."
        else:
            catchphrase = f"我是{request.pet_name}！"
    
    # 创建宠物响应对象
    now = datetime.now()
    pet_response = CustomPetResponse(
        pet_id=pet_id,
        pet_name=request.pet_name,
        pet_type=request.pet_type,
        personality_tags=request.personality_tags,
        catchphrase=catchphrase,
        special_habits=request.special_habits,
        avatar_url=request.avatar_url,
        system_prompt=system_prompt,
        created_at=now
    )
    
    # 存储
    custom_pets_storage[pet_id] = pet_response
    
    return pet_response


@router.get("/{pet_id}", response_model=CustomPetResponse)
async def get_custom_pet(pet_id: str):
    """
    获取自定义宠物详情
    """
    if pet_id not in custom_pets_storage:
        raise HTTPException(status_code=404, detail="宠物不存在")
    
    return custom_pets_storage[pet_id]


@router.put("/{pet_id}", response_model=CustomPetResponse)
async def update_custom_pet(pet_id: str, request: CustomPetCreateRequest):
    """
    更新自定义宠物配置
    """
    if pet_id not in custom_pets_storage:
        raise HTTPException(status_code=404, detail="宠物不存在")
    
    # 验证配置
    is_valid, error = validate_pet_config(request)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)
    
    # 检查名称是否与其他宠物重复（排除自己）
    for pid, pet in custom_pets_storage.items():
        if pid != pet_id and pet.pet_name == request.pet_name:
            raise HTTPException(
                status_code=400,
                detail=f"宠物名称「{request.pet_name}」已被使用，请更换名称"
            )
    
    # 生成新的 System Prompt
    system_prompt = generate_custom_pet_system_prompt(
        pet_name=request.pet_name,
        pet_type=request.pet_type,
        personality_tags=request.personality_tags,
        catchphrase=request.catchphrase,
        special_habits=request.special_habits
    )
    
    # 生成口头禅
    catchphrase = request.catchphrase
    if not catchphrase:
        if "热情" in request.personality_tags or "活泼" in request.personality_tags:
            catchphrase = f"你好呀，我是{request.pet_name}！"
        elif "高冷" in request.personality_tags or "傲娇" in request.personality_tags:
            catchphrase = "哼...才不是关心你。"
        elif "胆小" in request.personality_tags:
            catchphrase = f"{request.pet_name}我啊..."
        else:
            catchphrase = f"我是{request.pet_name}！"
    
    # 更新宠物
    original = custom_pets_storage[pet_id]
    updated = CustomPetResponse(
        pet_id=pet_id,
        pet_name=request.pet_name,
        pet_type=request.pet_type,
        personality_tags=request.personality_tags,
        catchphrase=catchphrase,
        special_habits=request.special_habits,
        avatar_url=request.avatar_url,
        system_prompt=system_prompt,
        created_at=original.created_at  # 保持创建时间不变
    )
    
    custom_pets_storage[pet_id] = updated
    
    return updated


@router.delete("/{pet_id}")
async def delete_custom_pet(pet_id: str):
    """
    删除自定义宠物
    """
    if pet_id not in custom_pets_storage:
        raise HTTPException(status_code=404, detail="宠物不存在")
    
    del custom_pets_storage[pet_id]
    
    return {"message": "删除成功"}


@router.get("")
async def list_custom_pets():
    """
    列出用户所有自定义宠物
    """
    return {
        "pets": [
            {
                "pet_id": pet.pet_id,
                "pet_name": pet.pet_name,
                "pet_type": pet.pet_type,
                "personality_tags": pet.personality_tags,
                "avatar_url": pet.avatar_url,
                "created_at": pet.created_at.isoformat()
            }
            for pet in custom_pets_storage.values()
        ],
        "total": len(custom_pets_storage)
    }
