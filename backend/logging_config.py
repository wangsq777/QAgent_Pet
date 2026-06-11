"""
统一日志工具

使用 Python logging 模块，支持 LOG_LEVEL 环境变量控制日志级别。
DEBUG: 敏感数据（用户消息、LLM 响应、画像数据）
INFO: 业务流程（工具调用、日程提取、压缩触发）
WARNING: 可恢复的失败
ERROR: 严重错误
"""

import logging
import os


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level, logging.INFO))
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            '[%(levelname)s] %(name)s: %(message)s'
        ))
        logger.addHandler(handler)
    return logger