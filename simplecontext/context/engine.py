"""
context/engine.py v4.1 — ContextEngine
Tambahan:
- Context cache (LRU, TTL 30s)
- Retrieval debug mode dengan detail log
"""

from __future__ import annotations
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..storage.base import BaseStorage
    from .node import ContextNode
    from .planner import RetrievalPlan

from .retriever import ContextRetriever
from .resolver  import StatusResolver, CandidateFilter
from .scorer    import ContextScorer
from .selector  import ContextSelector
from .cache     import ContextCache

logger = logging.getLogger(__name__)


class ContextEngine:
    """
    Facade untuk pipeline retrieval lengkap.

    Pipeline: collect → resolve_status → filter → score → select

    Dengan cache: kalau query + intent sama dalam 30 detik → pakai cache.
    """

    def __init__(self, storage: "BaseStorage",
                 ttl_config: dict = None,
                 cache_ttl: int = 30,
                 debug: bool = False):
        self._retriever = ContextRetriever(storage)
        self._resolver  = StatusResolver(storage, ttl_config)
        self._filter    = CandidateFilter()
        self._scorer    = ContextScorer()
        self._selector  = ContextSelector()
        self._cache     = ContextCache(ttl_seconds=cache_ttl)
        self._debug     = debug

    def retrieve(self, plan: "RetrievalPlan") -> list["ContextNode"]:
        """
        Jalankan pipeline retrieval lengkap.
        Pakai cache kalau query+intent sama dan belum expired.
        """
        # Cek cache
        cache_key = ContextCache.make_key(plan.user_id, plan.query, plan.intent)
        cached = self._cache.get(cache_key)
        if cached is not None:
            if self._debug:
                logger.info(f"[ContextEngine] CACHE HIT key={cache_key[:20]}... nodes={len(cached)}")
            return cached

        # Pipeline
        candidates = self._retriever.collect(plan)
        candidates = self._resolver.resolve(candidates)
        active     = self._filter.apply(candidates)
        ranked     = self._scorer.rank(active, plan)
        selected   = self._selector.select(ranked, plan)

        if self._debug:
            self._log_debug(plan, candidates, active, selected)

        # Simpan ke cache
        self._cache.set(cache_key, selected)

        return selected

    def invalidate_cache(self, user_id: str):
        """Hapus cache untuk user tertentu — panggil setelah save turn."""
        self._cache.invalidate(user_id)

    def set_debug(self, enabled: bool):
        """Toggle debug mode."""
        self._debug = enabled

    def _log_debug(self, plan: "RetrievalPlan",
                   candidates: list, active: list, selected: list):
        """Log detail retrieval pipeline."""
        logger.info(
            f"\n[ContextEngine] ── Retrieval Debug ──\n"
            f"  query:      {plan.query[:60]!r}\n"
            f"  intent:     {plan.intent}\n"
            f"  user_id:    {plan.user_id}\n"
            f"  candidates: {len(candidates)}\n"
            f"  active:     {len(active)}\n"
            f"  selected:   {len(selected)}\n"
            f"  total_chars:{sum(n.char_count for n in selected)}\n"
            f"  breakdown:"
        )
        from ..enums import Tier
        for tier in list(Tier) + ["skills"]:
            tier_val = tier.value if hasattr(tier, "value") else tier
            count = sum(1 for n in selected
                       if (n.tier.value == tier_val
                           or (tier_val == "skills" and "/skills/" in n.path)))
            if count:
                logger.info(f"    {tier_val}: {count}")

        if selected:
            logger.info("  nodes selected:")
            for n in selected:
                logger.info(f"    [{n.tier.value}/{n.kind.value}] "
                            f"imp={n.importance:.2f} "
                            f"path={n.path} "
                            f"content={n.content[:50]!r}")

    def get_stats(self, plan: "RetrievalPlan") -> dict:
        """Return stats tanpa menggunakan cache."""
        candidates = self._retriever.collect(plan)
        resolved   = self._resolver.resolve(list(candidates))
        active     = self._filter.apply(resolved)
        ranked     = self._scorer.rank(active, plan)
        selected   = self._selector.select(ranked, plan)

        from ..enums import Tier
        tier_counts = {t.value: 0 for t in Tier}
        tier_counts["skills"] = 0
        for n in selected:
            if "/skills/" in n.path:
                tier_counts["skills"] += 1
            else:
                tier_counts[n.tier.value] = tier_counts.get(n.tier.value, 0) + 1

        return {
            "candidates":     len(candidates),
            "active":         len(active),
            "selected":       len(selected),
            "total_chars":    sum(n.char_count for n in selected),
            "tier_breakdown": tier_counts,
            "cache_size":     self._cache.size,
        }
