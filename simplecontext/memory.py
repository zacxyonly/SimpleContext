"""
memory.py v4
TieredMemory: akses per tier (working/episodic/semantic).
Backward compat: sc.memory(user_id) tetap bekerja seperti v3 API.
"""

from __future__ import annotations
import uuid
import re
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from collections import Counter

if TYPE_CHECKING:
    from .storage.base import BaseStorage
    from .plugins.loader import PluginLoader

from .enums import Tier, NodeKind, NodeStatus, ImportanceDelta
from .context.node import ContextNode


# ── TieredMemory (v4 API baru) ────────────────────────────

class TieredMemory:
    """Akses memory per tier. Ini adalah v4 API."""

    def __init__(self, storage: "BaseStorage", user_id: str):
        self._storage = storage
        self.user_id  = str(user_id)

    @property
    def working(self) -> "TierView":
        return TierView(self._storage, self.user_id, Tier.WORKING)

    @property
    def episodic(self) -> "TierView":
        return TierView(self._storage, self.user_id, Tier.EPISODIC)

    @property
    def semantic(self) -> "TierView":
        return TierView(self._storage, self.user_id, Tier.SEMANTIC)

    def get_all_active(self, limit: int = 50) -> list[ContextNode]:
        results = []
        for tier in Tier:
            nodes = self._storage.get_nodes(
                self.user_id, tier=tier.value,
                status=NodeStatus.ACTIVE.value, limit=limit
            )
            results.extend(nodes)
        return results

    def prune(self):
        """Hapus semua node expired dan deleted."""
        for status in (NodeStatus.EXPIRED.value, NodeStatus.DELETED.value):
            self._storage.delete_nodes(self.user_id, status=status)

    def stats(self) -> dict:
        return {
            "user_id":  self.user_id,
            "working":  self._storage.count_nodes(self.user_id, tier="working"),
            "episodic": self._storage.count_nodes(self.user_id, tier="episodic"),
            "semantic": self._storage.count_nodes(self.user_id, tier="semantic"),
        }

    def __repr__(self):
        s = self.stats()
        return (f"<TieredMemory user={self.user_id!r} "
                f"working={s['working']} episodic={s['episodic']} semantic={s['semantic']}>")


class TierView:
    """View untuk satu tier memory."""

    def __init__(self, storage: "BaseStorage", user_id: str, tier: Tier):
        self._storage = storage
        self.user_id  = user_id
        self.tier     = tier

    def add(self, content: str, kind: NodeKind,
            importance: float = 0.5, source: str = "user",
            tags: list = None, metadata: dict = None) -> ContextNode:
        now  = datetime.now(timezone.utc)
        node = ContextNode(
            user_id    = self.user_id,
            path       = f"/memory/{self.tier.value}/{self.user_id}/{uuid.uuid4().hex[:8]}",
            tier       = self.tier,
            kind       = kind,
            content    = content,
            created_at = now,
            updated_at = now,
            importance = importance,
            source     = source,
            tags       = tags or [],
            metadata   = metadata or {},
        )
        self._storage.save_node(node)
        return node

    def get(self, limit: int = 20) -> list[ContextNode]:
        return self._storage.get_nodes(
            self.user_id, tier=self.tier.value,
            status=NodeStatus.ACTIVE.value, limit=limit
        )

    def count(self) -> int:
        return self._storage.count_nodes(self.user_id, tier=self.tier.value)

    def clear(self):
        self._storage.delete_nodes(self.user_id)

    def __repr__(self):
        return f"<TierView {self.tier.value} user={self.user_id!r} count={self.count()}>"


# ── Memory (v3 backward-compat facade) ───────────────────

class Memory:
    """
    Memory v4 dengan backward compatibility penuh untuk v3 API.

    sc.memory(user_id) tetap bekerja persis seperti sebelumnya.

    Di balik layar:
    - add_user/add_assistant → working tier (ContextNode)
    - get_for_llm() → working messages + episodic summary (blended)
    - profile → tetap di tabel profiles (tidak berubah)
    """

    def __init__(self, storage: "BaseStorage", plugins: "PluginLoader",
                 user_id: str, default_limit: int = 20,
                 compression_config: dict = None):
        self._storage    = storage
        self._plugins    = plugins
        self.user_id     = str(user_id)
        self._limit      = default_limit
        self._comp       = compression_config or {}
        self._local_count: Optional[int] = None

        # v4 API tersedia via .tiered
        self.tiered = TieredMemory(storage, user_id)

    # ── Tambah Pesan (v3 compat) ──────────────────────────

    def add(self, role: str, content: str,
            tags: list = None, metadata: dict = None) -> "Memory":
        tags = tags or []
        meta = metadata or {}

        # Simpan ke working tier sebagai ContextNode
        now  = datetime.now(timezone.utc)
        node = ContextNode(
            user_id    = self.user_id,
            path       = f"/memory/working/{self.user_id}/{uuid.uuid4().hex[:8]}",
            tier       = Tier.WORKING,
            kind       = NodeKind.MESSAGE,
            content    = content,
            created_at = now,
            updated_at = now,
            importance = 0.5,
            source     = role,
            tags       = tags,
            metadata   = {**meta, "role": role},
        )
        self._storage.save_node(node)

        # Plugin hook (backward compat)
        self._plugins.fire_message_saved(self.user_id, role, content, tags, meta)

        # Local counter
        if self._local_count is None:
            self._local_count = self._storage.count_nodes(
                self.user_id, tier="working", status="active"
            )
        else:
            self._local_count += 1

        # Auto-compress
        if self._comp.get("enabled"):
            threshold = self._comp.get("threshold", 50)
            if not hasattr(self, "_next_compress_at"):
                self._next_compress_at = threshold + 1
            if self._local_count >= self._next_compress_at:
                keep = self._comp.get("keep_last", 10)
                self.compress(keep_last=keep)
                self._local_count = self._storage.count_nodes(
                    self.user_id, tier="working", status="active"
                )
                self._next_compress_at = self._local_count + threshold

        return self

    def add_user(self, content: str, tags: list = None,
                 metadata: dict = None) -> "Memory":
        return self.add("user", content, tags, metadata)

    def add_assistant(self, content: str, tags: list = None,
                      metadata: dict = None) -> "Memory":
        return self.add("assistant", content, tags, metadata)

    def add_system(self, content: str, tags: list = None,
                   metadata: dict = None) -> "Memory":
        return self.add("system", content, tags, metadata)

    # ── Ambil Pesan (v3 compat) ───────────────────────────

    def get(self, limit: int = None, tags: list = None) -> list[dict]:
        """Ambil pesan dari working tier, format v3 dict."""
        n     = limit if limit is not None else self._limit
        nodes = self._storage.get_nodes(
            self.user_id, tier=Tier.WORKING.value,
            status=NodeStatus.ACTIVE.value, limit=n,
            order="chronological"
        )
        result = []
        for node in nodes:
            if tags and not any(t in node.tags for t in tags):
                continue
            result.append({
                "role":       node.source,
                "content":    node.content,
                "created_at": node.created_at.isoformat(),
                "tags":       node.tags,
                "metadata":   node.metadata,
            })
        return result

    def get_for_llm(self, limit: int = None,
                    tags: list = None) -> list[dict]:
        """
        Ambil history untuk LLM.
        Blended: episodic summary (kalau ada) + working messages.
        Sudah diproses plugin on_context_build.
        """
        messages = self.get(limit, tags)
        clean    = [{"role": m["role"], "content": m["content"]} for m in messages]

        # Inject episodic summary di awal kalau ada
        episodic_nodes = self._storage.get_nodes(
            self.user_id,
            tier   = Tier.EPISODIC.value,
            kind   = NodeKind.SUMMARY.value,
            status = NodeStatus.ACTIVE.value,
            limit  = 1,
        )
        if episodic_nodes:
            clean = [{"role": "system",
                      "content": f"[RINGKASAN SESI SEBELUMNYA]\n{episodic_nodes[0].content}"}
                     ] + clean

        return self._plugins.fire_context_build(self.user_id, clean)

    def search(self, keyword: str, limit: int = 5) -> list[dict]:
        nodes = self._storage.search_nodes(
            self.user_id, keyword, tier=Tier.WORKING.value, limit=limit
        )
        return [{"role": n.source, "content": n.content} for n in nodes]

    def last(self, n: int = 1, tags: list = None) -> list[dict]:
        return self.get(n, tags)

    # ── Profil (tidak berubah dari v3) ────────────────────

    def remember(self, key: str, value) -> "Memory":
        self._storage.update_profile(self.user_id, key, value)
        return self

    def recall(self, key: str, default=None):
        return self._storage.get_profile(self.user_id).get(key, default)

    def get_profile(self) -> dict:
        return self._storage.get_profile(self.user_id)

    def set_profile(self, data: dict) -> "Memory":
        self._storage.set_profile(self.user_id, data)
        return self

    def update_profile(self, updates: dict) -> "Memory":
        profile = self.get_profile()
        profile.update(updates)
        self._storage.set_profile(self.user_id, profile)
        return self

    # ── Compression ───────────────────────────────────────

    def compress(self, keep_last: int = None) -> str:
        """
        Kompres working memory:
        - Pesan lama → summary → simpan ke episodic tier
        - N pesan terbaru tetap di working
        """
        keep  = keep_last or self._comp.get("keep_last", 10)
        nodes = self._storage.get_nodes(
            self.user_id, tier=Tier.WORKING.value,
            status=NodeStatus.ACTIVE.value, limit=999999
        )
        if len(nodes) <= keep:
            return ""

        old_nodes  = nodes[:-keep]
        msgs       = [{"role": n.source, "content": n.content} for n in old_nodes]
        summary    = _summarize(msgs)

        # Soft delete pesan lama
        for n in old_nodes:
            self._storage.update_node_status(n.id, NodeStatus.DELETED.value)

        # Simpan summary ke episodic tier
        now = datetime.now(timezone.utc)
        summary_node = ContextNode(
            user_id    = self.user_id,
            path       = f"/memory/episodic/{self.user_id}/{uuid.uuid4().hex[:8]}",
            tier       = Tier.EPISODIC,
            kind       = NodeKind.SUMMARY,
            content    = summary,
            created_at = now,
            updated_at = now,
            importance = 0.7,
            source     = "system",
            tags       = ["compressed", "summary"],
            metadata   = {"original_count": len(old_nodes)},
        )
        self._storage.save_node(summary_node)
        self._local_count = None
        return summary

    # ── Clear & Utils ─────────────────────────────────────

    def clear(self, tags: list = None) -> "Memory":
        if tags is None:
            self._storage.delete_nodes(self.user_id)
            self._local_count = 0
        else:
            nodes = self._storage.get_nodes(
                self.user_id, status=NodeStatus.ACTIVE.value, limit=999999
            )
            for n in nodes:
                if any(t in n.tags for t in tags):
                    self._storage.update_node_status(n.id, NodeStatus.DELETED.value)
            self._local_count = None
        self._plugins.fire_messages_cleared(self.user_id)
        return self

    def count(self) -> int:
        if self._local_count is not None:
            return self._local_count
        return self._storage.count_nodes(
            self.user_id, tier="working", status="active"
        )

    def build_context_string(self, limit: int = None,
                              include_profile: bool = True) -> str:
        parts = []
        if include_profile:
            profile = self.get_profile()
            if profile:
                parts.append("=== PROFIL USER ===")
                for k, v in profile.items():
                    parts.append(f"- {k}: {v}")
                parts.append("")
        messages = self.get(limit)
        if messages:
            parts.append("=== RIWAYAT PERCAKAPAN ===")
            for m in messages:
                prefix = "User" if m["role"] == "user" else "Assistant"
                parts.append(f"{prefix}: {m['content'][:300]}")
        return "\n".join(parts)

    def summary(self) -> dict:
        return {
            "user_id":        self.user_id,
            "total_messages": self.count(),
            "profile_keys":   list(self.get_profile().keys()),
        }

    def __repr__(self):
        return f"<Memory user_id={self.user_id!r} messages={self.count()}>"


# ── Compression helper ────────────────────────────────────

def _summarize(messages: list[dict]) -> str:
    if not messages:
        return ""
    stopwords = {
        "yang","dan","di","ke","dari","ini","itu","dengan","untuk","adalah",
        "ada","saya","kamu","aku","the","a","an","is","i","you","to","of",
        "bisa","mau","sudah","belum","tidak","bukan",
    }
    user_texts = [m["content"] for m in messages if m.get("role") == "user"]
    asst_texts = [m["content"] for m in messages if m.get("role") == "assistant"]
    all_words  = []
    for text in user_texts:
        words = re.findall(r'\b[a-zA-Z\u00C0-\u024F]{3,}\b', text.lower())
        all_words.extend([w for w in words if w not in stopwords])
    top_topics = [w for w, _ in Counter(all_words).most_common(5)]
    lines      = [f"Percakapan terdiri dari {len(messages)} pesan."]
    if top_topics:
        lines.append(f"Topik: {', '.join(top_topics)}.")
    if user_texts:
        lines.append(f"Pertanyaan awal: \"{user_texts[0][:100]}\"")
        if len(user_texts) > 1:
            lines.append(f"Pertanyaan terakhir: \"{user_texts[-1][:100]}\"")
    if asst_texts:
        lines.append(f"Respons terakhir: \"{asst_texts[-1][:150]}\"")
    return "\n".join(lines)
