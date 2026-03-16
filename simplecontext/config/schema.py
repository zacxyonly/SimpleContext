"""
Config Schema v3
Load, validasi, dan akses konfigurasi dari YAML atau JSON.
Zero external dependencies.
"""

import json
import os
from typing import Any


DEFAULTS: dict = {
    "simplecontext": {"version": "3.0"},
    "storage": {"backend": "sqlite", "path": "./simplecontext.db"},
    "memory": {"default_limit": 20, "max_per_user": 1000,
                "compression": {"enabled": False, "threshold": 50, "keep_last": 10}},
    "skills": {"inheritance_depth": 5},
    "agents": {"folder": "./agents", "hot_reload": True, "default": "general"},
    "plugins": {"enabled": True, "folder": "./plugins"},
    "export": {"folder": "./exports"},
}


class Config:
    def __init__(self, data: dict):
        self._data = _deep_merge(DEFAULTS, data)

    @classmethod
    def load(cls, path: str) -> "Config":
        if not path or not os.path.exists(path):
            return cls({})
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return cls({})
        if path.endswith(".json") or content.startswith("{"):
            try:
                return cls(json.loads(content))
            except json.JSONDecodeError as e:
                raise ValueError(f"Config JSON tidak valid: {e}")
        if path.endswith((".yaml", ".yml")):
            try:
                return cls(_parse_yaml(content))
            except Exception as e:
                raise ValueError(f"Config YAML tidak valid: {e}")
        raise ValueError(f"Format tidak dikenali: {path}")

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        return cls(data)

    @classmethod
    def default(cls) -> "Config":
        return cls({})

    def get(self, key: str, default: Any = None) -> Any:
        parts = key.split(".")
        node = self._data
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, key: str, value: Any):
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def section(self, name: str) -> dict:
        return self._data.get(name, {})

    def all(self) -> dict:
        return self._data

    def save(self, path: str):
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def __repr__(self):
        return f"<Config v{self.get('simplecontext.version')} backend={self.get('storage.backend')}>"


# ── Helpers ───────────────────────────────────────────────

def _deep_merge(base: dict, override: dict) -> dict:
    import copy
    result = copy.deepcopy(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


def _parse_yaml(content: str) -> dict:
    result = {}
    stack: list[tuple[int, dict]] = [(-1, result)]
    for raw_line in content.splitlines():
        stripped = raw_line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        indent = len(raw_line) - len(stripped)
        key, _, raw_val = stripped.partition(":")
        key = key.strip()
        val_str = raw_val.strip()
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if val_str == "" or val_str.startswith("#"):
            new_dict: dict = {}
            parent[key] = new_dict
            stack.append((indent, new_dict))
        else:
            if " #" in val_str:
                val_str = val_str[:val_str.index(" #")].strip()
            parent[key] = _cast(val_str)
    return result


def _cast(val: str) -> Any:
    if val.lower() in ("true", "yes", "on"):   return True
    if val.lower() in ("false", "no", "off"):  return False
    if val.lower() in ("null", "~", "none"):   return None
    if (val.startswith('"') and val.endswith('"')) or \
       (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    try: return int(val)
    except ValueError: pass
    try: return float(val)
    except ValueError: pass
    return val
