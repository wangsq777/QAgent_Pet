"""
工具调用执行器 - 支持 Agent 调用各种工具
"""
import re
import json
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass


# 工具参数验证规则
TOOL_ARG_SCHEMAS = {
    "query_weather": {
        "location": {"type": str, "max_length": 50, "pattern": r'^[一-龥a-zA-Z\s\-]+$'}
    }
}


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    result: Any = None
    error: str = None


class ToolExecutor:
    """工具调用执行器"""

    def __init__(self):
        self._tools: Dict[str, Callable] = {}

    def register(self, name: str, func: Callable):
        """注册工具"""
        self._tools[name] = func

    async def execute(self, tool_name: str, args: Dict[str, Any]) -> ToolResult:
        """执行工具调用"""
        if tool_name not in self._tools:
            return ToolResult(success=False, error=f"未知工具: {tool_name}")

        # 参数验证
        schema = TOOL_ARG_SCHEMAS.get(tool_name)
        if schema:
            for key, rules in schema.items():
                if key in args:
                    value = args[key]
                    if not isinstance(value, rules["type"]):
                        return ToolResult(False, None, f"参数类型错误: {key}")
                    if len(str(value)) > rules.get("max_length", 100):
                        return ToolResult(False, None, f"参数过长: {key}")
                    if "pattern" in rules and not re.match(rules["pattern"], str(value)):
                        return ToolResult(False, None, f"参数格式非法: {key}")

        try:
            func = self._tools[tool_name]
            # 支持异步和同步函数
            if hasattr(func, '__code__') and func.__code__.co_flags & 0x80:  # async function
                result = await func(**args)
            else:
                result = func(**args)
            return ToolResult(success=True, result=result)
        except Exception as e:
            return ToolResult(success=False, error=str(e))
    
    @staticmethod
    def parse_tool_calls(text: str) -> List[Dict[str, Any]]:
        """
        从 LLM 输出中解析工具调用
        支持多种格式：
        1. [TOOL_CALL] {tool: "xxx", args: {...}} [/TOOL_CALL]
        2. tool: xxx\nargs: {...}
        3. {"tool": "xxx", "args": {...}}
        """
        tool_calls = []
        
        # 格式1: [TOOL_CALL] ... [/TOOL_CALL]
        pattern1 = r'\[TOOL_CALL\]\s*(\{[\s\S]*?\})\s*\[/TOOL_CALL\]'
        for match in re.finditer(pattern1, text, re.IGNORECASE):
            try:
                data = json.loads(match.group(1))
                if 'tool' in data:
                    tool_calls.append({
                        'tool': data['tool'],
                        'args': data.get('args', {})
                    })
            except json.JSONDecodeError:
                continue
        
        # 格式2: JSON 对象
        pattern2 = r'\{\s*"tool"\s*:\s*"([^"]+)"[\s\S]*?"args"\s*:\s*(\{[\s\S]*?\})'
        for match in re.finditer(pattern2, text):
            try:
                tool_name = match.group(1)
                args = json.loads(match.group(2))
                tool_calls.append({
                    'tool': tool_name,
                    'args': args
                })
            except json.JSONDecodeError:
                continue
        
        return tool_calls
    
    @staticmethod
    def remove_tool_calls(text: str) -> str:
        """从回复中移除工具调用部分，只保留文本回复"""
        # 移除 [TOOL_CALL] 块
        text = re.sub(r'\[TOOL_CALL\]\s*\{[\s\S]*?\}\s*\[/TOOL_CALL\]', '', text, flags=re.IGNORECASE)
        # 移除独立的 JSON 工具调用
        text = re.sub(r'\{\s*"tool"\s*:\s*"[^"]+"(?:[^}]|\}[^,])\}', '', text)
        # 清理多余空白
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()


# 全局工具执行器实例
tool_executor = ToolExecutor()
