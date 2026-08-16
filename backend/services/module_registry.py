"""Closed registry for built-in leisure modules."""
from __future__ import annotations

BUILTIN_MODULES = {
    "builtin.novel": {
        "module_id": "builtin.novel", "version": "1.0.0", "title": "小说", "module_type": "novel",
        "description": "读一小段故事，随时从上次的位置继续。", "icon": "📖", "source": "builtin",
        "required_permissions": [], "entrypoint": "builtin.novel",
    }
}


def get_module(module_id: str) -> dict | None:
    module = BUILTIN_MODULES.get(module_id)
    return dict(module) if module else None


def list_modules() -> list[dict]:
    return [dict(module) for module in BUILTIN_MODULES.values()]


def validate_module(module_id: str) -> dict:
    module = get_module(module_id)
    if not module or module.get("source") != "builtin":
        raise ValueError("unknown or external leisure module")
    return module
