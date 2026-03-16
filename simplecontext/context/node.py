"""
context/node.py — ContextNode dataclass
Node adalah unit terkecil dari context system.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import uuid

from ..enums import Tier, NodeKind, NodeStatus, validate_tier_kind, SKILL_NAMESPACE_PREFIX


@dataclass
class ContextNode:
    """
    Satu unit context — bisa berupa pesan, fakta, ringkasan, skill, dll.

    path mengikuti konvensi:
        /memory/working/{user_id}/{id}
        /memory/episodic/{user_id}/{id}
        /memory/semantic/{user_id}/{id}
        /skills/{agent_id}/{name}
    """
    # ── Required ──────────────────────────────────────────
    user_id:    str
    path:       str
    tier:       Tier
    kind:       NodeKind
    content:    str

    # ── Auto-generated ────────────────────────────────────
    id:         str      = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ── Scoring ───────────────────────────────────────────
    importance: float = 0.5     # [0.0, 1.0]
    confidence: float = 1.0     # [0.0, 1.0]

    # ── Metadata ──────────────────────────────────────────
    source:     str             = "user"    # user | assistant | system | inferred
    status:     NodeStatus      = NodeStatus.ACTIVE
    supersedes: Optional[str]   = None      # id node yang digantikan
    tags:       list[str]       = field(default_factory=list)
    metadata:   dict            = field(default_factory=dict)

    def __post_init__(self):
        # Normalisasi tags
        self.tags = [t.lower().strip() for t in self.tags if t.strip()]

        # Clamp importance dan confidence
        self.importance = max(0.0, min(1.0, self.importance))
        self.confidence = max(0.0, min(1.0, self.confidence))

        # Validasi tier+kind
        if self.kind != NodeKind.SKILL:
            if not validate_tier_kind(self.tier, self.kind):
                raise ValueError(
                    f"Kombinasi tier={self.tier!r} + kind={self.kind!r} tidak valid. "
                    f"Lihat VALID_TIER_KIND di enums.py."
                )

        # Skill harus punya path di /skills/
        if self.kind == NodeKind.SKILL and not self.path.startswith(SKILL_NAMESPACE_PREFIX):
            raise ValueError(
                f"Node dengan kind=SKILL harus punya path yang dimulai dengan '{SKILL_NAMESPACE_PREFIX}'. "
                f"Diberikan: {self.path!r}"
            )

    # ── Convenience properties ────────────────────────────

    @property
    def is_active(self) -> bool:
        return self.status == NodeStatus.ACTIVE

    @property
    def age_hours(self) -> float:
        """Umur node dalam jam."""
        now = datetime.now(timezone.utc)
        # Handle naive datetime dari SQLite
        updated = self.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return (now - updated).total_seconds() / 3600

    @property
    def char_count(self) -> int:
        return len(self.content)

    def touch(self):
        """Update updated_at ke sekarang."""
        self.updated_at = datetime.now(timezone.utc)

    def update_importance(self, delta: float):
        """Update importance dengan clamp [0.0, 1.0]."""
        self.importance = max(0.0, min(1.0, self.importance + delta))
        self.touch()

    def expire(self):
        """Soft delete: mark sebagai expired."""
        self.status    = NodeStatus.EXPIRED
        self.importance = 0.0
        self.touch()

    def supersede_by(self, new_node_id: str):
        """Mark node ini sebagai digantikan oleh node lain."""
        self.status    = NodeStatus.SUPERSEDED
        self.importance = max(0.0, self.importance - 0.10)
        self.metadata["superseded_by"] = new_node_id
        self.touch()

    # ── Serialization ─────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize ke dict untuk storage."""
        import json
        return {
            "id":          self.id,
            "user_id":     self.user_id,
            "path":        self.path,
            "tier":        self.tier.value,
            "kind":        self.kind.value,
            "content":     self.content,
            "created_at":  self.created_at.isoformat(),
            "updated_at":  self.updated_at.isoformat(),
            "importance":  self.importance,
            "confidence":  self.confidence,
            "source":      self.source,
            "status":      self.status.value,
            "supersedes":  self.supersedes,
            "tags":        json.dumps(self.tags),
            "metadata":    json.dumps(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ContextNode":
        """Deserialize dari dict (dari DB)."""
        import json
        from datetime import datetime

        def parse_dt(s: str) -> datetime:
            if not s:
                return datetime.now(timezone.utc)
            try:
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                return datetime.now(timezone.utc)

        def parse_json(v):
            if isinstance(v, str):
                try:
                    return json.loads(v)
                except Exception:
                    return v
            return v or {}

        return cls(
            id          = d["id"],
            user_id     = d["user_id"],
            path        = d["path"],
            tier        = Tier(d["tier"]),
            kind        = NodeKind(d["kind"]),
            content     = d["content"],
            created_at  = parse_dt(d.get("created_at", "")),
            updated_at  = parse_dt(d.get("updated_at", "")),
            importance  = float(d.get("importance", 0.5)),
            confidence  = float(d.get("confidence", 1.0)),
            source      = d.get("source", "user"),
            status      = NodeStatus(d.get("status", "active")),
            supersedes  = d.get("supersedes"),
            tags        = parse_json(d.get("tags", "[]")),
            metadata    = parse_json(d.get("metadata", "{}")),
        )

    def __repr__(self):
        return (f"<ContextNode {self.tier.value}/{self.kind.value} "
                f"path={self.path!r} imp={self.importance:.2f} "
                f"status={self.status.value}>")
