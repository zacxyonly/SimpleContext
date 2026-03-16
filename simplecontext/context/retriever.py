"""
context/retriever.py — ContextRetriever
Ambil candidate nodes dari storage berdasarkan RetrievalPlan.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..storage.base import BaseStorage
    from .node import ContextNode
    from .planner import RetrievalPlan

from ..enums import Tier, NodeKind, NodeStatus, SKILL_NAMESPACE_PREFIX


class ContextRetriever:
    """
    Ambil kandidat node dari storage.
    Belum di-filter status, belum di-score.
    """

    def __init__(self, storage: "BaseStorage"):
        self._storage = storage

    def collect(self, plan: "RetrievalPlan") -> list["ContextNode"]:
        """
        Kumpulkan semua kandidat node sesuai plan.
        Return flat list — belum di-filter, belum di-sort.
        """
        candidates: list["ContextNode"] = []
        uid = plan.user_id

        # ── Working tier ──────────────────────────────────
        if plan.working:
            limit = plan.budget.get("working", 5) * 3  # ambil lebih, nanti di-filter
            nodes = self._storage.get_nodes(
                uid, tier=Tier.WORKING.value,
                status=None,  # ambil semua status, resolver yang handle TTL
                limit=limit,
            )
            candidates.extend(nodes)

        # ── Episodic tier ─────────────────────────────────
        if plan.episodic:
            limit = plan.budget.get("episodic", 2) * 3
            nodes = self._storage.get_nodes(
                uid, tier=Tier.EPISODIC.value,
                status=None,
                limit=limit,
            )
            candidates.extend(nodes)

        # ── Semantic tier ─────────────────────────────────
        if plan.semantic:
            # Kalau ada keyword di query, tambahkan search
            limit = plan.budget.get("semantic", 4) * 3
            nodes = self._storage.get_nodes(
                uid, tier=Tier.SEMANTIC.value,
                status=None,
                limit=limit,
            )
            candidates.extend(nodes)

            # Tambahan: search nodes berdasarkan keyword dari query
            if plan.query:
                keywords = _extract_keywords(plan.query)
                for kw in keywords[:3]:  # max 3 keyword search
                    search_results = self._storage.search_nodes(
                        uid, keyword=kw,
                        tier=Tier.SEMANTIC.value,
                        limit=5,
                    )
                    for n in search_results:
                        if n.id not in {c.id for c in candidates}:
                            candidates.append(n)

        # ── Skills namespace ──────────────────────────────
        if plan.include_skills:
            # Skills disimpan dengan path /skills/{agent_id}/...
            skill_nodes = self._storage.get_nodes_by_path_prefix(uid, SKILL_NAMESPACE_PREFIX)
            # Juga ambil dari agent_id kalau ada di metadata plan
            agent_id = plan.metadata.get("agent_id") if hasattr(plan, "metadata") else None
            if agent_id:
                agent_skill_nodes = self._storage.get_nodes_by_path_prefix(
                    uid, f"{SKILL_NAMESPACE_PREFIX}{agent_id}/"
                )
                for n in agent_skill_nodes:
                    if n.id not in {c.id for c in skill_nodes}:
                        skill_nodes.append(n)
            candidates.extend(skill_nodes)

        # ── Focus paths (preferred_paths dari plan) ───────
        for path_prefix in plan.preferred_paths:
            path_nodes = self._storage.get_nodes_by_path_prefix(uid, path_prefix)
            for n in path_nodes:
                if n.id not in {c.id for c in candidates}:
                    candidates.append(n)

        # ── Focus tags ────────────────────────────────────
        if plan.focus_tags:
            # Boost: cari node dengan tags yang match
            for node in candidates:
                if any(t in node.tags for t in plan.focus_tags):
                    node.importance = min(1.0, node.importance + 0.1)

        return candidates


def _extract_keywords(text: str) -> list[str]:
    """Ekstrak kata kunci dari query untuk semantic search."""
    import re
    stopwords = {
        "yang", "dan", "di", "ke", "dari", "ini", "itu", "dengan", "untuk",
        "adalah", "ada", "saya", "kamu", "aku", "bisa", "mau", "bagaimana",
        "the", "a", "an", "is", "are", "how", "what", "why", "when", "where",
        "i", "you", "we", "do", "does", "can", "please", "tolong",
    }
    words = re.findall(r'\b[a-zA-Z0-9\u00C0-\u024F]{3,}\b', text.lower())
    return [w for w in words if w not in stopwords]
