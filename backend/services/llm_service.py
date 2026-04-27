import httpx
import json
import re
from typing import Optional, List, Dict, Any
from backend.config import settings


class LLMService:
    def __init__(self):
        self.api_key = settings.LLM_API_KEY
        self.base_url = settings.LLM_BASE_URL
        self.model = settings.LLM_MODEL

    def _clean_response(self, text: Optional[str]) -> Optional[str]:
        if not text:
            return None
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'\[Think\].*?\[/Think\]', '', text, flags=re.DOTALL | re.IGNORECASE)
        
        # 清理内部提示词泄露
        text = re.sub(r'用户的消息是[：:].*?(?=\n|$)', '', text, flags=re.IGNORECASE)
        text = re.sub(r'用户要求我扮演.*?(?=\n|$)', '', text, flags=re.IGNORECASE)
        text = re.sub(r'You are.*?(?=\n|$)', '', text, flags=re.IGNORECASE)
        text = re.sub(r'The user asks[：:].*?(?=\n|$)', '', text, flags=re.IGNORECASE)
        text = re.sub(r'So we have a user.*?(?=\n|$)', '', text, flags=re.IGNORECASE)
        
        # 清理 JSON 格式的思考内容
        text = re.sub(r'\{[^{]*?"thought".*?\}', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'\{[^{]*?"reasoning".*?\}', '', text, flags=re.DOTALL | re.IGNORECASE)
        
        # 清理多余的空白字符
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()
        
        # 如果清理后内容过短或看起来不像正常回复，返回 None
        if len(text) < 3 or text.startswith('LLM response:') or text.startswith('用户'):
            return None
            
        return text

    async def _call_llm(self, messages: List[Dict[str, str]], model: str, temperature: float, max_tokens: int) -> Optional[str]:
        if not self.api_key:
            return None

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                cleaned = self._clean_response(content)
                print(f"LLM response: {cleaned}")
                return cleaned
        except Exception as e:
            print(f"LLM API error: {e}")
            return None

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.8,
        max_tokens: int = 500
    ) -> Optional[str]:
        return await self._call_llm(messages, self.model, temperature, max_tokens)

    async def generate_welcome_message(self, pet_type: str, pet_name: str, pet_personality: str) -> str:
        # 根据宠物类型定制欢迎语 prompt
        welcome_prompts = {
            "hot_dog": f"""你是 {pet_name}，{pet_personality}
请用你的性格风格，写一句简短的欢迎主人的话（30字以内）。
你的口头禅是"汪！主人！"或类似风格的开场白。
直接输出欢迎语，不要任何解释。""",
            "cold_cat": f"""你是 {pet_name}，{pet_personality}
请用傲娇的猫咪风格，写一句简短的欢迎主人的话（30字以内）。
口头禅是"哼。......才不是关心你。"
保持高冷但暗藏关心，简洁冷淡。
直接输出欢迎语，不要任何解释。""",
            "mouse": f"""你是 {pet_name}，{pet_personality}
请用胆怯但真诚的小老鼠风格，写一句简短的欢迎主人的话（30字以内）。
可以带"鼠鼠我啊..."这样的开场。
直接输出欢迎语，不要任何解释。"""
        }

        prompt = welcome_prompts.get(pet_type, welcome_prompts["hot_dog"])
        messages = [{"role": "user", "content": prompt}]
        result = await self.chat(messages, temperature=1.0, max_tokens=100)

        # 检查返回内容是否合理（欢迎语应该在50字以内）
        # 如果过长或为None，使用fallback
        if not result or len(result) > 50:
            return self._get_fallback_welcome(pet_type)
        return result

    def _get_fallback_welcome(self, pet_type: str) -> str:
        fallbacks = {
            "hot_dog": "汪！主人！终于等到你啦！",
            "cold_cat": "哼...你来了啊。",
            "mouse": "鼠鼠我啊...见到主人了..."
        }
        return fallbacks.get(pet_type, "你好呀！")

    async def generate_proactive_message(self, pet_type: str, pet_name: str, reason: str) -> Optional[str]:
        prompt = f"""你是 {pet_name}。
原因：{reason}
请用你的性格风格，写一句主动关心主人的消息（40字以内）。
直接输出消息内容，不要任何解释。"""

        messages = [{"role": "user", "content": prompt}]
        return await self.chat(messages, temperature=0.9, max_tokens=150)

    async def extract_emotion(self, user_message: str, pet_type: str) -> str:
        prompt = f"""用户的这条消息：「{user_message}」
请判断用户的情绪，从以下选项中选择一个：happy（开心）、sad（低落）、anxious（焦虑）、tired（疲惫）、neutral（中性）
只输出情绪标签，不要任何解释。"""

        messages = [{"role": "user", "content": prompt}]
        result = await self.chat(messages, temperature=0.3, max_tokens=20)
        valid_emotions = ["happy", "sad", "anxious", "tired", "neutral"]
        if result and result.strip().lower() in valid_emotions:
            return result.strip().lower()
        return "neutral"

    async def extract_schedule(self, user_message: str) -> Optional[Dict[str, str]]:
        prompt = f"""用户的这条消息：「{user_message}」
请判断是否包含日程安排（如约定时间、待办事项等）。
如果有，请用JSON格式输出：{{"content": "日程内容", "scheduled_time": "YYYY-MM-DD HH:MM"}}
如果没有日程，请输出"None"。
直接输出JSON或None，不要任何解释。"""

        messages = [{"role": "user", "content": prompt}]
        result = await self.chat(messages, temperature=0.3, max_tokens=100)
        print(f"[DEBUG] extract_schedule raw result: {result}")  # 添加日志
        if result and result.strip() != "None":
            try:
                schedule = json.loads(result)
                print(f"[DEBUG] Schedule extracted: {schedule}")  # 添加日志
                return schedule
            except Exception as e:
                print(f"[DEBUG] Schedule parse failed: {e}")  # 添加日志
                return None
        print("[DEBUG] No schedule in message")
        return None

    async def compress_memory(self, messages: List[Dict[str, str]], pet_name: str) -> str:
        conversation_text = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
        prompt = f"""以下是一段你和主人之间的对话记录，请压缩成200字以内的摘要，保留关键信息和重要细节：
{conversation_text}
直接输出摘要内容，不要任何解释。"""

        messages_list = [{"role": "user", "content": prompt}]
        result = await self.chat(messages_list, temperature=0.5, max_tokens=300)
        return result or "对话摘要（内容已丢失）"


llm_service = LLMService()