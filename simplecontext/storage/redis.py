"""
Redis Storage Backend — Opsional
Install: pip install redis
"""

import json
from datetime import datetime, timezone
from typing import Any, Optional
from .base import BaseStorage


class RedisStorage(BaseStorage):
    """
    Redis backend untuk SimpleContext.
    Cocok untuk deployment multi-instance atau performa tinggi.

    Config:
        storage:
          backend: redis
          url: redis://localhost:6379/0
          prefix: sc          # prefix semua key Redis
    """

    def __init__(self, url: str = "redis://localhost:6379/0", prefix: str = "sc"):
        try:
            import redis as _redis
        except ImportError:
            raise ImportError(
                "Redis backend membutuhkan library 'redis'.\n"
                "Install: pip install redis"
            )
        self._r = _redis.from_url(url, decode_responses=True)
        self._prefix = prefix
        # Test koneksi
        self._r.ping()

    # ── Key helpers ───────────────────────────────────────

    def _k(self, *parts) -> str:
        return f"{self._prefix}:" + ":".join(str(p) for p in parts)

    # ── Messages ──────────────────────────────────────────

    def save_message(self, user_id, role, content, tags=None, metadata=None) -> int:
        key  = self._k("messages", user_id)
        idx  = self._r.rpush(key, json.dumps({
            "role": role, "content": content,
            "tags": tags or [], "metadata": metadata or {},
            "created_at": _now(),
        }))
        return idx

    def get_messages(self, user_id, limit=20, tags=None) -> list[dict]:
        key  = self._k("messages", user_id)
        raw  = self._r.lrange(key, -limit, -1)
        msgs = [json.loads(r) for r in raw]
        if tags:
            msgs = [m for m in msgs if any(t in m.get("tags", []) for t in tags)]
        return msgs

    def count_messages(self, user_id) -> int:
        return self._r.llen(self._k("messages", user_id))

    def delete_messages(self, user_id, tags=None):
        if tags is None:
            self._r.delete(self._k("messages", user_id))
        else:
            # Redis tidak support filter delete by tag — rebuild list tanpa tag tersebut
            key  = self._k("messages", user_id)
            msgs = self.get_messages(user_id, limit=999999)
            keep = [m for m in msgs if not any(t in m.get("tags", []) for t in tags)]
            pipe = self._r.pipeline()
            pipe.delete(key)
            for m in keep:
                pipe.rpush(key, json.dumps(m))
            pipe.execute()

    def search_messages(self, user_id, keyword, limit=5) -> list[dict]:
        msgs = self.get_messages(user_id, limit=999999)
        found = [m for m in msgs if keyword.lower() in m["content"].lower()]
        return list(reversed(found))[:limit]

    # ── Skills ────────────────────────────────────────────

    def save_skill(self, agent_id, name, content, description="", extends=None,
                   enabled=True, priority=0, group=None, conditions=None,
                   tags=None, metadata=None):
        key = self._k("skills", agent_id, name)
        self._r.set(key, json.dumps({
            "agent_id": agent_id, "name": name, "description": description,
            "content": content, "extends": extends, "enabled": enabled,
            "priority": priority, "group": group, "conditions": conditions or {},
            "tags": tags or [], "metadata": metadata or {},
            "updated_at": _now(),
        }))
        # Index: set of skill names per agent
        self._r.sadd(self._k("skill_index", agent_id), name)

    def get_skill(self, agent_id, name) -> Optional[dict]:
        raw = self._r.get(self._k("skills", agent_id, name))
        return json.loads(raw) if raw else None

    def get_skills(self, agent_id, enabled_only=True, group=None, tags=None) -> list[dict]:
        names  = self._r.smembers(self._k("skill_index", agent_id))
        skills = [self.get_skill(agent_id, n) for n in names]
        skills = [s for s in skills if s]
        if enabled_only:
            skills = [s for s in skills if s.get("enabled", True)]
        if group is not None:
            skills = [s for s in skills if s.get("group") == group]
        if tags:
            skills = [s for s in skills if any(t in s.get("tags", []) for t in tags)]
        return sorted(skills, key=lambda s: (-s.get("priority", 0), s["name"]))

    def delete_skill(self, agent_id, name) -> bool:
        deleted = self._r.delete(self._k("skills", agent_id, name))
        self._r.srem(self._k("skill_index", agent_id), name)
        return bool(deleted)

    def search_skills(self, agent_id, keyword) -> list[dict]:
        skills = self.get_skills(agent_id, enabled_only=True)
        kw = keyword.lower()
        return [s for s in skills if kw in s["name"].lower()
                or kw in s.get("description","").lower()
                or kw in s["content"].lower()]

    # ── Profile ───────────────────────────────────────────

    def get_profile(self, user_id) -> dict:
        raw = self._r.get(self._k("profile", user_id))
        return json.loads(raw) if raw else {}

    def set_profile(self, user_id, data):
        self._r.set(self._k("profile", user_id), json.dumps(data))

    def update_profile(self, user_id, key, value):
        p = self.get_profile(user_id)
        p[key] = value
        self.set_profile(user_id, p)

    # ── Plugin State ──────────────────────────────────────

    def get_plugin_state(self, plugin_name) -> dict:
        raw = self._r.get(self._k("plugin_state", plugin_name))
        return json.loads(raw) if raw else {}

    def set_plugin_state(self, plugin_name, data):
        self._r.set(self._k("plugin_state", plugin_name), json.dumps(data))

    def update_plugin_state(self, plugin_name, key, value):
        s = self.get_plugin_state(plugin_name)
        s[key] = value
        self.set_plugin_state(plugin_name, s)

    # ── Export / Import ───────────────────────────────────

    def export_user(self, user_id) -> dict:
        return {
            "type": "user", "user_id": user_id, "exported_at": _now(),
            "profile": self.get_profile(user_id),
            "messages": self.get_messages(user_id, limit=999999),
        }

    def export_agent(self, agent_id) -> dict:
        return {
            "type": "agent", "agent_id": agent_id, "exported_at": _now(),
            "skills": self.get_skills(agent_id, enabled_only=False),
        }

    def export_all(self) -> dict:
        return {
            "type": "full", "exported_at": _now(), "version": "3.0",
            "users":  {u: self.export_user(u)  for u in self.list_users()},
            "agents": {a: self.export_agent(a) for a in self.list_agents()},
        }

    def import_data(self, data, merge=True):
        dtype = data.get("type", "full")
        if dtype == "user":
            self._import_user(data, merge)
        elif dtype == "agent":
            self._import_agent(data, merge)
        elif dtype == "full":
            for ud in data.get("users",  {}).values(): self._import_user(ud,  merge)
            for ad in data.get("agents", {}).values(): self._import_agent(ad, merge)

    def _import_user(self, data, merge):
        uid = data["user_id"]
        if not merge: self.delete_messages(uid)
        if data.get("profile"):
            prof = {**self.get_profile(uid), **data["profile"]} if merge else data["profile"]
            self.set_profile(uid, prof)
        for m in data.get("messages", []):
            self.save_message(uid, m["role"], m["content"], m.get("tags",[]), m.get("metadata",{}))

    def _import_agent(self, data, merge):
        aid = data["agent_id"]
        if not merge:
            for s in self.get_skills(aid, enabled_only=False): self.delete_skill(aid, s["name"])
        for s in data.get("skills", []):
            self.save_skill(aid, s["name"], s["content"],
                            description=s.get("description",""), extends=s.get("extends"),
                            enabled=bool(s.get("enabled",True)), priority=s.get("priority",0),
                            group=s.get("group"), conditions=s.get("conditions",{}),
                            tags=s.get("tags",[]), metadata=s.get("metadata",{}))

    # ── Utils ─────────────────────────────────────────────

    def get_stats(self) -> dict:
        users  = self.list_users()
        agents = self.list_agents()
        return {
            "backend": "redis",
            "total_users":    len(users),
            "total_messages": sum(self.count_messages(u) for u in users),
            "total_agents":   len(agents),
            "total_skills":   sum(len(self.get_skills(a, enabled_only=False)) for a in agents),
            "total_profiles": len(users),
        }

    def list_users(self) -> list[str]:
        keys = self._r.keys(self._k("messages", "*"))
        prefix = self._k("messages") + ":"
        return [k[len(prefix):] for k in keys]

    def list_agents(self) -> list[str]:
        keys = self._r.keys(self._k("skill_index", "*"))
        prefix = self._k("skill_index") + ":"
        return [k[len(prefix):] for k in keys]

    def close(self):
        self._r.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
