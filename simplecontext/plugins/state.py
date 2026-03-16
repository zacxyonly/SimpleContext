"""
Plugin State Manager
State permanen untuk plugin, disimpan ke storage backend.
"""

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..storage.base import BaseStorage


class PluginState:
    """
    Persistent state untuk satu plugin.
    Dibuat otomatis oleh PluginLoader saat plugin diinit.

    Contoh penggunaan di dalam plugin:
        def on_message_saved(self, ...):
            count = self.state.get("message_count", 0)
            self.state.set("message_count", count + 1)
    """

    def __init__(self, storage: "BaseStorage", plugin_name: str):
        self._storage     = storage
        self._plugin_name = plugin_name

    def get(self, key: str, default: Any = None) -> Any:
        """Ambil nilai state"""
        return self._storage.get_plugin_state(self._plugin_name).get(key, default)

    def set(self, key: str, value: Any):
        """Set satu nilai state"""
        self._storage.update_plugin_state(self._plugin_name, key, value)

    def all(self) -> dict:
        """Ambil semua state sebagai dict"""
        return self._storage.get_plugin_state(self._plugin_name)

    def update(self, data: dict):
        """Update banyak key sekaligus"""
        current = self.all()
        current.update(data)
        self._storage.set_plugin_state(self._plugin_name, current)

    def clear(self):
        """Hapus semua state plugin ini"""
        self._storage.set_plugin_state(self._plugin_name, {})

    def increment(self, key: str, by: int = 1) -> int:
        """Increment nilai integer, return nilai baru"""
        val = self.get(key, 0)
        new_val = val + by
        self.set(key, new_val)
        return new_val

    def __repr__(self):
        return f"<PluginState plugin={self._plugin_name} keys={list(self.all().keys())}>"
