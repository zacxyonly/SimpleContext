"""
AgentRegistry
Load semua agent dari folder agents/, cache, dan hot-reload otomatis.
"""

import os
import logging
from typing import Optional
from .schema import AgentDef

logger = logging.getLogger(__name__)


class AgentRegistry:
    """
    Menyimpan semua AgentDef yang diload dari folder.
    Hot-reload: setiap akses cek apakah file berubah,
    kalau berubah reload agent tersebut saja.
    """

    def __init__(self, agents_folder: str, hot_reload: bool = True):
        self._folder     = agents_folder
        self._hot_reload = hot_reload
        self._agents: dict[str, AgentDef]   = {}   # name → AgentDef
        self._mtimes: dict[str, float]       = {}   # path → mtime
        self._path_to_name: dict[str, str]   = {}   # path → agent name
        self._loaded = False

    def load(self):
        """Load semua agent dari folder saat startup."""
        if not os.path.isdir(self._folder):
            logger.warning(f"Agents folder tidak ditemukan: {self._folder}")
            self._loaded = True
            return

        for filename in sorted(os.listdir(self._folder)):
            if not filename.endswith((".yaml", ".yml", ".json")):
                continue
            path = os.path.join(self._folder, filename)
            self._load_file(path)

        self._loaded = True
        logger.info(f"✅ {len(self._agents)} agent(s) loaded dari '{self._folder}'")

    def register(self, agent_def: AgentDef):
        """Register agent secara manual (tanpa file)."""
        self._agents[agent_def.name] = agent_def
        logger.info(f"✅ Agent registered: {agent_def.name}")

    def get(self, name: str) -> Optional[AgentDef]:
        """Ambil agent berdasarkan nama. Hot-reload jika ada perubahan."""
        if self._hot_reload:
            self._check_reload()
        return self._agents.get(name)

    def all(self) -> list[AgentDef]:
        """Ambil semua agent. Hot-reload jika ada perubahan."""
        if self._hot_reload:
            self._check_reload()
        return list(self._agents.values())

    def names(self) -> list[str]:
        return list(self._agents.keys())

    def exists(self, name: str) -> bool:
        return self.get(name) is not None

    # ── Hot Reload ────────────────────────────────────────

    def _check_reload(self):
        """Cek semua file agent — reload yang berubah."""
        if not os.path.isdir(self._folder):
            return

        current_files = {
            os.path.join(self._folder, f)
            for f in os.listdir(self._folder)
            if f.endswith((".yaml", ".yml", ".json"))
        }

        # File baru atau berubah
        for path in current_files:
            mtime = os.path.getmtime(path)
            if path not in self._mtimes or self._mtimes[path] != mtime:
                self._load_file(path, is_reload=True)

        # File yang dihapus
        deleted = set(self._mtimes.keys()) - current_files
        for path in deleted:
            name = self._path_to_name.pop(path, None)
            if name and name in self._agents:
                del self._agents[name]
                logger.info(f"  ✗ Agent unloaded (file dihapus): {name}")
            self._mtimes.pop(path, None)

    def _load_file(self, path: str, is_reload: bool = False):
        try:
            agent = AgentDef.from_file(path)
            self._agents[agent.name]    = agent
            self._mtimes[path]          = os.path.getmtime(path)
            self._path_to_name[path]    = agent.name
            label = "reloaded" if is_reload else "loaded"
            logger.info(f"  {'↺' if is_reload else '+'} Agent {label}: {agent.name}")
        except Exception as e:
            logger.warning(f"  ⚠️  Gagal load agent '{os.path.basename(path)}': {e}")

    def summary(self) -> dict:
        agents = self.all()
        return {
            "folder":     self._folder,
            "hot_reload": self._hot_reload,
            "total":      len(agents),
            "agents": [
                {"name": a.name, "description": a.description,
                 "keywords": a.keywords[:5], "priority": a.priority}
                for a in agents
            ],
        }

    def __repr__(self):
        return f"<AgentRegistry agents={len(self._agents)} folder={self._folder!r} hot_reload={self._hot_reload}>"
