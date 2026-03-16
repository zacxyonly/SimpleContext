"""
BaseStorage v3 — Abstract Interface
Sync dan async methods.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional


class BaseStorage(ABC):

    # ── Messages ──────────────────────────────────────────

    @abstractmethod
    def save_message(self, user_id: str, role: str, content: str,
                     tags: list = None, metadata: dict = None) -> int: ...

    @abstractmethod
    def get_messages(self, user_id: str, limit: int = 20,
                     tags: list = None) -> list[dict]: ...

    @abstractmethod
    def count_messages(self, user_id: str) -> int: ...

    @abstractmethod
    def delete_messages(self, user_id: str, tags: list = None): ...

    @abstractmethod
    def search_messages(self, user_id: str, keyword: str,
                        limit: int = 5) -> list[dict]: ...

    # ── Skills ────────────────────────────────────────────

    @abstractmethod
    def save_skill(self, agent_id: str, name: str, content: str,
                   description: str = "", extends: str = None,
                   enabled: bool = True, priority: int = 0,
                   group: str = None, conditions: dict = None,
                   tags: list = None, metadata: dict = None): ...

    @abstractmethod
    def get_skill(self, agent_id: str, name: str) -> Optional[dict]: ...

    @abstractmethod
    def get_skills(self, agent_id: str, enabled_only: bool = True,
                   group: str = None, tags: list = None) -> list[dict]: ...

    @abstractmethod
    def delete_skill(self, agent_id: str, name: str) -> bool: ...

    @abstractmethod
    def search_skills(self, agent_id: str, keyword: str) -> list[dict]: ...

    # ── Profile ───────────────────────────────────────────

    @abstractmethod
    def get_profile(self, user_id: str) -> dict: ...

    @abstractmethod
    def set_profile(self, user_id: str, data: dict): ...

    @abstractmethod
    def update_profile(self, user_id: str, key: str, value: Any): ...

    # ── Plugin State ──────────────────────────────────────

    @abstractmethod
    def get_plugin_state(self, plugin_name: str) -> dict: ...

    @abstractmethod
    def set_plugin_state(self, plugin_name: str, data: dict): ...

    @abstractmethod
    def update_plugin_state(self, plugin_name: str, key: str, value: Any): ...

    # ── Export / Import ───────────────────────────────────

    @abstractmethod
    def export_user(self, user_id: str) -> dict: ...

    @abstractmethod
    def export_agent(self, agent_id: str) -> dict: ...

    @abstractmethod
    def export_all(self) -> dict: ...

    @abstractmethod
    def import_data(self, data: dict, merge: bool = True): ...

    # ── Utils ─────────────────────────────────────────────

    @abstractmethod
    def get_stats(self) -> dict: ...

    @abstractmethod
    def list_users(self) -> list[str]: ...

    @abstractmethod
    def list_agents(self) -> list[str]: ...

    @abstractmethod
    def close(self): ...

    # ── Context Nodes (v4) ────────────────────────────────

    @abstractmethod
    def save_node(self, node) -> None: ...

    @abstractmethod
    def get_node(self, node_id: str): ...

    @abstractmethod
    def get_nodes(self, user_id: str, tier: str = None,
                  kind: str = None, status: str = "active",
                  limit: int = 100, order: str = "importance") -> list: ...

    @abstractmethod
    def update_node_status(self, node_id: str, status: str) -> None: ...

    @abstractmethod
    def update_node_importance(self, node_id: str, importance: float) -> None: ...

    @abstractmethod
    def search_nodes(self, user_id: str, keyword: str,
                     tier: str = None, limit: int = 20) -> list: ...

    @abstractmethod
    def get_nodes_by_path_prefix(self, user_id: str, prefix: str) -> list: ...

    @abstractmethod
    def delete_nodes(self, user_id: str, status: str = None) -> None: ...

    @abstractmethod
    def count_nodes(self, user_id: str, tier: str = None,
                    status: str = "active") -> int: ...
