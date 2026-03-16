"""
context/resolver.py — StatusResolver
TTL check: mengubah status node, bukan sekadar menyaring.

context/filter.py logic juga ada di sini karena keduanya erat.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..storage.base import BaseStorage
    from .node import ContextNode

from ..enums import NodeStatus, DEFAULT_TTL_HOURS, Tier


class StatusResolver:
    """
    Periksa TTL setiap node dan update status jika sudah expired.
    Ini mengubah state node, bukan hanya menyaring.
    """

    def __init__(self, storage: "BaseStorage",
                 ttl_config: dict[str, float | None] = None):
        """
        ttl_config: override TTL per tier dalam jam.
        None = tidak pernah expire.
        """
        self._storage = storage
        self._ttl: dict[str, float | None] = {
            tier.value: DEFAULT_TTL_HOURS.get(tier)
            for tier in Tier
        }
        if ttl_config:
            self._ttl.update(ttl_config)

    def resolve(self, nodes: list["ContextNode"]) -> list["ContextNode"]:
        """
        Periksa dan update status node yang sudah expired.
        Return nodes yang sama — sudah diupdate in-place.
        """
        for node in nodes:
            if node.status != NodeStatus.ACTIVE:
                continue  # sudah ada status, skip

            ttl = self._ttl.get(node.tier.value)
            if ttl is None:
                continue  # permanen, tidak expire

            if node.age_hours > ttl:
                node.expire()
                # Persist ke storage
                self._storage.update_node_status(node.id, NodeStatus.EXPIRED.value)

        return nodes


class CandidateFilter:
    """
    Filter nodes — hanya loloskan yang status=active.
    """

    def apply(self, nodes: list["ContextNode"]) -> list["ContextNode"]:
        """Return hanya node dengan status ACTIVE."""
        return [n for n in nodes if n.status == NodeStatus.ACTIVE]
