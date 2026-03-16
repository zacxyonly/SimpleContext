"""
context/graph.py — Memory Graph & Relationships
Simpan relasi antar ContextNode di SQLite.
Zero dependencies.
"""

from __future__ import annotations
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..storage.base import BaseStorage


# Tipe relasi yang valid
REL_TYPES = {
    "related_to",    # fakta yang berkaitan
    "causes",        # A menyebabkan B
    "part_of",       # A adalah bagian dari B
    "contradicts",   # A bertentangan dengan B
    "precedes",      # A terjadi sebelum B (temporal)
    "supports",      # A mendukung/memperkuat B
}


@dataclass
class Relationship:
    """Relasi antara dua ContextNode."""
    source_id:  str
    target_id:  str
    rel_type:   str           # dari REL_TYPES
    strength:   float = 1.0  # 0.0 – 1.0
    id:         str   = None
    created_at: str   = None
    metadata:   dict  = None

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if self.metadata is None:
            self.metadata = {}
        self.strength = max(0.0, min(1.0, self.strength))
        if self.rel_type not in REL_TYPES:
            raise ValueError(
                f"Invalid rel_type {self.rel_type!r}. Valid: {REL_TYPES}"
            )

    def to_dict(self) -> dict:
        import json
        return {
            "id":         self.id,
            "source_id":  self.source_id,
            "target_id":  self.target_id,
            "rel_type":   self.rel_type,
            "strength":   self.strength,
            "created_at": self.created_at,
            "metadata":   json.dumps(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Relationship":
        import json
        meta = d.get("metadata", "{}")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        return cls(
            id         = d["id"],
            source_id  = d["source_id"],
            target_id  = d["target_id"],
            rel_type   = d["rel_type"],
            strength   = float(d.get("strength", 1.0)),
            created_at = d.get("created_at", ""),
            metadata   = meta,
        )


class GraphStore:
    """
    Store dan query relationships antar ContextNode.
    Pakai tabel context_relationships di SQLite yang sama.
    """

    def __init__(self, storage: "BaseStorage"):
        self._storage = storage
        self._ensure_table()

    def _ensure_table(self):
        """Buat tabel relationships kalau belum ada."""
        conn = self._storage._conn
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS context_relationships (
                id         TEXT PRIMARY KEY,
                source_id  TEXT NOT NULL,
                target_id  TEXT NOT NULL,
                rel_type   TEXT NOT NULL,
                strength   REAL DEFAULT 1.0,
                created_at TEXT NOT NULL,
                metadata   TEXT DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_rel_source ON context_relationships(source_id);
            CREATE INDEX IF NOT EXISTS idx_rel_target ON context_relationships(target_id);
            CREATE INDEX IF NOT EXISTS idx_rel_type   ON context_relationships(rel_type);
        """)
        conn.commit()

    def add(self, rel: Relationship) -> Relationship:
        """Simpan relationship baru."""
        d = rel.to_dict()
        self._storage._conn.execute("""
            INSERT OR REPLACE INTO context_relationships
                (id, source_id, target_id, rel_type, strength, created_at, metadata)
            VALUES (?,?,?,?,?,?,?)
        """, (d["id"], d["source_id"], d["target_id"], d["rel_type"],
              d["strength"], d["created_at"], d["metadata"]))
        self._storage._conn.commit()
        return rel

    def link(self, source_id: str, target_id: str,
             rel_type: str, strength: float = 1.0,
             metadata: dict = None) -> Relationship:
        """Shortcut — buat dan simpan relationship sekaligus."""
        rel = Relationship(
            source_id = source_id,
            target_id = target_id,
            rel_type  = rel_type,
            strength  = strength,
            metadata  = metadata or {},
        )
        return self.add(rel)

    def get_related(self, node_id: str,
                    rel_type: str = None,
                    direction: str = "both") -> list[Relationship]:
        """
        Ambil semua relationships dari/ke node_id.
        direction: "out" (source), "in" (target), "both"
        """
        conn    = self._storage._conn
        results = []

        if direction in ("out", "both"):
            q = "SELECT * FROM context_relationships WHERE source_id=?"
            p = [node_id]
            if rel_type:
                q += " AND rel_type=?"
                p.append(rel_type)
            rows = conn.execute(q, p).fetchall()
            results += [Relationship.from_dict(dict(r)) for r in rows]

        if direction in ("in", "both"):
            q = "SELECT * FROM context_relationships WHERE target_id=?"
            p = [node_id]
            if rel_type:
                q += " AND rel_type=?"
                p.append(rel_type)
            rows = conn.execute(q, p).fetchall()
            results += [Relationship.from_dict(dict(r)) for r in rows]

        return results

    def get_neighbors(self, node_id: str,
                      rel_type: str = None) -> list[str]:
        """Return list node_id yang terhubung dengan node_id ini."""
        rels = self.get_related(node_id, rel_type, direction="both")
        neighbors = set()
        for r in rels:
            if r.source_id == node_id:
                neighbors.add(r.target_id)
            else:
                neighbors.add(r.source_id)
        return list(neighbors)

    def get_path(self, start_id: str, end_id: str,
                 max_hops: int = 3) -> list[list[str]]:
        """
        Cari path antara dua node (BFS, max_hops langkah).
        Return list of paths, tiap path adalah list node_id.
        """
        if start_id == end_id:
            return [[start_id]]

        visited: set[str] = set()
        queue: list[list[str]] = [[start_id]]
        paths: list[list[str]] = []

        while queue:
            path = queue.pop(0)
            node = path[-1]

            if len(path) > max_hops + 1:
                continue

            if node in visited:
                continue
            visited.add(node)

            neighbors = self.get_neighbors(node)
            for neighbor in neighbors:
                new_path = path + [neighbor]
                if neighbor == end_id:
                    paths.append(new_path)
                else:
                    queue.append(new_path)

        return paths

    def delete_node_relationships(self, node_id: str):
        """Hapus semua relationships yang melibatkan node_id."""
        self._storage._conn.execute(
            "DELETE FROM context_relationships WHERE source_id=? OR target_id=?",
            (node_id, node_id)
        )
        self._storage._conn.commit()

    def summary(self, user_id: str = None) -> dict:
        """Stats ringkas tentang graph."""
        conn = self._storage._conn
        total = conn.execute(
            "SELECT COUNT(*) FROM context_relationships"
        ).fetchone()[0]
        by_type = {}
        rows = conn.execute(
            "SELECT rel_type, COUNT(*) FROM context_relationships GROUP BY rel_type"
        ).fetchall()
        for row in rows:
            by_type[row[0]] = row[1]
        return {"total_relationships": total, "by_type": by_type}

    def auto_link(self, new_node, existing_nodes: list,
                  threshold: float = 0.65) -> list[Relationship]:
        """
        Otomatis buat relationships berdasarkan Jaccard similarity.
        Nodes dengan similarity tinggi → related_to.
        """
        from .fuzzy import fuzzy_match_score
        created = []
        for existing in existing_nodes:
            if existing.id == new_node.id:
                continue
            score = fuzzy_match_score(new_node.content, existing.content)
            if score >= threshold:
                # Deteksi apakah contradicts (ada kata negasi)
                rel_type = _detect_rel_type(new_node.content, existing.content)
                rel = self.link(
                    source_id = new_node.id,
                    target_id = existing.id,
                    rel_type  = rel_type,
                    strength  = score,
                )
                created.append(rel)
        return created


def _detect_rel_type(content_a: str, content_b: str) -> str:
    """Heuristik sederhana untuk mendeteksi tipe relasi."""
    negations = {"tidak", "bukan", "ganti", "diganti", "pindah", "sudah tidak",
                 "no longer", "not", "changed", "switched", "moved"}
    causes    = {"karena", "menyebabkan", "because", "causes", "due to", "hasil"}
    parts     = {"bagian", "part of", "termasuk", "includes", "contains"}

    combined = (content_a + " " + content_b).lower()
    if any(w in combined for w in negations):
        return "contradicts"
    if any(w in combined for w in causes):
        return "causes"
    if any(w in combined for w in parts):
        return "part_of"
    return "related_to"
