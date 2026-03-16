"""Porter v3 — Export & Import"""

import json, os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..storage.base import BaseStorage
    from ..plugins.loader import PluginLoader


class Porter:
    def __init__(self, storage, plugins, export_folder="./exports"):
        self._storage = storage
        self._plugins = plugins
        self.export_folder = export_folder

    def export_user(self, user_id, path=None) -> str:
        data = self._plugins.fire_export(self._storage.export_user(user_id))
        return self._write(data, path or self._auto_path(f"user_{user_id}"))

    def export_agent(self, agent_id, path=None) -> str:
        data = self._plugins.fire_export(self._storage.export_agent(agent_id))
        return self._write(data, path or self._auto_path(f"agent_{agent_id}"))

    def export_all(self, path=None) -> str:
        data = self._plugins.fire_export(self._storage.export_all())
        return self._write(data, path or self._auto_path("full_backup"))

    def import_file(self, path, merge=True):
        if not os.path.exists(path):
            raise FileNotFoundError(f"File tidak ditemukan: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data = self._plugins.fire_import(data)
        self._storage.import_data(data, merge=merge)
        # Invalidate memory cache agar counter lokal tidak stale
        if hasattr(self, "_memory_cache_ref") and self._memory_cache_ref:
            self._memory_cache_ref.clear()

    def import_dict(self, data, merge=True):
        data = self._plugins.fire_import(data)
        self._storage.import_data(data, merge=merge)
        if hasattr(self, "_memory_cache_ref") and self._memory_cache_ref:
            self._memory_cache_ref.clear()

    def preview(self, path) -> dict:
        if not os.path.exists(path):
            raise FileNotFoundError(f"File tidak ditemukan: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        dtype  = data.get("type", "unknown")
        result = {"type": dtype, "exported_at": data.get("exported_at"), "version": data.get("version")}
        if dtype == "user":
            # v4: count dari nodes, fallback ke messages (v3 compat)
            nodes_count    = len(data.get("nodes", []))
            messages_count = len(data.get("messages", []))
            total = nodes_count if nodes_count > 0 else messages_count
            result.update({
                "user_id":        data.get("user_id"),
                "messages_count": total,
                "profile_keys":   list(data.get("profile", {}).keys()),
                "nodes_count":    nodes_count,
                "version":        data.get("version", "3.0"),
            })
        elif dtype == "agent":
            result.update({"agent_id": data.get("agent_id"), "skills_count": len(data.get("skills",[])), "skill_names": [s["name"] for s in data.get("skills",[])]})
        elif dtype == "full":
            result.update({"users_count": len(data.get("users",{})), "agents_count": len(data.get("agents",{})), "user_ids": list(data.get("users",{}).keys()), "agent_ids": list(data.get("agents",{}).keys())})
        return result

    def list_exports(self) -> list[dict]:
        if not os.path.isdir(self.export_folder):
            return []
        files = []
        for fname in sorted(os.listdir(self.export_folder)):
            if not fname.endswith(".json"): continue
            fpath = os.path.join(self.export_folder, fname)
            stat  = os.stat(fpath)
            files.append({"filename": fname, "path": fpath, "size_kb": round(stat.st_size/1024,2), "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat()})
        return files

    def _write(self, data, path) -> str:
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return path

    def _auto_path(self, prefix) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return os.path.join(self.export_folder, f"{prefix}_{ts}.json")
