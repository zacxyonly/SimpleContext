"""
SimpleContext v4 Core
Universal AI Brain dengan tiered memory, context planning, dan smart retrieval.
Fully backward compatible dengan v3 API.
"""

import logging
from typing import Optional

from .config import Config
from .storage import create_storage
from .storage.base import BaseStorage
from .plugins.loader import PluginLoader
from .plugins.base import BasePlugin
from .agent.registry import AgentRegistry
from .agent.router import AgentRouter, RouteResult
from .memory import Memory, TieredMemory
from .skills import Skills
from .io.porter import Porter
from .context.node import ContextNode
from .context.planner import ContextPlanner, RetrievalPlan
from .context.engine import ContextEngine
from .context.builder import PromptBuilder
from .context.processor import MemoryProcessor, ProcessTurn
from .enums import Tier, NodeKind

logger = logging.getLogger(__name__)


class SimpleContext:
    """
    SimpleContext v4 — Universal AI Brain.

    Dua mode pakai:

    Mode v3 (backward compat, simple):
        result   = sc.router.route(user_id, message)
        messages = sc.prepare_messages(user_id, message, result)
        reply    = your_llm(messages)
        reply    = sc.process_response(user_id, message, reply, result)

    Mode v4 (full context engine):
        plan     = sc.planner.plan(message, user_id, profile)
        nodes    = sc.engine.retrieve(plan)
        messages = sc.builder.build(system, nodes, message)
        reply    = your_llm(messages)
        turn     = ProcessTurn(user_id, message, reply, used_nodes=nodes)
        sc.processor.process(turn)
    """

    def __init__(self, config_path: str = None, **overrides):
        self._config = Config.load(config_path) if config_path else Config.default()
        for key, val in overrides.items():
            self._config.set(key.replace("__", "."), val)

        # Storage
        self._storage: BaseStorage = create_storage(self._config)

        # Plugins
        plugin_folder  = self._config.get("plugins.folder", "./plugins")
        plugin_configs = {
            k: v for k, v in self._config.section("plugins").items()
            if k not in ("enabled", "folder") and isinstance(v, dict)
        }
        self._plugins = PluginLoader(plugin_folder, self._storage, plugin_configs)
        if self._config.get("plugins.enabled", True):
            self._plugins.load()

        # Agent registry & router
        agents_folder = self._config.get("agents.folder", "./agents")
        hot_reload    = self._config.get("agents.hot_reload", True)
        self._registry = AgentRegistry(agents_folder, hot_reload=hot_reload)
        self._registry.load()
        self._sync_agent_skills()

        default_agent = self._config.get("agents.default", "general")
        self._router  = AgentRouter(
            self._registry, self._storage, self._plugins, default_agent
        )

        # v4: context engine components
        ttl_cfg    = self._config.section("memory").get("ttl_hours", {})
        debug_mode = self._config.get("debug.retrieval", False)
        self._engine    = ContextEngine(self._storage, ttl_cfg, debug=debug_mode)
        self._planner   = ContextPlanner()
        self._builder   = PromptBuilder()
        self._processor = MemoryProcessor(self._storage)

        # Memory cache (FIX #4 dari v3.1)
        self._memory_cache: dict[str, Memory] = {}

        # Porter (export/import)
        self._porter = Porter(
            self._storage, self._plugins,
            self._config.get("export.folder", "./exports")
        )
        self._porter._memory_cache_ref = self._memory_cache

        logger.info(f"✅ SimpleContext v4 ready — {self._storage}")

    def _sync_agent_skills(self):
        """Sync skills dari agent YAML ke storage."""
        for agent in self._registry.all():
            if agent.skills:
                self.skills(agent.name).sync_from_agent(agent.skills)

    # ── v3 High-level API (backward compat) ──────────────

    @property
    def router(self) -> AgentRouter:
        return self._router

    def prepare_messages(self, user_id, message: str,
                         route_result: RouteResult,
                         history_limit: int = None) -> list[dict]:
        """
        v3 compat: build messages array untuk LLM.
        Pesan user BELUM disimpan ke memori di sini.
        """
        mem     = self.memory(user_id)
        history = mem.get_for_llm(limit=history_limit)
        system  = route_result.system_prompt
        profile = mem.get_profile()
        display = {k: v for k, v in profile.items()
                   if not k.startswith("_") and k != "preferred_agent"}
        if display:
            lines   = "\n".join(f"- {k}: {v}" for k, v in display.items())
            system += f"\n\nPROFIL USER:\n{lines}"

        messages = [{"role": "system", "content": system}]
        messages.extend(history)
        messages.append({"role": "user", "content": message})
        messages = self._plugins.fire_before_llm(
            str(user_id), route_result.agent_id, messages
        )
        return messages

    def process_response(self, user_id, message: str,
                         reply: str, route_result: RouteResult,
                         chain_from: str = None) -> str:
        """
        v3 compat: proses response LLM, fire hooks, simpan ke memori.
        """
        reply = self._plugins.fire_after_llm(
            str(user_id), route_result.agent_id, reply
        )
        mem      = self.memory(user_id)
        msg_meta = {"agent_id": route_result.agent_id}
        if chain_from:
            msg_meta["chained_from"] = chain_from
        # Invalidate cache setelah simpan — agar retrieval berikutnya fresh
        self._engine.invalidate_cache(str(user_id))
        mem.add_user(message, metadata=msg_meta)
        mem.add_assistant(reply, metadata={"agent_id": route_result.agent_id,
                                           **({"chained_from": chain_from} if chain_from else {})})
        return reply

    # ── v4 Context Engine API ─────────────────────────────

    @property
    def engine(self) -> ContextEngine:
        """v4: akses ContextEngine untuk smart retrieval."""
        return self._engine

    @property
    def planner(self) -> ContextPlanner:
        """v4: akses ContextPlanner untuk buat RetrievalPlan."""
        return self._planner

    @property
    def builder(self) -> PromptBuilder:
        """v4: akses PromptBuilder untuk build messages."""
        return self._builder

    @property
    def processor(self) -> MemoryProcessor:
        """v4: akses MemoryProcessor untuk proses turn."""
        return self._processor

    def context(self, user_id) -> TieredMemory:
        """
        v4: akses TieredMemory untuk user tertentu.
        Berbeda dari .memory() yang mengembalikan v3 compat facade.
        """
        return TieredMemory(self._storage, str(user_id))

    def chat(self, user_id, message: str,
             agent_id: str = None,
             history_limit: int = None) -> "ChatContext":
        """
        v4 high-level: satu method untuk semua — route + plan + retrieve + build.
        Return ChatContext yang siap dikirim ke LLM.

        Contoh:
            ctx      = sc.chat(user_id, message)
            reply    = your_llm(ctx.messages)
            ctx.save(reply)   # simpan ke memori
        """
        return ChatContext(self, user_id, message, agent_id, history_limit)

    # ── Memory & Skills ───────────────────────────────────

    def memory(self, user_id) -> Memory:
        """v3 compat: ambil Memory facade untuk user tertentu."""
        uid = str(user_id)
        if uid not in self._memory_cache:
            comp  = self._config.section("memory").get("compression", {})
            limit = self._config.get("memory.default_limit", 20)
            self._memory_cache[uid] = Memory(
                self._storage, self._plugins, uid, limit, comp
            )
        return self._memory_cache[uid]

    def skills(self, agent_id: str) -> Skills:
        depth = self._config.get("skills.inheritance_depth", 5)
        return Skills(self._storage, self._plugins, str(agent_id), depth)

    # ── Export / Import ───────────────────────────────────

    def export(self) -> Porter:
        return self._porter

    # ── Plugin Management ─────────────────────────────────

    def use(self, plugin: BasePlugin) -> "SimpleContext":
        self._plugins.register(plugin)
        return self

    # ── Agent Management ──────────────────────────────────

    def register_agent(self, agent_def) -> "SimpleContext":
        self._registry.register(agent_def)
        if agent_def.skills:
            self.skills(agent_def.name).sync_from_agent(agent_def.skills)
        return self

    def reload_agents(self):
        self._registry.load()
        self._sync_agent_skills()

    def apply_decay(self, user_id=None):
        """
        Terapkan importance decay.
        user_id=None → terapkan ke semua user.
        Panggil periodik, misal setiap hari atau setiap sesi baru.
        """
        users = [str(user_id)] if user_id else self._storage.list_users()
        for uid in users:
            self._processor.apply_decay(uid)

    def enable_debug(self, enabled: bool = True):
        """Toggle retrieval debug mode (log detail pipeline ke console)."""
        self._engine.set_debug(enabled)

    # ── Info & Stats ──────────────────────────────────────

    def stats(self) -> dict:
        base = self._storage.get_stats()
        return {
            **base,
            "agents":  self._registry.summary(),
            "plugins": self._plugins.summary(),
            "config": {
                "storage_backend": self._config.get("storage.backend"),
                "agents_folder":   self._config.get("agents.folder"),
                "hot_reload":      self._config.get("agents.hot_reload"),
                "memory_limit":    self._config.get("memory.default_limit"),
                "memory_cache":    len(self._memory_cache),
            },
        }

    def list_users(self)  -> list[str]: return self._storage.list_users()
    def list_agents(self) -> list[str]: return self._storage.list_agents()
    def config(self)      -> Config:    return self._config

    # ── Lifecycle ─────────────────────────────────────────

    def close(self):
        self._plugins.teardown()
        self._storage.close()
        self._memory_cache.clear()

    def __enter__(self): return self
    def __exit__(self, *a): self.close()

    def __repr__(self):
        s = self._storage.get_stats()
        return (f"<SimpleContext v4 backend={s.get('backend')!r} "
                f"agents={len(self._registry.names())} "
                f"users={s.get('total_users')} "
                f"plugins={len(self._plugins.all())}>")


# ── ChatContext (v4 high-level helper) ────────────────────

class ChatContext:
    """
    Helper untuk alur chat lengkap v4.

    Contoh:
        ctx   = sc.chat(user_id, message)
        reply = your_llm(ctx.messages)
        ctx.save(reply)
    """

    def __init__(self, sc: SimpleContext, user_id, message: str,
                 agent_id: str = None, history_limit: int = None):
        self._sc       = sc
        self._user_id  = str(user_id)
        self._message  = message
        self._used_nodes: list[ContextNode] = []

        # Route
        self._route_result = sc.router.route(self._user_id, message)
        agent_id = agent_id or self._route_result.agent_id

        # Plan + retrieve
        profile = sc.memory(user_id).get_profile()
        plan    = sc.planner.plan(message, self._user_id, profile, agent_id)
        self._used_nodes = sc.engine.retrieve(plan)

        # Build messages (v4 path: pakai ContextEngine + PromptBuilder)
        # Ambil history dari working tier (untuk compat)
        history = sc.memory(user_id).get_for_llm(limit=history_limit)

        self.messages = sc.builder.build(
            system_base  = self._route_result.system_prompt,
            nodes        = self._used_nodes,
            user_message = message,
            history      = history,
            profile      = profile,
        )

        # Fire before_llm hooks
        self.messages = sc._plugins.fire_before_llm(
            self._user_id, agent_id, self.messages
        )

    def save(self, reply: str, chain_from: str = None) -> str:
        """
        Simpan turn ke memori via MemoryProcessor.
        Return reply yang sudah diproses after_llm hooks.
        """
        # Fire after_llm hooks
        reply = self._sc._plugins.fire_after_llm(
            self._user_id, self._route_result.agent_id, reply
        )

        # Proses turn via MemoryProcessor (v4 path)
        turn = ProcessTurn(
            user_id            = self._user_id,
            user_message       = self._message,
            assistant_response = reply,
            agent_id           = self._route_result.agent_id,
            used_nodes         = self._used_nodes,
            runtime_state      = {"intent": self._route_result.agent_id},
        )
        self._sc.processor.process(turn)
        return reply

    @property
    def agent_id(self) -> str:
        return self._route_result.agent_id

    @property
    def personality_level(self) -> str:
        return self._route_result.personality_level

    def should_chain(self, user_message: str = None) -> Optional[dict]:
        return self._route_result.should_chain(user_message or self._message)
