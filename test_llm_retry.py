"""
LLM 调用重试逻辑单元测试

运行：python test_llm_retry.py
覆盖 _call_llm 的重试策略：仅 429/5xx 与网络错误（RequestError）重试，
其余 4xx / 解析失败保持原有 return None 行为；退避基数为 0 时不引入真实等待。
"""
import asyncio
import importlib
import unittest
from unittest.mock import patch

import httpx

from backend.config import settings

llm_service_module = importlib.import_module("backend.services.llm_service")
from backend.services.llm_service import LLMService


def _text_payload(text):
    return {"content": [{"type": "text", "text": text}]}


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://test/v1/messages")
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """按 script 列表依次返回响应或抛出异常，并记录 post 调用。"""

    def __init__(self, script, calls):
        # 共享同一个 script 队列（不拷贝）：_call_llm 每次重试都会新建 client，
        # 必须让后续 attempt 拿到前一个 attempt pop 之后的剩余队列
        self._script = script
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, headers=None, json=None):
        self._calls.append({"url": url, "json": json})
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class TestLLMRetry(unittest.TestCase):
    def setUp(self):
        self.service = LLMService()
        self.calls = []
        self.script = []

        patches = [
            patch.object(settings, "LLM_API_KEY", "test-key"),
            patch.object(settings, "LLM_RETRY_ATTEMPTS", 2),
            patch.object(settings, "LLM_RETRY_BASE_DELAY", 0.0),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        # 用 fake 命名空间替换模块内对 httpx 的引用，避免全局污染真实 httpx 模块
        fake_httpx = type("FakeHttpx", (), {
            "HTTPStatusError": httpx.HTTPStatusError,
            "RequestError": httpx.RequestError,
            "Timeout": httpx.Timeout,
            "AsyncClient": lambda **kwargs: _FakeAsyncClient(self.script, self.calls),
        })
        client_patch = patch.object(llm_service_module, "httpx", fake_httpx)
        client_patch.start()
        self.addCleanup(client_patch.stop)

    def _chat(self, messages=None):
        return asyncio.run(
            self.service.chat(messages or [{"role": "user", "content": "hi"}])
        )

    def test_success_first_try(self):
        self.script = [_FakeResponse(200, _text_payload("你好呀"))]
        self.assertEqual(self._chat(), "你好呀")
        self.assertEqual(len(self.calls), 1)

    def test_retry_on_500_then_success(self):
        self.script = [_FakeResponse(500), _FakeResponse(200, _text_payload("重试成功"))]
        self.assertEqual(self._chat(), "重试成功")
        self.assertEqual(len(self.calls), 2)

    def test_retry_on_429_exhausted_returns_none(self):
        self.script = [_FakeResponse(429), _FakeResponse(429), _FakeResponse(429)]
        self.assertIsNone(self._chat())
        self.assertEqual(len(self.calls), 3)

    def test_no_retry_on_400(self):
        self.script = [_FakeResponse(400), _FakeResponse(200, _text_payload("不应到达"))]
        self.assertIsNone(self._chat())
        self.assertEqual(len(self.calls), 1)

    def test_retry_on_request_error_then_success(self):
        request = httpx.Request("POST", "http://test/v1/messages")
        self.script = [httpx.ConnectError("boom", request=request),
                       _FakeResponse(200, _text_payload("网络恢复"))]
        self.assertEqual(self._chat(), "网络恢复")
        self.assertEqual(len(self.calls), 2)

    def test_retry_disabled_when_attempts_zero(self):
        with patch.object(settings, "LLM_API_KEY", "test-key"), \
             patch.object(settings, "LLM_RETRY_ATTEMPTS", 0), \
             patch.object(settings, "LLM_RETRY_BASE_DELAY", 0.0):
            self.script = [_FakeResponse(503), _FakeResponse(200, _text_payload("不应到达"))]
            self.assertIsNone(self._chat())
            self.assertEqual(len(self.calls), 1)

    def test_no_key_returns_none_without_call(self):
        with patch.object(settings, "LLM_API_KEY", ""), \
             patch.object(settings, "LLM_RETRY_ATTEMPTS", 2), \
             patch.object(settings, "LLM_RETRY_BASE_DELAY", 0.0):
            self.script = [_FakeResponse(200, _text_payload("不应到达"))]
            self.assertIsNone(self._chat())
            self.assertEqual(len(self.calls), 0)


if __name__ == "__main__":
    unittest.main()
