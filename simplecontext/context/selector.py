"""
context/selector.py — ContextSelector
Pilih final nodes dari ranked list berdasarkan:
- budget per tier
- max_total_nodes global
- max_total_chars global
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .node import ContextNode
    from .planner import RetrievalPlan

from ..enums import Tier, NodeKind, SKILL_NAMESPACE_PREFIX


class ContextSelector:
    """
    Pilih final set nodes yang akan masuk ke prompt.
    Menghormati budget per tier dan limit global.
    """

    def select(self, ranked_nodes: list["ContextNode"],
               plan: "RetrievalPlan") -> list["ContextNode"]:
        """
        Pilih nodes dari ranked list dengan constraint:
        1. Max per tier (dari plan.budget)
        2. Max total nodes (plan.max_total_nodes)
        3. Max total chars (plan.max_total_chars)

        Urutan prioritas: working > episodic > semantic > skills
        (karena working paling relevan untuk percakapan saat ini)
        """
        budget         = plan.budget
        max_nodes      = plan.max_total_nodes
        max_chars      = plan.max_total_chars

        # Counter per tier
        counts: dict[str, int] = {
            "working":  0,
            "episodic": 0,
            "semantic": 0,
            "skills":   0,
        }

        selected: list["ContextNode"] = []
        total_chars = 0

        for node in ranked_nodes:
            # Cek global limits dulu
            if len(selected) >= max_nodes:
                break
            if total_chars >= max_chars:
                break

            # Tentukan bucket (skills atau tier biasa)
            if node.path.startswith(SKILL_NAMESPACE_PREFIX) or node.kind == NodeKind.SKILL:
                bucket = "skills"
            else:
                bucket = node.tier.value

            # Cek budget per tier
            tier_limit = budget.get(bucket, 0)
            if counts[bucket] >= tier_limit:
                continue

            # Cek apakah chars masih muat
            node_chars = node.char_count
            if total_chars + node_chars > max_chars:
                # Kalau node ini terlalu besar, skip tapi lanjut ke node berikutnya
                # yang mungkin lebih kecil
                continue

            selected.append(node)
            counts[bucket] += 1
            total_chars += node_chars

        return selected
