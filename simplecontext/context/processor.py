"""
context/processor.py v4.1 — MemoryProcessor
Perbaikan:
- Fact extraction patterns lebih lengkap dan akurat
- Normalized fact format: "user uses X", "user name X", dll
- Safety limit: max node content length
- Importance decay method
"""

from __future__ import annotations
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..storage.base import BaseStorage
    from .node import ContextNode

from ..enums import Tier, NodeKind, NodeStatus, ImportanceDelta
from .node import ContextNode

# Safety limit: node content tidak boleh lebih dari ini
MAX_NODE_CONTENT = 1000


@dataclass
class ProcessTurn:
    """Satu turn percakapan yang akan diproses."""
    user_id:            str
    user_message:       str
    assistant_response: str
    agent_id:           str  = "general"
    used_nodes:         list = None
    runtime_state:      dict = None


class MemoryProcessor:
    """Proses turn percakapan → extract → store → update importance."""

    MAX_TOKENS_FOR_DEDUP = 20
    DEDUP_THRESHOLD      = 0.65
    CONFLICT_THRESHOLD   = 0.65

    # ── Fact extraction rules ─────────────────────────────
    # Format: (pattern, template)
    # template menggunakan group(1) dari pattern
    # Hasil fact selalu dalam format normalized: "user X Y"

    FACT_RULES: list[tuple[str, str]] = [
        # Nama user
        (r"(?:nama\s+(?:saya|aku)|my\s+name\s+is|nama\s+ku)\s+([A-Za-z0-9_\- ]{2,30}?)(?:[.,!?\n]|$)",
         "user name {}"),

        # Tools/stack/bahasa yang dipakai
        (r"(?:saya|aku|i)\s+(?:pakai|menggunakan|memakai|use|using)\s+([A-Za-z0-9_\-\. ]{2,40}?)(?:\s+untuk|\s+for|[.,!?\n]|$)",
         "user uses {}"),

        # Preferensi suka
        (r"(?:saya|aku|i)\s+(?:suka|like|prefer|senang\s+dengan)\s+([A-Za-z0-9_\-\. ]{2,40}?)(?:[.,!?\n]|$)",
         "user likes {}"),

        # Project user
        (r"(?:project|proyek|app|aplikasi)\s+(?:saya|aku|ku|my)\s+(?:adalah\s+|is\s+)?([A-Za-z0-9_\-\. ]{2,40}?)(?:[.,!?\n]|$)",
         "user project {}"),
        (r"(?:saya|aku|i)\s+(?:lagi\s+)?(?:buat|membuat|building|developing|working on)\s+([A-Za-z0-9_\-\. ]{2,40}?)(?:[.,!?\n]|$)",
         "user building {}"),

        # Server/infra
        (r"(?:server|vps|hosting|infra)\s+(?:saya|aku|ku|my)\s+(?:pakai\s+|menggunakan\s+|is\s+|uses?\s+)?([A-Za-z0-9_\-\. ]{2,30}?)(?:[.,!?\n]|$)",
         "user server {}"),

        # OS/platform
        (r"(?:saya|aku|i)\s+(?:pakai|menggunakan|use|using|run(?:ning)?)\s+(linux|ubuntu|debian|windows|macos|proxmox|arch[A-Za-z]*)(?:[.,!?\n ]|$)",
         "user uses {}"),

        # Stack/framework
        (r"(?:stack|framework|backend|frontend)\s+(?:saya|aku|ku|my)\s+(?:adalah\s+|is\s+)?([A-Za-z0-9_\-\. ]{2,40}?)(?:[.,!?\n]|$)",
         "user stack {}"),

        # Level/jabatan
        (r"(?:saya|aku|i)\s+(?:adalah|am|seorang?)\s+(?:a\s+)?([A-Za-z ]{3,40}?)(?:[.,!?\n]|$)",
         "user is {}"),
    ]

    def __init__(self, storage: "BaseStorage"):
        self._storage = storage

    def process(self, turn: ProcessTurn) -> list[ContextNode]:
        """Proses satu turn dan return list node yang disimpan."""
        stored: list[ContextNode] = []
        uid = turn.user_id

        # 1. Simpan pesan ke working memory
        msg_nodes = self._store_messages(turn)
        stored.extend(msg_nodes)

        # 2. Extract + process facts dari pesan USER saja
        # (lebih reliable dari response assistant)
        user_facts = self._extract_facts(turn.user_message)
        for fact_content in user_facts:
            node = self._process_fact(uid, fact_content, "user", turn)
            if node:
                stored.append(node)

        # 3. Update importance untuk nodes yang dipakai
        if turn.used_nodes:
            self._update_used_importance(turn.used_nodes)

        # 4. Simpan task_state kalau ada
        if turn.runtime_state and turn.runtime_state.get("task_state"):
            ts_node = self._store_task_state(uid, turn)
            if ts_node:
                stored.append(ts_node)

        return stored

    # ── Message storage ───────────────────────────────────

    def _store_messages(self, turn: ProcessTurn) -> list[ContextNode]:
        nodes = []
        uid   = turn.user_id
        now   = datetime.now(timezone.utc)

        for role, content in [("user", turn.user_message),
                               ("assistant", turn.assistant_response)]:
            # Safety limit
            safe_content = _truncate(content, MAX_NODE_CONTENT)
            node = ContextNode(
                user_id    = uid,
                path       = f"/memory/working/{uid}/{uuid.uuid4().hex[:8]}",
                tier       = Tier.WORKING,
                kind       = NodeKind.MESSAGE,
                content    = safe_content,
                created_at = now,
                updated_at = now,
                importance = 0.5,
                source     = role,
                tags       = ["message"],
                metadata   = {"agent_id": turn.agent_id},
            )
            self._storage.save_node(node)
            nodes.append(node)

        return nodes

    # ── Fact extraction ───────────────────────────────────

    def _extract_facts(self, text: str) -> list[str]:
        """
        Ekstrak fakta dari teks menggunakan rules yang sudah didefinisikan.
        Return list fact dalam format normalized: "user uses X", "user name X", dll.
        """
        facts: list[str] = []
        text_lower = text.lower().strip()

        for pattern, template in self.FACT_RULES:
            for m in re.finditer(pattern, text_lower):
                extracted = m.group(1).strip().rstrip(".,!? ")
                if not extracted or len(extracted) < 2:
                    continue
                # Normalize: hapus kata umum yang tidak bermakna
                if extracted in {"itu","ini","yang","ada","dan","atau","juga"}:
                    continue
                # Format fact normalized
                fact = template.format(extracted)
                # Validasi panjang token
                tokens = fact.split()
                if 3 <= len(tokens) <= self.MAX_TOKENS_FOR_DEDUP:
                    if fact not in facts:
                        facts.append(fact)

        return facts[:6]  # max 6 facts per turn

    # ── Fact processing ───────────────────────────────────

    def _process_fact(self, user_id: str, content: str,
                      source: str, turn: ProcessTurn) -> ContextNode | None:
        """Proses satu fakta: dedup → conflict resolve → store."""
        tokens = content.split()
        if len(tokens) > self.MAX_TOKENS_FOR_DEDUP:
            return None

        # Ambil existing semantic facts
        existing_facts = self._storage.get_nodes(
            user_id,
            tier   = Tier.SEMANTIC.value,
            kind   = NodeKind.FACT.value,
            status = NodeStatus.ACTIVE.value,
            limit  = 100,
        )

        supersede_id = None
        for existing in existing_facts:
            if len(existing.content.split()) > self.MAX_TOKENS_FOR_DEDUP:
                continue
            sim = _jaccard(content, existing.content)
            if sim >= self.DEDUP_THRESHOLD:
                new_confidence = 0.9
                if new_confidence >= existing.confidence:
                    # Supersede existing
                    supersede_id = existing.id
                    existing.supersede_by("pending")
                    self._storage.update_node_status(
                        existing.id, NodeStatus.SUPERSEDED.value
                    )
                    self._storage.update_node_importance(
                        existing.id,
                        max(0.0, existing.importance + ImportanceDelta.SUPERSEDED)
                    )
                    break
                else:
                    return None  # existing lebih reliable

        # Store fact baru
        now  = datetime.now(timezone.utc)
        node = ContextNode(
            user_id    = user_id,
            path       = f"/memory/semantic/{user_id}/{uuid.uuid4().hex[:8]}",
            tier       = Tier.SEMANTIC,
            kind       = NodeKind.FACT,
            content    = content,
            created_at = now,
            updated_at = now,
            importance = 0.7,
            confidence = 0.9,
            source     = source,
            tags       = ["fact"],
            metadata   = {
                "agent_id": turn.agent_id,
                **({"supersedes": supersede_id} if supersede_id else {}),
            },
        )
        node.update_importance(ImportanceDelta.NEW_FACT_FROM_USER)
        self._storage.save_node(node)
        return node

    # ── Task state ────────────────────────────────────────

    def _store_task_state(self, user_id: str,
                          turn: ProcessTurn) -> ContextNode | None:
        state_content = str(turn.runtime_state.get("task_state", ""))
        if not state_content:
            return None
        safe = _truncate(state_content, MAX_NODE_CONTENT)
        now  = datetime.now(timezone.utc)
        node = ContextNode(
            user_id    = user_id,
            path       = f"/memory/working/{user_id}/task_state",
            tier       = Tier.WORKING,
            kind       = NodeKind.TASK_STATE,
            content    = safe,
            created_at = now,
            updated_at = now,
            importance = 0.8,
            source     = "system",
            tags       = ["task_state"],
        )
        self._storage.save_node(node)
        return node

    # ── Importance update ─────────────────────────────────

    def _update_used_importance(self, used_nodes: list):
        for node in used_nodes:
            if hasattr(node, "id") and hasattr(node, "importance"):
                new_imp = min(1.0, node.importance + ImportanceDelta.USED_IN_RETRIEVAL)
                self._storage.update_node_importance(node.id, new_imp)

    # ── Importance decay ──────────────────────────────────

    def apply_decay(self, user_id: str):
        """
        Terapkan importance decay ke semua active nodes user.
        Panggil secara periodik (misal setiap hari atau setiap sesi).
        Node dengan importance mendekati 0 akan di-soft-expire.
        """
        nodes = self._storage.get_nodes(
            user_id, status=NodeStatus.ACTIVE.value, limit=999999
        )
        for node in nodes:
            new_imp = max(0.0, node.importance + ImportanceDelta.DAILY_DECAY)
            self._storage.update_node_importance(node.id, new_imp)
            # Auto-expire kalau importance terlalu rendah
            if new_imp <= 0.05:
                self._storage.update_node_status(node.id, NodeStatus.EXPIRED.value)


# ── Helpers ───────────────────────────────────────────────

def _jaccard(a: str, b: str) -> float:
    sa = set(a.lower().split())
    sb = set(b.lower().split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)

def _truncate(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 3].rstrip() + "..."


# ── Smart Compression ─────────────────────────────────────

class SmartCompressor:
    """
    Compress percakapan dengan semantic chunking.
    Deteksi pergantian topik tanpa LLM — pakai Jaccard similarity.
    """

    def __init__(self, storage: "BaseStorage"):
        self._storage = storage

    def smart_compress(self, user_id: str,
                       strategy: str = "semantic",
                       keep_last: int = 5) -> list:
        """
        Compress working memory dengan strategi yang dipilih.

        strategy:
        - "semantic" : pisah berdasarkan topik (Jaccard similarity)
        - "time"     : per session/jam
        - "token"    : berdasarkan estimasi token count

        Return: list ContextNode summary yang disimpan ke episodic.
        """
        from ..enums import Tier, NodeKind, NodeStatus
        from .node import ContextNode
        import uuid
        from datetime import datetime, timezone

        nodes = self._storage.get_nodes(
            user_id, tier=Tier.WORKING.value,
            kind=NodeKind.MESSAGE.value,
            status=NodeStatus.ACTIVE.value,
            limit=999999,
            order="chronological",
        )

        if len(nodes) <= keep_last:
            return []

        old_nodes = nodes[:-keep_last]

        if strategy == "semantic":
            chunks = self._semantic_chunks(old_nodes)
        elif strategy == "time":
            chunks = self._time_chunks(old_nodes)
        elif strategy == "token":
            chunks = self._token_chunks(old_nodes, max_tokens=500)
        else:
            chunks = [old_nodes]

        stored = []
        now = datetime.now(timezone.utc)

        for chunk in chunks:
            if not chunk:
                continue
            topic   = self._detect_chunk_topic(chunk)
            summary = self._summarize_chunk(chunk)

            node = ContextNode(
                user_id    = user_id,
                path       = f"/memory/episodic/{user_id}/{uuid.uuid4().hex[:8]}",
                tier       = Tier.EPISODIC,
                kind       = NodeKind.SUMMARY,
                content    = summary,
                created_at = now,
                updated_at = now,
                importance = 0.7,
                source     = "system",
                tags       = ["compressed", "summary", strategy],
                metadata   = {
                    "topic":          topic,
                    "original_count": len(chunk),
                    "strategy":       strategy,
                },
            )
            self._storage.save_node(node)
            stored.append(node)

            # Soft-delete pesan lama
            for n in chunk:
                from ..enums import NodeStatus
                self._storage.update_node_status(n.id, NodeStatus.DELETED.value)

        return stored

    def _semantic_chunks(self, nodes: list,
                          similarity_threshold: float = 0.25) -> list[list]:
        """
        Pisah nodes berdasarkan topik.
        Kalau Jaccard similarity antara dua pesan berurutan < threshold,
        anggap topik berganti → buat chunk baru.
        """
        if not nodes:
            return []

        chunks = [[nodes[0]]]
        for i in range(1, len(nodes)):
            prev = nodes[i - 1].content
            curr = nodes[i].content
            sim  = _jaccard_sim(prev, curr)
            if sim < similarity_threshold:
                chunks.append([nodes[i]])  # topik baru
            else:
                chunks[-1].append(nodes[i])
        return chunks

    def _time_chunks(self, nodes: list,
                     gap_hours: float = 2.0) -> list[list]:
        """Pisah nodes berdasarkan gap waktu antar pesan."""
        from datetime import timezone
        if not nodes:
            return []

        chunks = [[nodes[0]]]
        for i in range(1, len(nodes)):
            prev_dt = nodes[i - 1].created_at
            curr_dt = nodes[i].created_at
            if prev_dt.tzinfo is None:
                prev_dt = prev_dt.replace(tzinfo=timezone.utc)
            if curr_dt.tzinfo is None:
                curr_dt = curr_dt.replace(tzinfo=timezone.utc)
            gap = (curr_dt - prev_dt).total_seconds() / 3600
            if gap > gap_hours:
                chunks.append([nodes[i]])
            else:
                chunks[-1].append(nodes[i])
        return chunks

    def _token_chunks(self, nodes: list,
                      max_tokens: int = 500) -> list[list]:
        """Pisah nodes berdasarkan estimasi token (4 chars ≈ 1 token)."""
        chunks = [[]]
        current_tokens = 0
        for node in nodes:
            est_tokens = len(node.content) // 4
            if current_tokens + est_tokens > max_tokens and chunks[-1]:
                chunks.append([])
                current_tokens = 0
            chunks[-1].append(node)
            current_tokens += est_tokens
        return [c for c in chunks if c]

    def _detect_chunk_topic(self, chunk: list) -> str:
        """Deteksi topik dominan dari chunk menggunakan TF-IDF sederhana."""
        import re
        from collections import Counter
        stopwords = {
            "yang","dan","di","ke","dari","ini","itu","dengan","untuk",
            "saya","aku","bisa","the","a","an","i","you","to","is","are",
        }
        all_words = []
        for node in chunk:
            words = re.findall(r'\b[a-zA-Z\u00C0-\u024F]{3,}\b',
                               node.content.lower())
            all_words.extend([w for w in words if w not in stopwords])
        if not all_words:
            return "general"
        return Counter(all_words).most_common(1)[0][0]

    def _summarize_chunk(self, chunk: list) -> str:
        """Generate summary ringkas dari chunk."""
        from collections import Counter
        import re

        user_msgs = [n.content for n in chunk if n.source == "user"]
        asst_msgs = [n.content for n in chunk if n.source == "assistant"]

        stopwords = {
            "yang","dan","di","ke","dari","ini","itu","dengan","untuk",
            "saya","aku","the","a","an","i","you","to","is","are","it",
        }
        all_words = []
        for text in user_msgs:
            words = re.findall(r'\b[a-zA-Z\u00C0-\u024F]{3,}\b', text.lower())
            all_words.extend([w for w in words if w not in stopwords])
        top_words = [w for w, _ in Counter(all_words).most_common(4)]

        lines = [f"Percakapan {len(chunk)} pesan."]
        if top_words:
            lines.append(f"Topik: {', '.join(top_words)}.")
        if user_msgs:
            lines.append(f"Pertanyaan: \"{user_msgs[0][:100]}\"")
        if asst_msgs:
            lines.append(f"Respons: \"{asst_msgs[-1][:100]}\"")
        return "\n".join(lines)


def _jaccard_sim(a: str, b: str) -> float:
    import re
    wa = set(re.findall(r'\b\w{2,}\b', a.lower()))
    wb = set(re.findall(r'\b\w{2,}\b', b.lower()))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)
