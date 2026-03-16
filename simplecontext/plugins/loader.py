"""
Plugin Loader v3
- Auto-scan folder
- Dependency resolver
- State injection
- Semua hooks v3 (termasuk on_before_llm, on_after_llm)
"""

import os
import importlib.util
import logging
from typing import Optional, TYPE_CHECKING

from .base import BasePlugin, AppCommandContext
from .state import PluginState

if TYPE_CHECKING:
    from ..storage.base import BaseStorage

logger = logging.getLogger(__name__)


class PluginLoader:

    def __init__(self, plugin_folder: str, storage: "BaseStorage",
                 plugin_configs: dict = None):
        self.plugin_folder  = plugin_folder
        self._storage       = storage
        self._plugin_configs = plugin_configs or {}
        self._plugins: list[BasePlugin] = []
        self._loaded = False

    def load(self):
        """Scan folder dan load semua plugin yang valid, urut berdasarkan dependency."""
        if not os.path.isdir(self.plugin_folder):
            logger.debug(f"Plugin folder tidak ditemukan: {self.plugin_folder}")
            self._loaded = True
            return

        candidates: list[BasePlugin] = []

        for filename in sorted(os.listdir(self.plugin_folder)):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue
            path = os.path.join(self.plugin_folder, filename)
            self._load_file(path, candidates)

        # Resolve dependency order
        ordered = self._resolve_dependencies(candidates)
        self._plugins.extend(ordered)
        self._loaded = True
        logger.info(f"✅ {len(self._plugins)} plugin(s) loaded dari '{self.plugin_folder}'")

    def _load_file(self, path: str, candidates: list):
        module_name = os.path.splitext(os.path.basename(path))[0]
        try:
            spec   = importlib.util.spec_from_file_location(f"sc_plugin_{module_name}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type)
                        and issubclass(attr, BasePlugin)
                        and attr is not BasePlugin
                        and getattr(attr, "name", "")):

                    cfg      = self._plugin_configs.get(attr.name, {})
                    instance = attr(config=cfg)
                    # Inject state sebelum setup dipanggil ulang
                    self._inject_state(instance)

                    if instance.enabled:
                        candidates.append(instance)
                        logger.info(f"  ✓ Candidate: {attr.name} v{attr.version} deps={attr.depends_on}")
                    else:
                        logger.info(f"  ✗ Disabled: {attr.name}")

        except Exception as e:
            logger.warning(f"  ⚠️  Gagal load plugin '{module_name}': {e}")

    def _inject_state(self, instance: BasePlugin):
        """Inject PluginState dan app_info ke instance sebelum setup()"""
        if instance.name:
            instance.state    = PluginState(self._storage, instance.name)
            instance.app_info = {}   # host bisa isi ini via loader.set_app_info()

    def _resolve_dependencies(self, candidates: list[BasePlugin]) -> list[BasePlugin]:
        """
        Topological sort berdasarkan depends_on.
        Plugin yang jadi dependency diload lebih dulu.
        """
        name_map  = {p.name: p for p in candidates}
        resolved: list[BasePlugin] = []
        visited:  set[str] = set()

        def visit(name: str, chain: list[str]):
            if name in visited:
                return
            if name in chain:
                raise RuntimeError(
                    f"Circular dependency terdeteksi: {' → '.join(chain + [name])}"
                )
            plugin = name_map.get(name)
            if not plugin:
                raise RuntimeError(
                    f"Plugin dependency '{name}' tidak ditemukan. "
                    f"Plugin yang tersedia: {list(name_map.keys())}"
                )
            for dep in plugin.depends_on:
                visit(dep, chain + [name])
            visited.add(name)
            resolved.append(plugin)

        for p in candidates:
            visit(p.name, [])

        return resolved

    def register(self, instance: BasePlugin) -> "PluginLoader":
        """Register plugin secara manual (tanpa file)."""
        if not isinstance(instance, BasePlugin):
            raise TypeError("Plugin harus merupakan instance dari BasePlugin")

        # Inject state
        self._inject_state(instance)

        # Cek dependency
        registered_names = {p.name for p in self._plugins}
        for dep in instance.depends_on:
            if dep not in registered_names:
                raise RuntimeError(
                    f"Plugin '{instance.name}' membutuhkan '{dep}' yang belum diregister. "
                    f"Register '{dep}' terlebih dahulu."
                )

        if instance.enabled:
            self._plugins.append(instance)
            logger.info(f"✅ Plugin registered manually: {instance.name}")
        return self

    def unregister(self, plugin_name: str) -> bool:
        before = len(self._plugins)
        # Cek apakah ada plugin lain yang bergantung padanya
        dependents = [p.name for p in self._plugins if plugin_name in p.depends_on]
        if dependents:
            raise RuntimeError(
                f"Tidak bisa unregister '{plugin_name}': "
                f"plugin {dependents} masih bergantung padanya."
            )
        self._plugins = [p for p in self._plugins if p.name != plugin_name]
        return len(self._plugins) < before

    def get(self, name: str) -> Optional[BasePlugin]:
        for p in self._plugins:
            if p.name == name:
                return p
        return None

    def all(self) -> list[BasePlugin]: return list(self._plugins)

    def teardown(self):
        for p in self._plugins:
            try: p.teardown()
            except Exception as e: logger.warning(f"Plugin teardown error ({p.name}): {e}")

    # ── Fire Hooks ────────────────────────────────────────

    def fire_message_saved(self, user_id, role, content, tags, metadata):
        for p in self._plugins:
            try: p.on_message_saved(user_id, role, content, tags, metadata)
            except Exception as e: logger.warning(f"{p.name}.on_message_saved: {e}")

    def fire_messages_cleared(self, user_id):
        for p in self._plugins:
            try: p.on_messages_cleared(user_id)
            except Exception as e: logger.warning(f"{p.name}.on_messages_cleared: {e}")

    def fire_context_build(self, user_id, messages: list) -> list:
        result = messages
        for p in self._plugins:
            try: result = p.on_context_build(user_id, result) or result
            except Exception as e: logger.warning(f"{p.name}.on_context_build: {e}")
        return result

    def fire_before_llm(self, user_id: str, agent_id: str, messages: list) -> list:
        """Dipanggil SEBELUM pesan dikirim ke LLM — bisa modifikasi messages."""
        result = messages
        for p in self._plugins:
            try: result = p.on_before_llm(user_id, agent_id, result) or result
            except Exception as e: logger.warning(f"{p.name}.on_before_llm: {e}")
        return result

    def fire_after_llm(self, user_id: str, agent_id: str, response: str) -> str:
        """Dipanggil SETELAH LLM menghasilkan response — bisa modifikasi response."""
        result = response
        for p in self._plugins:
            try: result = p.on_after_llm(user_id, agent_id, result) or result
            except Exception as e: logger.warning(f"{p.name}.on_after_llm: {e}")
        return result

    def fire_skill_saved(self, agent_id, name, content):
        for p in self._plugins:
            try: p.on_skill_saved(agent_id, name, content)
            except Exception as e: logger.warning(f"{p.name}.on_skill_saved: {e}")

    def fire_skill_deleted(self, agent_id, name):
        for p in self._plugins:
            try: p.on_skill_deleted(agent_id, name)
            except Exception as e: logger.warning(f"{p.name}.on_skill_deleted: {e}")

    def fire_prompt_build(self, agent_id, prompt: str) -> str:
        result = prompt
        for p in self._plugins:
            try: result = p.on_prompt_build(agent_id, result) or result
            except Exception as e: logger.warning(f"{p.name}.on_prompt_build: {e}")
        return result

    def fire_agent_routed(self, user_id, agent_id, message):
        for p in self._plugins:
            try: p.on_agent_routed(user_id, agent_id, message)
            except Exception as e: logger.warning(f"{p.name}.on_agent_routed: {e}")

    def fire_agent_chain(self, user_id, from_agent, to_agent, reason):
        for p in self._plugins:
            try: p.on_agent_chain(user_id, from_agent, to_agent, reason)
            except Exception as e: logger.warning(f"{p.name}.on_agent_chain: {e}")

    def fire_export(self, data: dict) -> dict:
        result = data
        for p in self._plugins:
            try: result = p.on_export(result) or result
            except Exception as e: logger.warning(f"{p.name}.on_export: {e}")
        return result

    def fire_import(self, data: dict) -> dict:
        result = data
        for p in self._plugins:
            try: result = p.on_import(result) or result
            except Exception as e: logger.warning(f"{p.name}.on_import: {e}")
        return result

    def summary(self) -> dict:
        return {
            "folder":  self.plugin_folder,
            "total":   len(self._plugins),
            "plugins": [
                {
                    "name":         p.name,
                    "version":      p.version,
                    "description":  p.description,
                    "depends_on":   p.depends_on,
                    "app_commands": list(p.get_app_commands().keys()),
                }
                for p in self._plugins
            ],
        }

    def set_app_info(self, info: dict):
        """
        Set app_info ke semua plugin yang ter-load.
        Dipanggil host app setelah load() untuk inject metadata platform.

        Contoh dari Telegram bot:
            loader.set_app_info({"platform": "telegram", "version": "1.2.0"})
        """
        for p in self._plugins:
            p.app_info = dict(info)

    def get_all_app_commands(self) -> dict[str, dict]:
        """
        Kumpulkan semua app_commands dari semua plugin yang ter-load.
        Return: { "command_name": {...cmd_info, "plugin": plugin_instance} }

        Digunakan host app untuk auto-register semua command sekaligus.
        Contoh:
            for cmd_name, cmd_info in loader.get_all_app_commands().items():
                app.register_command(cmd_name, cmd_info)
        """
        all_commands = {}
        for plugin in self._plugins:
            for cmd_name, cmd_info in plugin.get_app_commands().items():
                if cmd_name in all_commands:
                    existing = all_commands[cmd_name]["plugin"].name
                    logger.warning(
                        f"Command '{cmd_name}' sudah didaftarkan oleh plugin '{existing}'. "
                        f"Plugin '{plugin.name}' dilewati untuk command ini."
                    )
                    continue
                all_commands[cmd_name] = {**cmd_info, "plugin": plugin}
        return all_commands

    async def fire_app_command(self, context: AppCommandContext) -> Optional[str]:
        """
        Jalankan app_command ke plugin yang bersangkutan.

        Urutan eksekusi:
        1. Cari plugin yang punya command ini via get_all_app_commands()
        2. Panggil dedicated handler method (dari app_commands["handler"])
        3. Jika tidak ada dedicated handler, fallback ke on_app_command()
        4. Return string response atau None

        Contoh dari host app:
            ctx    = AppCommandContext.create("semantic", uid, args, platform="telegram")
            result = await sc._plugins.fire_app_command(ctx)
        """
        all_commands = self.get_all_app_commands()
        cmd_info     = all_commands.get(context.command)

        if cmd_info:
            plugin       = cmd_info["plugin"]
            handler_name = cmd_info.get("handler")
            if handler_name:
                handler = getattr(plugin, handler_name, None)
                if handler:
                    try:
                        return await handler(context)
                    except Exception as e:
                        logger.warning(f"Error di {plugin.name}.{handler_name}: {e}")
                        return None

        # Fallback: coba on_app_command di semua plugin
        for plugin in self._plugins:
            try:
                result = await plugin.on_app_command(context)
                if result is not None:
                    return result
            except Exception as e:
                logger.warning(f"{plugin.name}.on_app_command: {e}")

        return None

    def __repr__(self):
        return f"<PluginLoader plugins={len(self._plugins)} folder={self.plugin_folder!r}>"
