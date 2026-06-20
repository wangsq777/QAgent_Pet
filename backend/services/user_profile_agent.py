"""
用户画像总结 Agent
专门负责从对话历史中提取和更新用户画像信息
"""
from typing import Optional, Dict, Any
from backend.services.llm_service import llm_service
from backend.logging_config import get_logger

logger = get_logger(__name__)


class UserProfileAgent:
    """
    用户画像总结 Agent
    接收对话历史，返回提取的用户画像信息（不影响主对话流程）
    """
    
    PROFILE_EXTRACT_PROMPT = """你是一个用户信息提取专家。请从对话历史中提取用户的个人信息。

【对话历史】
{conversation_history}

请提取以下信息：
1. 地区/城市：用户提到过的居住地、工作地、旅行目的地等
2. 身份标签：用户的角色，如学生党、上班族、自由职业等
3. 兴趣爱好：用户提到过的爱好、运动、游戏、美食等（多个用逗号分隔）
4. 职业/专业：用户的具体职业或学科专业
5. 性格特征：从对话中推断用户的性格倾向，如内向、幽默、健谈等
6. 活跃时段：用户常在线的时间段
7. 其他信息：用户的习惯、偏好、特殊情况等

请用JSON格式输出：
{{"region": "城市或地区", "identity": "身份标签", "interests": "兴趣爱好", "occupation": "职业或专业", "personality_hint": "性格特征", "active_hours": "活跃时段", "extra_info": "其他重要信息"}}
如果某项完全无法确定，设为null。
只输出JSON，不要任何解释。"""

    async def analyze_and_extract(self, conversation_history: str, existing_profile: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """
        分析对话历史，提取用户画像信息
        
        Args:
            conversation_history: 对话历史，格式为 "主人: xxx\n汪汪: xxx"
            existing_profile: 现有的用户画像（用于合并）
            
        Returns:
            提取到的用户画像信息，如果没有提取到任何信息返回 None
        """
        if not conversation_history or len(conversation_history.strip()) < 10:
            logger.debug("对话历史太短，跳过提取")
            return None
        
        prompt = self.PROFILE_EXTRACT_PROMPT.format(
            conversation_history=conversation_history
        )
        
        messages = [{"role": "user", "content": prompt}]
        result = await llm_service._call_llm(
            messages,
            llm_service.model,
            temperature=0.3,
            max_tokens=2000,
            caller="user_profile_agent"
        )
        
        logger.debug("LLM result: %s", result)
        
        if not result:
            return None
        
        # 解析 JSON
        import json
        import re
        
        try:
            # 尝试多种方式提取 JSON
            code_block_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', result)
            if code_block_match:
                profile_data = json.loads(code_block_match.group(1))
            else:
                json_start = result.find('{')
                json_end = result.rfind('}')
                if json_start != -1 and json_end != -1 and json_end > json_start:
                    profile_data = json.loads(result[json_start:json_end+1])
                else:
                    profile_data = json.loads(result)
            
            # 检查是否有任何有效数据
            has_data = any(
                v for k, v in profile_data.items() 
                if v is not None and v != "null" and v != "" and v != []
            )
            
            if has_data:
                logger.debug("提取到用户画像: %s", profile_data)
                return profile_data
            else:
                logger.debug("未提取到有效信息")
                return None
                
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("JSON解析失败: %s, result: %s", e, result[:200] if result else "None")
            return None


# 全局单例
user_profile_agent = UserProfileAgent()
