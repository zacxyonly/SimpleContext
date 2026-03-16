"""
context/scorer.py v4.1 — ContextScorer
Score formula diperluas:
  score = relevance*0.55 + importance*0.25 + recency*0.10 + path_priority*0.10

path_priority: /memory/semantic > /memory/episodic > /memory/working
relevance: text + tag + path similarity
"""

from __future__ import annotations
import re
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .node import ContextNode
    from .planner import RetrievalPlan

from ..enums import Intent

# Bobot scoring (total = 1.0)
W_RELEVANCE     = 0.55
W_IMPORTANCE    = 0.25
W_RECENCY       = 0.10
W_PATH_PRIORITY = 0.10

# Recency half-life per tier (jam)
RECENCY_HALF_LIFE = {
    "working":  1.0,
    "episodic": 72.0,
    "semantic": 720.0,
}

# Sub-bobot relevance
W_TEXT = 0.60
W_TAG  = 0.25
W_PATH = 0.15

# Path priority scores (0.0 – 1.0)
PATH_PRIORITY_MAP = {
    "/memory/semantic": 1.0,    # knowledge jangka panjang → prioritas tinggi
    "/memory/episodic": 0.6,    # ringkasan sesi → menengah
    "/memory/working":  0.3,    # pesan aktif → rendah (tapi sudah banyak)
    "/skills":          0.8,    # skills → tinggi untuk coding/task
}

_STOPWORDS = {
    "yang","dan","di","ke","dari","ini","itu","dengan","untuk","adalah",
    "ada","saya","kamu","aku","kita","bisa","mau","the","a","an","is",
    "are","was","i","you","we","to","of","in","it","and","or","but",
    "do","does","did","tolong","please","gimana","bagaimana",
}


class ContextScorer:
    """Rank candidate nodes berdasarkan score gabungan."""

    def rank(self, nodes: list["ContextNode"],
             plan: "RetrievalPlan") -> list["ContextNode"]:
        """Return nodes diurutkan score tertinggi ke terendah."""
        if not nodes:
            return []
        query_tokens = _tokenize(plan.query)
        scored = [(self._score(n, query_tokens, plan), n) for n in nodes]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [n for _, n in scored]

    def _score(self, node: "ContextNode", query_tokens: list[str],
               plan: "RetrievalPlan") -> float:
        relevance     = self._relevance(node, query_tokens, plan)
        importance    = node.importance
        recency       = self._recency(node)
        path_priority = self._path_priority(node)

        return (relevance     * W_RELEVANCE
                + importance  * W_IMPORTANCE
                + recency     * W_RECENCY
                + path_priority * W_PATH_PRIORITY)

    def _relevance(self, node: "ContextNode", query_tokens: list[str],
                   plan: "RetrievalPlan") -> float:
        if not query_tokens:
            return 0.5

        text_sim = _token_overlap(query_tokens, _tokenize(node.content))
        tag_sim  = _token_overlap(query_tokens, node.tags)
        path_sim = _token_overlap(query_tokens, _tokenize(node.path.replace("/", " ")))

        base = text_sim * W_TEXT + tag_sim * W_TAG + path_sim * W_PATH

        # Intent boost
        intent_boost = self._intent_boost(node, plan.intent)
        return min(1.0, base + intent_boost)

    def _intent_boost(self, node: "ContextNode", intent: str) -> float:
        boosts = {
            Intent.PERSONAL.value:     {"semantic", "fact"},
            Intent.CODING.value:       {"skill", "resource", "fact"},
            Intent.TASK.value:         {"task_state", "fact", "episodic"},
            Intent.KNOWLEDGE.value:    {"semantic", "resource", "fact"},
            Intent.CONVERSATION.value: {"working", "message"},
        }
        relevant = boosts.get(intent, set())
        if node.kind.value in relevant or node.tier.value in relevant:
            return 0.08
        return 0.0

    def _recency(self, node: "ContextNode") -> float:
        half_life = RECENCY_HALF_LIFE.get(node.tier.value, 72.0)
        return math.pow(2, -node.age_hours / half_life)

    def _path_priority(self, node: "ContextNode") -> float:
        """Hitung path priority berdasarkan prefix path node."""
        for prefix, score in sorted(PATH_PRIORITY_MAP.items(),
                                     key=lambda x: -len(x[0])):
            if node.path.startswith(prefix):
                return score
        return 0.3  # default


# ── Token helpers ─────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    words = re.findall(r'\b[a-zA-Z0-9\u00C0-\u024F]{2,}\b', text.lower())
    return [w for w in words if w not in _STOPWORDS]

def _token_overlap(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb)
