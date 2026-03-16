"""
PostgreSQL Storage Backend — Opsional
Install: pip install psycopg2-binary
"""

import json
from datetime import datetime, timezone
from typing import Any, Optional
from .base import BaseStorage


class PostgreSQLStorage(BaseStorage):
    """
    PostgreSQL backend untuk SimpleContext.
    Cocok untuk production skala besar dengan banyak user.

    Config:
        storage:
          backend: postgresql
          dsn: postgresql://user:password@localhost:5432/mydb
    """

    def __init__(self, dsn: str):
        try:
            import psycopg2
            import psycopg2.extras
            self._psycopg2 = psycopg2
            self._extras   = psycopg2.extras
        except ImportError:
            raise ImportError(
                "PostgreSQL backend membutuhkan library 'psycopg2'.\n"
                "Install: pip install psycopg2-binary"
            )
        self._dsn  = dsn
        self._conn = psycopg2.connect(dsn)
        self._conn.autocommit = False
        self._init_tables()

    def _cur(self):
        return self._conn.cursor(cursor_factory=self._extras.RealDictCursor)

    def _init_tables(self):
        with self._cur() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sc_messages (
                    id         SERIAL PRIMARY KEY,
                    user_id    TEXT   NOT NULL,
                    role       TEXT   NOT NULL,
                    content    TEXT   NOT NULL,
                    tags       JSONB  DEFAULT '[]',
                    metadata   JSONB  DEFAULT '{}',
                    created_at TEXT   NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sc_skills (
                    id          SERIAL PRIMARY KEY,
                    agent_id    TEXT    NOT NULL,
                    name        TEXT    NOT NULL,
                    description TEXT    DEFAULT '',
                    content     TEXT    NOT NULL,
                    extends     TEXT,
                    enabled     BOOLEAN DEFAULT TRUE,
                    priority    INTEGER DEFAULT 0,
                    grp         TEXT,
                    conditions  JSONB   DEFAULT '{}',
                    tags        JSONB   DEFAULT '[]',
                    metadata    JSONB   DEFAULT '{}',
                    created_at  TEXT    NOT NULL,
                    updated_at  TEXT    NOT NULL,
                    UNIQUE(agent_id, name)
                );
                CREATE TABLE IF NOT EXISTS sc_profiles (
                    user_id    TEXT PRIMARY KEY,
                    data       JSONB DEFAULT '{}',
                    updated_at TEXT  NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sc_plugin_states (
                    plugin_name TEXT PRIMARY KEY,
                    data        JSONB DEFAULT '{}',
                    updated_at  TEXT  NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sc_messages_user  ON sc_messages(user_id);
                CREATE INDEX IF NOT EXISTS idx_sc_skills_agent   ON sc_skills(agent_id);
                CREATE INDEX IF NOT EXISTS idx_sc_skills_enabled ON sc_skills(agent_id, enabled);
            """)
        self._conn.commit()

    # ── Messages ──────────────────────────────────────────

    def save_message(self, user_id, role, content, tags=None, metadata=None) -> int:
        with self._cur() as cur:
            cur.execute(
                "INSERT INTO sc_messages (user_id,role,content,tags,metadata,created_at) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id",
                (user_id, role, content, json.dumps(tags or []), json.dumps(metadata or {}), _now())
            )
            row_id = cur.fetchone()["id"]
        self._conn.commit()
        return row_id

    def get_messages(self, user_id, limit=20, tags=None) -> list[dict]:
        with self._cur() as cur:
            if tags:
                cur.execute(
                    "SELECT * FROM (SELECT * FROM sc_messages WHERE user_id=%s ORDER BY id DESC LIMIT %s) sub ORDER BY id ASC",
                    (user_id, limit * 3)
                )
                rows = [dict(r) for r in cur.fetchall()]
                rows = [r for r in rows if any(t in (r.get("tags") or []) for t in tags)]
                return rows[-limit:]
            else:
                cur.execute(
                    "SELECT * FROM (SELECT * FROM sc_messages WHERE user_id=%s ORDER BY id DESC LIMIT %s) sub ORDER BY id ASC",
                    (user_id, limit)
                )
                return [dict(r) for r in cur.fetchall()]

    def count_messages(self, user_id) -> int:
        with self._cur() as cur:
            cur.execute("SELECT COUNT(*) as c FROM sc_messages WHERE user_id=%s", (user_id,))
            return cur.fetchone()["c"]

    def delete_messages(self, user_id, tags=None):
        with self._cur() as cur:
            if tags:
                for tag in tags:
                    cur.execute("DELETE FROM sc_messages WHERE user_id=%s AND tags @> %s", (user_id, json.dumps([tag])))
            else:
                cur.execute("DELETE FROM sc_messages WHERE user_id=%s", (user_id,))
        self._conn.commit()

    def search_messages(self, user_id, keyword, limit=5) -> list[dict]:
        with self._cur() as cur:
            cur.execute(
                "SELECT * FROM sc_messages WHERE user_id=%s AND content ILIKE %s ORDER BY id DESC LIMIT %s",
                (user_id, f"%{keyword}%", limit)
            )
            return [dict(r) for r in cur.fetchall()]

    # ── Skills ────────────────────────────────────────────

    def save_skill(self, agent_id, name, content, description="", extends=None,
                   enabled=True, priority=0, group=None, conditions=None,
                   tags=None, metadata=None):
        now = _now()
        with self._cur() as cur:
            cur.execute("""
                INSERT INTO sc_skills
                    (agent_id,name,description,content,extends,enabled,priority,grp,conditions,tags,metadata,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(agent_id,name) DO UPDATE SET
                    description=EXCLUDED.description, content=EXCLUDED.content,
                    extends=EXCLUDED.extends, enabled=EXCLUDED.enabled,
                    priority=EXCLUDED.priority, grp=EXCLUDED.grp,
                    conditions=EXCLUDED.conditions, tags=EXCLUDED.tags,
                    metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at
            """, (agent_id, name, description, content, extends, enabled, priority,
                  group, json.dumps(conditions or {}), json.dumps(tags or []),
                  json.dumps(metadata or {}), now, now))
        self._conn.commit()

    def get_skill(self, agent_id, name) -> Optional[dict]:
        with self._cur() as cur:
            cur.execute("SELECT * FROM sc_skills WHERE agent_id=%s AND name=%s", (agent_id, name))
            row = cur.fetchone()
            return _pg_row(dict(row)) if row else None

    def get_skills(self, agent_id, enabled_only=True, group=None, tags=None) -> list[dict]:
        query = "SELECT * FROM sc_skills WHERE agent_id=%s"
        params: list = [agent_id]
        if enabled_only:
            query += " AND enabled=TRUE"
        if group is not None:
            query += " AND grp=%s"; params.append(group)
        if tags:
            for tag in tags:
                query += " AND tags @> %s"; params.append(json.dumps([tag]))
        query += " ORDER BY priority DESC, name ASC"
        with self._cur() as cur:
            cur.execute(query, params)
            return [_pg_row(dict(r)) for r in cur.fetchall()]

    def delete_skill(self, agent_id, name) -> bool:
        with self._cur() as cur:
            cur.execute("DELETE FROM sc_skills WHERE agent_id=%s AND name=%s", (agent_id, name))
            deleted = cur.rowcount > 0
        self._conn.commit()
        return deleted

    def search_skills(self, agent_id, keyword) -> list[dict]:
        with self._cur() as cur:
            cur.execute("""
                SELECT * FROM sc_skills WHERE agent_id=%s AND enabled=TRUE
                AND (name ILIKE %s OR description ILIKE %s OR content ILIKE %s)
                ORDER BY priority DESC, name ASC
            """, (agent_id, f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"))
            return [_pg_row(dict(r)) for r in cur.fetchall()]

    # ── Profile ───────────────────────────────────────────

    def get_profile(self, user_id) -> dict:
        with self._cur() as cur:
            cur.execute("SELECT data FROM sc_profiles WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
            return dict(row["data"]) if row else {}

    def set_profile(self, user_id, data):
        with self._cur() as cur:
            cur.execute("""
                INSERT INTO sc_profiles (user_id,data,updated_at) VALUES(%s,%s,%s)
                ON CONFLICT(user_id) DO UPDATE SET data=EXCLUDED.data, updated_at=EXCLUDED.updated_at
            """, (user_id, json.dumps(data), _now()))
        self._conn.commit()

    def update_profile(self, user_id, key, value):
        p = self.get_profile(user_id)
        p[key] = value
        self.set_profile(user_id, p)

    # ── Plugin State ──────────────────────────────────────

    def get_plugin_state(self, plugin_name) -> dict:
        with self._cur() as cur:
            cur.execute("SELECT data FROM sc_plugin_states WHERE plugin_name=%s", (plugin_name,))
            row = cur.fetchone()
            return dict(row["data"]) if row else {}

    def set_plugin_state(self, plugin_name, data):
        with self._cur() as cur:
            cur.execute("""
                INSERT INTO sc_plugin_states (plugin_name,data,updated_at) VALUES(%s,%s,%s)
                ON CONFLICT(plugin_name) DO UPDATE SET data=EXCLUDED.data, updated_at=EXCLUDED.updated_at
            """, (plugin_name, json.dumps(data), _now()))
        self._conn.commit()

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
        if   dtype == "user":   self._import_user(data, merge)
        elif dtype == "agent":  self._import_agent(data, merge)
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
                            group=s.get("group") or s.get("grp"),
                            conditions=s.get("conditions",{}),
                            tags=s.get("tags",[]), metadata=s.get("metadata",{}))

    # ── Utils ─────────────────────────────────────────────

    def get_stats(self) -> dict:
        with self._cur() as cur:
            cur.execute("SELECT COUNT(DISTINCT user_id) as c FROM sc_messages"); u = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) as c FROM sc_messages"); m = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(DISTINCT agent_id) as c FROM sc_skills"); a = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) as c FROM sc_skills"); s = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) as c FROM sc_profiles"); p = cur.fetchone()["c"]
        return {"backend": "postgresql", "dsn": self._dsn,
                "total_users": u, "total_messages": m,
                "total_agents": a, "total_skills": s, "total_profiles": p}

    def list_users(self) -> list[str]:
        with self._cur() as cur:
            cur.execute("SELECT DISTINCT user_id FROM sc_messages")
            return [r["user_id"] for r in cur.fetchall()]

    def list_agents(self) -> list[str]:
        with self._cur() as cur:
            cur.execute("SELECT DISTINCT agent_id FROM sc_skills")
            return [r["agent_id"] for r in cur.fetchall()]

    def close(self):
        self._conn.close()


def _now() -> str: return datetime.now(timezone.utc).isoformat()

def _pg_row(d: dict) -> dict:
    if "grp" in d: d["group"] = d.pop("grp")
    return d
