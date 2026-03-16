"""
context/adaptive.py — Adaptive Scoring
Per-user bobot scoring yang belajar dari feedback.
Zero dependencies — simpan weight history di SQLite.
"""

from __future__ import annotations
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..storage.base import BaseStorage
    from .node import ContextNode

# Default weights (harus total = 1.0)
DEFAULT_WEIGHTS = {
    "relevance":     0.55,
    "importance":    0.25,
    "recency":       0.10,
    "path_priority": 0.10,
}

# Batas perubahan weight per feedback
LEARNING_RATE      = 0.03
MIN_WEIGHT         = 0.05
MAX_WEIGHT         = 0.70
FEEDBACK_HISTORY_LIMIT = 50


class AdaptiveScorer:
    """
    Scorer yang belajar dari feedback user.
    Weight per dimensi scoring disesuaikan berdasarkan:
    - Feedback positif (score > 0.5): boost tier yang banyak dipakai
    - Feedback negatif (score < -0.5): kurangi bobot tier yang dominan
    """

    def __init__(self, storage: "BaseStorage"):
        self._storage = storage
        self._ensure_table()

    def _ensure_table(self):
        conn = self._storage._conn
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS adaptive_weights (
                user_id     TEXT PRIMARY KEY,
                weights     TEXT NOT NULL,
                feedback_count INTEGER DEFAULT 0,
                updated_at  TEXT
            );
        """)
        conn.commit()

    # ── Weights ───────────────────────────────────────────

    def get_weights(self, user_id: str) -> dict:
        """Ambil weights untuk user. Default kalau belum ada."""
        row = self._storage._conn.execute(
            "SELECT weights FROM adaptive_weights WHERE user_id=?",
            (user_id,)
        ).fetchone()
        if not row:
            return dict(DEFAULT_WEIGHTS)
        try:
            return json.loads(row[0])
        except Exception:
            return dict(DEFAULT_WEIGHTS)

    def save_weights(self, user_id: str, weights: dict):
        """Simpan weights untuk user."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        self._storage._conn.execute("""
            INSERT INTO adaptive_weights (user_id, weights, feedback_count, updated_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                weights        = excluded.weights,
                feedback_count = feedback_count + 1,
                updated_at     = excluded.updated_at
        """, (user_id, json.dumps(weights), now))
        self._storage._conn.commit()

    def reset_weights(self, user_id: str):
        """Reset ke default weights."""
        self.save_weights(user_id, dict(DEFAULT_WEIGHTS))

    # ── Feedback ──────────────────────────────────────────

    def record_feedback(self, user_id: str,
                        selected_nodes: list["ContextNode"],
                        feedback_score: float):
        """
        Update weights berdasarkan feedback.

        feedback_score:
        +1.0 = sangat membantu
         0.0 = netral
        -1.0 = tidak membantu / salah konteks

        Cara kerja:
        - Feedback positif → boost bobot tier yang banyak di selected_nodes
        - Feedback negatif → kurangi bobot tier yang dominan
        """
        if not selected_nodes:
            return

        weights = self.get_weights(user_id)

        # Hitung distribusi tier di selected nodes
        tier_counts: dict[str, int] = {}
        total = len(selected_nodes)
        for node in selected_nodes:
            tier = node.tier.value if hasattr(node.tier, "value") else str(node.tier)
            tier_counts[tier] = tier_counts.get(tier, 0) + 1

        # Tier yang dominan mendapat feedback
        dominant_tier = max(tier_counts, key=tier_counts.get) if tier_counts else None

        if feedback_score > 0.5 and dominant_tier:
            # Positif: boost relevance dan importance (yang paling umum berguna)
            weights["relevance"]  = min(MAX_WEIGHT,
                                       weights["relevance"] + LEARNING_RATE * feedback_score)
            weights["importance"] = min(MAX_WEIGHT,
                                       weights["importance"] + LEARNING_RATE * 0.5 * feedback_score)

        elif feedback_score < -0.5 and dominant_tier:
            # Negatif: kurangi recency (sering over-weigh pesan lama yang tidak relevan)
            weights["recency"]    = max(MIN_WEIGHT,
                                       weights["recency"] + LEARNING_RATE * feedback_score)
            weights["path_priority"] = max(MIN_WEIGHT,
                                          weights["path_priority"] + LEARNING_RATE * 0.5 * feedback_score)

        # Normalisasi agar total = 1.0
        weights = _normalize(weights)
        self.save_weights(user_id, weights)

    # ── Scoring ───────────────────────────────────────────

    def score(self, node: "ContextNode", query_tokens: list[str],
              plan, user_id: str) -> float:
        """
        Hitung score dengan user-specific weights.
        Drop-in replacement untuk ContextScorer._score().
        """
        from .scorer import ContextScorer, _token_overlap, _tokenize

        weights = self.get_weights(user_id)
        scorer  = ContextScorer()

        relevance     = scorer._relevance(node, query_tokens, plan)
        importance    = node.importance
        recency       = scorer._recency(node)
        path_priority = scorer._path_priority(node)

        return (relevance     * weights.get("relevance", 0.55)
                + importance  * weights.get("importance", 0.25)
                + recency     * weights.get("recency", 0.10)
                + path_priority * weights.get("path_priority", 0.10))

    def stats(self, user_id: str) -> dict:
        """Return current weights dan feedback count untuk user."""
        weights = self.get_weights(user_id)
        row = self._storage._conn.execute(
            "SELECT feedback_count, updated_at FROM adaptive_weights WHERE user_id=?",
            (user_id,)
        ).fetchone()
        return {
            "weights":        weights,
            "feedback_count": row[0] if row else 0,
            "last_updated":   row[1] if row else None,
        }


def _normalize(weights: dict) -> dict:
    """Normalisasi weights agar total = 1.0, semua di [MIN, MAX]."""
    # Clamp dulu
    clamped = {k: max(MIN_WEIGHT, min(MAX_WEIGHT, v)) for k, v in weights.items()}
    total   = sum(clamped.values())
    if total == 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: v / total for k, v in clamped.items()}
