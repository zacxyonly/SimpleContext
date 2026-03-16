"""
SQLite Storage v3
Default backend. Zero external dependencies.
"""

import sqlite3
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

from .base import BaseStorage


class SQLiteStorage(BaseStorage):

    def __init__(self, db_path: str = "./simplecontext.db"):
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_tables()

    def _init_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT    NOT NULL,
                role        TEXT    NOT NULL,
                content     TEXT    NOT NULL,
                tags        TEXT    DEFAULT '[]',
                metadata    TEXT    DEFAULT '{}',
                created_at  TEXT    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS skills (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id    TEXT    NOT NULL,
                name        TEXT    NOT NULL,
                description TEXT    DEFAULT '',
                content     TEXT    NOT NULL,
                extends     TEXT    DEFAULT NULL,
                enabled     INTEGER DEFAULT 1,
                priority    INTEGER DEFAULT 0,
                grp         TEXT    DEFAULT NULL,
                conditions  TEXT    DEFAULT '{}',
                tags        TEXT    DEFAULT '[]',
                metadata    TEXT    DEFAULT '{}',
                created_at  TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL,
                UNIQUE(agent_id, name)
            );
            CREATE TABLE IF NOT EXISTS profiles (
                user_id     TEXT    PRIMARY KEY,
                data        TEXT    DEFAULT '{}',
                updated_at  TEXT    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plugin_states (
                plugin_name TEXT    PRIMARY KEY,
                data        TEXT    DEFAULT '{}',
                updated_at  TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_user   ON messages(user_id);
            CREATE INDEX IF NOT EXISTS idx_skills_agent    ON skills(agent_id);
            CREATE INDEX IF NOT EXISTS idx_skills_enabled  ON skills(agent_id, enabled);
            CREATE INDEX IF NOT EXISTS idx_skills_group    ON skills(agent_id, grp);
        """)
        self._conn.commit()

    # ── Messages ──────────────────────────────────────────

    def save_message(self, user_id, role, content, tags=None, metadata=None) -> int:
        cur = self._conn.execute(
            "INSERT INTO messages (user_id,role,content,tags,metadata,created_at) VALUES(?,?,?,?,?,?)",
            (user_id, role, content, _j(tags or []), _j(metadata or {}), _now())
        )
        self._conn.commit()
        return cur.lastrowid

    def get_messages(self, user_id, limit=20, tags=None) -> list[dict]:
        if tags:
            cond = " OR ".join(["tags LIKE ?" for _ in tags])
            params = [user_id] + [f'%"{t}"%' for t in tags] + [limit]
            rows = self._conn.execute(
                f"SELECT * FROM messages WHERE user_id=? AND ({cond}) ORDER BY id DESC LIMIT ?", params
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)
            ).fetchall()
        return [_row(r) for r in reversed(rows)]

    def count_messages(self, user_id) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM messages WHERE user_id=?", (user_id,)
        ).fetchone()[0]

    def delete_messages(self, user_id, tags=None):
        if tags:
            cond = " OR ".join(["tags LIKE ?" for _ in tags])
            self._conn.execute(
                f"DELETE FROM messages WHERE user_id=? AND ({cond})",
                [user_id] + [f'%"{t}"%' for t in tags]
            )
        else:
            self._conn.execute("DELETE FROM messages WHERE user_id=?", (user_id,))
        self._conn.commit()

    def search_messages(self, user_id, keyword, limit=5) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE user_id=? AND content LIKE ? ORDER BY id DESC LIMIT ?",
            (user_id, f"%{keyword}%", limit)
        ).fetchall()
        return [_row(r) for r in rows]

    # ── Skills ────────────────────────────────────────────

    def save_skill(self, agent_id, name, content, description="", extends=None,
                   enabled=True, priority=0, group=None, conditions=None,
                   tags=None, metadata=None):
        now = _now()
        self._conn.execute("""
            INSERT INTO skills
                (agent_id,name,description,content,extends,enabled,priority,grp,conditions,tags,metadata,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(agent_id,name) DO UPDATE SET
                description=excluded.description, content=excluded.content,
                extends=excluded.extends, enabled=excluded.enabled,
                priority=excluded.priority, grp=excluded.grp,
                conditions=excluded.conditions, tags=excluded.tags,
                metadata=excluded.metadata, updated_at=excluded.updated_at
        """, (agent_id, name, description, content, extends, 1 if enabled else 0,
              priority, group, _j(conditions or {}), _j(tags or []),
              _j(metadata or {}), now, now))
        self._conn.commit()

    def get_skill(self, agent_id, name) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM skills WHERE agent_id=? AND name=?", (agent_id, name)
        ).fetchone()
        return _row(row) if row else None

    def get_skills(self, agent_id, enabled_only=True, group=None, tags=None) -> list[dict]:
        query = "SELECT * FROM skills WHERE agent_id=?"
        params: list = [agent_id]
        if enabled_only:
            query += " AND enabled=1"
        if group is not None:
            query += " AND grp=?"
            params.append(group)
        if tags:
            cond = " OR ".join(["tags LIKE ?" for _ in tags])
            query += f" AND ({cond})"
            params += [f'%"{t}"%' for t in tags]
        query += " ORDER BY priority DESC, name ASC"
        return [_row(r) for r in self._conn.execute(query, params).fetchall()]

    def delete_skill(self, agent_id, name) -> bool:
        cur = self._conn.execute(
            "DELETE FROM skills WHERE agent_id=? AND name=?", (agent_id, name)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def search_skills(self, agent_id, keyword) -> list[dict]:
        rows = self._conn.execute("""
            SELECT * FROM skills WHERE agent_id=?
            AND (name LIKE ? OR description LIKE ? OR content LIKE ?) AND enabled=1
            ORDER BY priority DESC, name ASC
        """, (agent_id, f"%{keyword}%", f"%{keyword}%", f"%{keyword}%")).fetchall()
        return [_row(r) for r in rows]

    # ── Profile ───────────────────────────────────────────

    def get_profile(self, user_id) -> dict:
        row = self._conn.execute(
            "SELECT data FROM profiles WHERE user_id=?", (user_id,)
        ).fetchone()
        return json.loads(row["data"]) if row else {}

    def set_profile(self, user_id, data):
        self._conn.execute("""
            INSERT INTO profiles (user_id,data,updated_at) VALUES(?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
        """, (user_id, _j(data), _now()))
        self._conn.commit()

    def update_profile(self, user_id, key, value):
        p = self.get_profile(user_id)
        p[key] = value
        self.set_profile(user_id, p)

    # ── Plugin State ──────────────────────────────────────

    def get_plugin_state(self, plugin_name) -> dict:
        row = self._conn.execute(
            "SELECT data FROM plugin_states WHERE plugin_name=?", (plugin_name,)
        ).fetchone()
        return json.loads(row["data"]) if row else {}

    def set_plugin_state(self, plugin_name, data):
        self._conn.execute("""
            INSERT INTO plugin_states (plugin_name,data,updated_at) VALUES(?,?,?)
            ON CONFLICT(plugin_name) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
        """, (plugin_name, _j(data), _now()))
        self._conn.commit()

    def update_plugin_state(self, plugin_name, key, value):
        s = self.get_plugin_state(plugin_name)
        s[key] = value
        self.set_plugin_state(plugin_name, s)

    # ── Export / Import ───────────────────────────────────

    def export_user(self, user_id) -> dict:
        self._ensure_nodes()
        # Export context_nodes (v4) + messages (v3 compat)
        nodes = self.get_nodes(user_id, status=None, limit=999999)
        return {
            "type": "user", "user_id": user_id, "exported_at": _now(),
            "version": "4.0",
            "profile": self.get_profile(user_id),
            "messages": self.get_messages(user_id, limit=999999),
            "nodes": [n.to_dict() for n in nodes],
        }

    def export_agent(self, agent_id) -> dict:
        return {
            "type": "agent", "agent_id": agent_id, "exported_at": _now(),
            "version": "4.0",
            "skills": self.get_skills(agent_id, enabled_only=False),
        }

    def export_all(self) -> dict:
        return {
            "type": "full", "exported_at": _now(), "version": "4.0",
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
        if not merge:
            self.delete_messages(uid)
            self.delete_nodes(uid)
        if data.get("profile"):
            prof = {**self.get_profile(uid), **data["profile"]} if merge else data["profile"]
            self.set_profile(uid, prof)
        # Import v3 messages (backward compat)
        for m in data.get("messages", []):
            self.save_message(uid, m["role"], m["content"],
                              m.get("tags", []), m.get("metadata", {}))
        # Import v4 context_nodes
        for nd in data.get("nodes", []):
            try:
                from ..context.node import ContextNode
                node = ContextNode.from_dict(nd)
                self.save_node(node)
            except Exception:
                pass  # skip invalid nodes saat import

    def _import_agent(self, data, merge):
        aid = data["agent_id"]
        if not merge:
            for s in self.get_skills(aid, enabled_only=False):
                self.delete_skill(aid, s["name"])
        for s in data.get("skills", []):
            self.save_skill(aid, s["name"], s["content"],
                            description=s.get("description",""),
                            extends=s.get("extends"),
                            enabled=bool(s.get("enabled",1)),
                            priority=s.get("priority",0),
                            group=s.get("grp") or s.get("group"),
                            conditions=s.get("conditions",{}),
                            tags=s.get("tags",[]),
                            metadata=s.get("metadata",{}))

    # ── Utils ─────────────────────────────────────────────

    def get_stats(self) -> dict:
        return {
            "backend": "sqlite", "db_path": self.db_path,
            "total_users":    self._conn.execute("SELECT COUNT(DISTINCT user_id) FROM messages").fetchone()[0],
            "total_messages": self._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
            "total_agents":   self._conn.execute("SELECT COUNT(DISTINCT agent_id) FROM skills").fetchone()[0],
            "total_skills":   self._conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0],
            "total_profiles": self._conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0],
        }

    def list_users(self) -> list[str]:
        self._ensure_nodes()
        # Gabungkan dari messages (v3) dan context_nodes (v4)
        v3 = {r[0] for r in self._conn.execute("SELECT DISTINCT user_id FROM messages").fetchall()}
        v4 = {r[0] for r in self._conn.execute("SELECT DISTINCT user_id FROM context_nodes").fetchall()}
        return sorted(v3 | v4)
    def list_agents(self) -> list[str]: return [r[0] for r in self._conn.execute("SELECT DISTINCT agent_id FROM skills").fetchall()]
    def close(self): self._conn.close()


    # ── Context Nodes (v4) ────────────────────────────────

    def _init_nodes_table(self):
        """Buat tabel context_nodes dan indexes. Dipanggil lazy saat pertama kali dibutuhkan."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS context_nodes (
                id          TEXT    PRIMARY KEY,
                user_id     TEXT    NOT NULL,
                path        TEXT    NOT NULL,
                tier        TEXT    NOT NULL,
                kind        TEXT    NOT NULL,
                content     TEXT    NOT NULL,
                created_at  TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL,
                importance  REAL    DEFAULT 0.5,
                confidence  REAL    DEFAULT 1.0,
                source      TEXT    DEFAULT 'user',
                status      TEXT    DEFAULT 'active',
                supersedes  TEXT    DEFAULT NULL,
                tags        TEXT    DEFAULT '[]',
                metadata    TEXT    DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_user       ON context_nodes(user_id);
            CREATE INDEX IF NOT EXISTS idx_nodes_path       ON context_nodes(path);
            CREATE INDEX IF NOT EXISTS idx_nodes_tier       ON context_nodes(user_id, tier);
            CREATE INDEX IF NOT EXISTS idx_nodes_status     ON context_nodes(user_id, status);
            CREATE INDEX IF NOT EXISTS idx_nodes_updated    ON context_nodes(updated_at);
            CREATE INDEX IF NOT EXISTS idx_nodes_importance ON context_nodes(user_id, importance DESC);
        """)
        self._conn.commit()
        self._nodes_initialized = True

    def _ensure_nodes(self):
        if not getattr(self, "_nodes_initialized", False):
            self._init_nodes_table()

    def save_node(self, node) -> None:
        self._ensure_nodes()
        d = node.to_dict()
        self._conn.execute("""
            INSERT INTO context_nodes
                (id,user_id,path,tier,kind,content,created_at,updated_at,
                 importance,confidence,source,status,supersedes,tags,metadata)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                content    = excluded.content,
                updated_at = excluded.updated_at,
                importance = excluded.importance,
                confidence = excluded.confidence,
                status     = excluded.status,
                supersedes = excluded.supersedes,
                tags       = excluded.tags,
                metadata   = excluded.metadata
        """, (d["id"], d["user_id"], d["path"], d["tier"], d["kind"], d["content"],
              d["created_at"], d["updated_at"], d["importance"], d["confidence"],
              d["source"], d["status"], d["supersedes"], d["tags"], d["metadata"]))
        self._conn.commit()

    def get_node(self, node_id: str):
        self._ensure_nodes()
        row = self._conn.execute(
            "SELECT * FROM context_nodes WHERE id=?", (node_id,)
        ).fetchone()
        if not row: return None
        from ..context.node import ContextNode
        return ContextNode.from_dict(dict(row))

    def get_nodes(self, user_id: str, tier: str = None, kind: str = None,
                  status: str = "active", limit: int = 100,
                  order: str = "importance") -> list:
        """
        order="importance"      → importance DESC, updated_at DESC (untuk retrieval)
        order="chronological"   → created_at ASC (untuk percakapan/history)
        """
        self._ensure_nodes()
        query  = "SELECT * FROM context_nodes WHERE user_id=?"
        params = [user_id]
        if tier:   query += " AND tier=?";   params.append(tier)
        if kind:   query += " AND kind=?";   params.append(kind)
        if status: query += " AND status=?"; params.append(status)
        if order == "chronological":
            query += " ORDER BY created_at ASC LIMIT ?"
        else:
            query += " ORDER BY importance DESC, updated_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        from ..context.node import ContextNode
        return [ContextNode.from_dict(dict(r)) for r in rows]

    def update_node_status(self, node_id: str, status: str) -> None:
        self._ensure_nodes()
        self._conn.execute(
            "UPDATE context_nodes SET status=?, updated_at=? WHERE id=?",
            (status, _now(), node_id)
        )
        self._conn.commit()

    def update_node_importance(self, node_id: str, importance: float) -> None:
        self._ensure_nodes()
        importance = max(0.0, min(1.0, importance))
        self._conn.execute(
            "UPDATE context_nodes SET importance=?, updated_at=? WHERE id=?",
            (importance, _now(), node_id)
        )
        self._conn.commit()

    def search_nodes(self, user_id: str, keyword: str,
                     tier: str = None, limit: int = 20) -> list:
        self._ensure_nodes()
        query  = "SELECT * FROM context_nodes WHERE user_id=? AND status='active' AND content LIKE ?"
        params = [user_id, f"%{keyword}%"]
        if tier: query += " AND tier=?"; params.append(tier)
        query += " ORDER BY importance DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        from ..context.node import ContextNode
        return [ContextNode.from_dict(dict(r)) for r in rows]

    def get_nodes_by_path_prefix(self, user_id: str, prefix: str) -> list:
        self._ensure_nodes()
        rows = self._conn.execute(
            "SELECT * FROM context_nodes WHERE user_id=? AND path LIKE ? AND status='active' ORDER BY importance DESC",
            (user_id, f"{prefix}%")
        ).fetchall()
        from ..context.node import ContextNode
        return [ContextNode.from_dict(dict(r)) for r in rows]

    def delete_nodes(self, user_id: str, status: str = None) -> None:
        self._ensure_nodes()
        if status:
            self._conn.execute(
                "DELETE FROM context_nodes WHERE user_id=? AND status=?", (user_id, status)
            )
        else:
            self._conn.execute("DELETE FROM context_nodes WHERE user_id=?", (user_id,))
        self._conn.commit()

    def count_nodes(self, user_id: str, tier: str = None, status: str = "active") -> int:
        self._ensure_nodes()
        query  = "SELECT COUNT(*) FROM context_nodes WHERE user_id=?"
        params = [user_id]
        if tier:   query += " AND tier=?";   params.append(tier)
        if status: query += " AND status=?"; params.append(status)
        return self._conn.execute(query, params).fetchone()[0]


# ── Helpers ───────────────────────────────────────────────

def _now() -> str: return datetime.now(timezone.utc).isoformat()
def _j(obj) -> str: return json.dumps(obj, ensure_ascii=False)

def _row(row) -> dict:
    d = dict(row)
    for f in ("tags", "metadata", "conditions", "data"):
        if f in d and isinstance(d[f], str):
            try: d[f] = json.loads(d[f])
            except: pass
    if "enabled" in d: d["enabled"] = bool(d["enabled"])
    if "grp" in d: d["group"] = d.pop("grp")
    return d
