"""
自定义宠物管理路由
支持自定义宠物的创建、预览和管理
数据持久化到 SQLite 数据库
"""

import json
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.database import get_db
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
limiter = Limiter(key_func=get_remote_address)


# ============ 辅助函数 ============

def get_pet_type_display(pet_type: str) -> str:
    """获取宠物类型的中文显示"""
    type_map = {
        "dog": "小狗", "cat": "小猫", "rabbit": "小兔", "bird": "小鸟",
        "hamster": "小仓鼠", "fox": "小狐狸", "bear": "小熊", "panda": "小熊猫",
        "tiger": "小老虎", "lion": "小狮子", "snake": "小蛇", "cheetah": "小猎豹",
        "deer": "小鹿", "lamb": "小羊", "pig": "小猪", "horse": "小马"
    }
    return type_map.get(pet_type, "其他")


def validate_pet_config(config: CustomPetConfigRequest) -> tuple:
    """
    验证宠物配置
    返回 (is_valid, error_message)
    """
    if not config.pet_name or len(config.pet_name.strip()) == 0:
        return False, "宠物名称不能为空"
    if len(config.pet_name) > 8:
        return False, "宠物名称不能超过8个字符"

    valid_types = ["dog", "cat", "rabbit", "bird", "hamster", "fox", "bear", "panda",
                   "tiger", "lion", "snake", "cheetah", "deer", "lamb", "pig", "horse"]
    if config.pet_type not in valid_types:
        return False, f"宠物类型无效，请选择: {', '.join(valid_types)}"

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

    if config.catchphrase and len(config.catchphrase) > 20:
        return False, "口头禅不能超过20个字符"

    return True, None


def _row_to_pet_response(row) -> CustomPetResponse:
    """将数据库行转换为 CustomPetResponse"""
    row_dict = dict(row)
    return CustomPetResponse(
        pet_id=row_dict["pet_id"],
        pet_name=row_dict["pet_name"],
        pet_type=row_dict["pet_type"],
        personality_tags=json.loads(row_dict["personality_tags"]),
        catchphrase=row_dict["catchphrase"] or "",
        special_habits=row_dict["special_habits"] or "",
        avatar_url=row_dict["avatar_url"] or "",
        system_prompt=row_dict["system_prompt"],
        created_at=datetime.fromisoformat(row_dict["created_at"]) if isinstance(row_dict["created_at"], str) else row_dict["created_at"]
    )


# ============ API 接口 ============

@router.get("/templates", response_model=PetTemplateListResponse)
@limiter.limit("60/minute")
async def get_pet_templates(request: Request):
    """
    获取所有可选的宠物模板（预置 + 用户自定义）
    """
    user_id = request.state.user_id
    presets = []
    for pet_type, preset in PRESET_PROMPTS.items():
        presets.append(PetTemplateResponse(
            pet_type=pet_type,
            pet_name=preset["name"],
            personality_tags=preset["personality"],
            is_preset=True
        ))

    customs = []
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM custom_pets WHERE user_id = ?",
            (user_id,)
        )
        rows = await cursor.fetchall()
        for row in rows:
            pet = _row_to_pet_response(row)
            customs.append(PetTemplateResponse(
                pet_type=pet.pet_type,
                pet_name=pet.pet_name,
                personality_tags=pet.personality_tags,
                is_preset=False
            ))

    return PetTemplateListResponse(presets=presets, customs=customs)


@router.post("/preview", response_model=CustomPetPreviewResponse)
@limiter.limit("30/minute")
async def preview_custom_pet(body: CustomPetPreviewRequest, request: Request):
    """
    预览自定义宠物配置
    根据用户配置生成完整的 System Prompt，支持用户确认或修改
    """
    is_valid, error = validate_pet_config(body)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)

    system_prompt = generate_custom_pet_system_prompt(
        pet_name=body.pet_name,
        pet_type=body.pet_type,
        personality_tags=body.personality_tags,
        catchphrase=body.catchphrase,
        special_habits=body.special_habits
    )

    welcome_messages = await generate_welcome_messages(
        pet_name=body.pet_name,
        pet_type=body.pet_type,
        personality_tags=body.personality_tags,
        catchphrase=body.catchphrase
    )

    return CustomPetPreviewResponse(
        system_prompt=system_prompt,
        pet_name=body.pet_name,
        pet_type=body.pet_type,
        personality_tags=body.personality_tags,
        catchphrase=body.catchphrase or "",
        special_habits=body.special_habits,
        welcome_messages=welcome_messages
    )


@router.post("", response_model=CustomPetResponse, status_code=201)
@limiter.limit("10/minute")
async def create_custom_pet(body: CustomPetCreateRequest, request: Request):
    """
    创建自定义宠物
    保存用户自定义宠物的完整配置到数据库
    """
    user_id = request.state.user_id
    is_valid, error = validate_pet_config(body)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)

    # 检查名称是否重复
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT pet_id FROM custom_pets WHERE user_id = ? AND pet_name = ?",
            (user_id, body.pet_name)
        )
        if await cursor.fetchone():
            raise HTTPException(
                status_code=400,
                detail=f"宠物名称「{body.pet_name}」已被使用，请更换名称"
            )

    pet_id = f"custom_{uuid.uuid4().hex[:8]}"

    system_prompt = generate_custom_pet_system_prompt(
        pet_name=body.pet_name,
        pet_type=body.pet_type,
        personality_tags=body.personality_tags,
        catchphrase=body.catchphrase,
        special_habits=body.special_habits
    )

    # 生成口头禅（如果未提供）
    catchphrase = body.catchphrase
    if not catchphrase:
        if "热情" in body.personality_tags or "活泼" in body.personality_tags:
            catchphrase = f"你好呀，我是{body.pet_name}！"
        elif "高冷" in body.personality_tags or "傲娇" in body.personality_tags:
            catchphrase = "哼...才不是关心你。"
        elif "胆小" in body.personality_tags:
            catchphrase = f"{body.pet_name}我啊..."
        else:
            catchphrase = f"我是{body.pet_name}！"

    now = datetime.now()

    async with get_db() as db:
        await db.execute(
            """INSERT INTO custom_pets 
               (pet_id, user_id, pet_name, pet_type, personality_tags, catchphrase, 
                special_habits, avatar_url, system_prompt, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pet_id, user_id, body.pet_name, body.pet_type,
             json.dumps(body.personality_tags, ensure_ascii=False),
             catchphrase, body.special_habits or "",
             body.avatar_url or "", system_prompt, now, now)
        )
        await db.commit()

    return CustomPetResponse(
        pet_id=pet_id,
        pet_name=body.pet_name,
        pet_type=body.pet_type,
        personality_tags=body.personality_tags,
        catchphrase=catchphrase,
        special_habits=body.special_habits,
        avatar_url=body.avatar_url,
        system_prompt=system_prompt,
        created_at=now
    )


@router.get("/detail/{pet_id}", response_model=CustomPetResponse)
@limiter.limit("60/minute")
async def get_custom_pet(pet_id: str, request: Request):
    """
    获取自定义宠物详情
    """
    user_id = request.state.user_id
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM custom_pets WHERE pet_id = ? AND user_id = ?",
            (pet_id, user_id)
        )
        row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="宠物不存在")

    return _row_to_pet_response(row)


@router.put("/detail/{pet_id}", response_model=CustomPetResponse)
@limiter.limit("10/minute")
async def update_custom_pet(pet_id: str, body: CustomPetCreateRequest, request: Request):
    """
    更新自定义宠物配置
    """
    user_id = request.state.user_id
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM custom_pets WHERE pet_id = ? AND user_id = ?",
            (pet_id, user_id)
        )
        row = await cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="宠物不存在")

        original = _row_to_pet_response(row)

    is_valid, error = validate_pet_config(body)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)

    # 检查名称是否与其他宠物重复（排除自己）
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT pet_id FROM custom_pets WHERE user_id = ? AND pet_name = ? AND pet_id != ?",
            (user_id, body.pet_name, pet_id)
        )
        if await cursor.fetchone():
            raise HTTPException(
                status_code=400,
                detail=f"宠物名称「{body.pet_name}」已被使用，请更换名称"
            )

    system_prompt = generate_custom_pet_system_prompt(
        pet_name=body.pet_name,
        pet_type=body.pet_type,
        personality_tags=body.personality_tags,
        catchphrase=body.catchphrase,
        special_habits=body.special_habits
    )

    catchphrase = body.catchphrase
    if not catchphrase:
        if "热情" in body.personality_tags or "活泼" in body.personality_tags:
            catchphrase = f"你好呀，我是{body.pet_name}！"
        elif "高冷" in body.personality_tags or "傲娇" in body.personality_tags:
            catchphrase = "哼...才不是关心你。"
        elif "胆小" in body.personality_tags:
            catchphrase = f"{body.pet_name}我啊..."
        else:
            catchphrase = f"我是{body.pet_name}！"

    now = datetime.now()

    async with get_db() as db:
        await db.execute(
            """UPDATE custom_pets SET
               pet_name=?, pet_type=?, personality_tags=?, catchphrase=?,
               special_habits=?, avatar_url=?, system_prompt=?, updated_at=?
               WHERE pet_id=? AND user_id=?""",
            (body.pet_name, body.pet_type,
             json.dumps(body.personality_tags, ensure_ascii=False),
             catchphrase, body.special_habits or "",
             body.avatar_url or "", system_prompt, now, pet_id, user_id)
        )
        await db.commit()

    return CustomPetResponse(
        pet_id=pet_id,
        pet_name=body.pet_name,
        pet_type=body.pet_type,
        personality_tags=body.personality_tags,
        catchphrase=catchphrase,
        special_habits=body.special_habits,
        avatar_url=body.avatar_url,
        system_prompt=system_prompt,
        created_at=original.created_at
    )


@router.delete("/detail/{pet_id}")
@limiter.limit("10/minute")
async def delete_custom_pet(pet_id: str, request: Request):
    """
    删除自定义宠物及所有关联数据

    安全校验：
    - pet_id 必须以 custom_ 开头，防止误删预置宠物
    - 按 user_id 查询，确保只能删除自己的宠物
    - 级联清理 pet_sessions / messages / long_term_memories / schedules / memory_vectors
    """
    user_id = request.state.user_id
    if not pet_id.startswith("custom_"):
        raise HTTPException(status_code=403, detail="预置宠物不支持删除")

    async with get_db() as db:
        # 1. 安全校验：按 user_id 查询宠物
        cursor = await db.execute(
            "SELECT pet_id FROM custom_pets WHERE pet_id = ? AND user_id = ?",
            (pet_id, user_id)
        )
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="宠物不存在")

        # 2. 查找关联会话
        cursor = await db.execute(
            "SELECT session_id FROM pet_sessions WHERE custom_pet_id = ?",
            (pet_id,)
        )
        session_rows = await cursor.fetchall()
        session_ids = [dict(row)["session_id"] for row in session_rows]

        # 3. 级联清理关联数据
        if session_ids:
            placeholders = ",".join(["?" for _ in session_ids])

            await db.execute(
                f"DELETE FROM messages WHERE session_id IN ({placeholders})",
                session_ids
            )
            await db.execute(
                f"DELETE FROM long_term_memories WHERE session_id IN ({placeholders})",
                session_ids
            )
            await db.execute(
                f"DELETE FROM schedules WHERE session_id IN ({placeholders})",
                session_ids
            )
            await db.execute(
                f"DELETE FROM memory_vectors WHERE session_id IN ({placeholders})",
                session_ids
            )
            await db.execute(
                f"DELETE FROM pet_sessions WHERE session_id IN ({placeholders})",
                session_ids
            )

        # 4. 删除宠物记录
        await db.execute("DELETE FROM custom_pets WHERE pet_id = ?", (pet_id,))
        await db.commit()

    return {"message": "删除成功", "cleaned_sessions": len(session_ids)}


@router.get("")
@limiter.limit("60/minute")
async def list_custom_pets(request: Request):
    """
    列出用户所有自定义宠物
    """
    user_id = request.state.user_id
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM custom_pets WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        )
        rows = await cursor.fetchall()

    return {
        "pets": [
            {
                "pet_id": dict(row)["pet_id"],
                "pet_name": dict(row)["pet_name"],
                "pet_type": dict(row)["pet_type"],
                "personality_tags": json.loads(dict(row)["personality_tags"]),
                "avatar_url": dict(row)["avatar_url"],
                "created_at": dict(row)["created_at"]
            }
            for row in rows
        ],
        "total": len(rows)
    }
