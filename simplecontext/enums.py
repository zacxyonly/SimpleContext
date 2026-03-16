"""
enums.py — Enum definitions untuk SimpleContext v4
Pakai str Enum agar kompatibel langsung dengan SQLite dan JSON.
"""

from enum import Enum


class Tier(str, Enum):
    """Tier memory node."""
    WORKING  = "working"    # pesan aktif, task state — singkat, selalu di-load
    EPISODIC = "episodic"   # ringkasan sesi, interaction history — medium TTL
    SEMANTIC = "semantic"   # facts, knowledge jangka panjang — permanen


class NodeKind(str, Enum):
    """Jenis konten node."""
    MESSAGE       = "message"        # pesan user/assistant
    FACT          = "fact"           # fakta yang diekstrak
    SUMMARY       = "summary"        # ringkasan sesi/percakapan
    RESOURCE      = "resource"       # dokumen, referensi eksternal
    TASK_STATE    = "task_state"     # state task yang sedang berjalan
    SKILL         = "skill"          # skill/instruksi agent (namespace /skills/)


class NodeStatus(str, Enum):
    """Status lifecycle node."""
    ACTIVE      = "active"       # node aktif, bisa di-retrieve
    SUPERSEDED  = "superseded"   # digantikan node lain (conflict resolution)
    EXPIRED     = "expired"      # TTL habis, soft deleted
    DELETED     = "deleted"      # dihapus manual


class Intent(str, Enum):
    """Intent user untuk context planning."""
    CONVERSATION = "conversation"   # obrolan umum
    PERSONAL     = "personal"       # pertanyaan tentang diri/preferensi user
    CODING       = "coding"         # programming, debug, review
    TASK         = "task"           # menyelesaikan tugas spesifik
    KNOWLEDGE    = "knowledge"      # pertanyaan faktual/knowledge base


# ── Valid tier+kind combinations ─────────────────────────
# Skill ada di namespace /skills/, bukan tier memory biasa

VALID_TIER_KIND: dict[Tier, set[NodeKind]] = {
    Tier.WORKING:  {NodeKind.MESSAGE, NodeKind.FACT, NodeKind.TASK_STATE},
    Tier.EPISODIC: {NodeKind.SUMMARY, NodeKind.FACT},
    Tier.SEMANTIC: {NodeKind.FACT, NodeKind.RESOURCE},
}

# Skill hanya boleh kind=SKILL
SKILL_NAMESPACE_PREFIX = "/skills/"


def validate_tier_kind(tier: Tier, kind: NodeKind) -> bool:
    """Return True kalau kombinasi tier+kind valid."""
    if kind == NodeKind.SKILL:
        return False  # skill tidak masuk tier memory
    valid_kinds = VALID_TIER_KIND.get(tier, set())
    return kind in valid_kinds


# ── Importance delta constants ────────────────────────────

class ImportanceDelta:
    USED_IN_RETRIEVAL  = +0.02
    NEW_FACT_FROM_USER = +0.10
    SUPERSEDED         = -0.10
    DAILY_DECAY        = -0.005
    MIN                = 0.0
    MAX                = 1.0

    @classmethod
    def clamp(cls, value: float) -> float:
        return max(cls.MIN, min(cls.MAX, value))


# ── Default retrieval budgets ─────────────────────────────

DEFAULT_BUDGET: dict[str, int] = {
    "working":  5,
    "episodic": 2,
    "semantic": 4,
    "skills":   2,
}

DEFAULT_MAX_TOTAL_NODES = 12
DEFAULT_MAX_TOTAL_CHARS = 8000


# ── Default TTL per tier (dalam jam) ─────────────────────

DEFAULT_TTL_HOURS: dict[Tier, float | None] = {
    Tier.WORKING:  2.0,     # 2 jam
    Tier.EPISODIC: 720.0,   # 30 hari
    Tier.SEMANTIC: None,    # permanen
}
