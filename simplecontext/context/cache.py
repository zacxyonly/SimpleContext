"""
context/cache.py — ContextCache
LRU cache sederhana untuk hasil retrieval.
TTL default 30 detik — mengurangi query SQLite untuk percakapan cepat.
Zero external dependencies.
"""

from __future__ import annotations
import hashlib
import time
from typing import Optional


class ContextCache:
    """
    LRU Cache untuk hasil ContextEngine.retrieve().
    Key: hash dari (user_id + query + intent).
    Value: list ContextNode.
    """

    def __init__(self, ttl_seconds: int = 30, max_size: int = 50):
        """
        Args:
            ttl_seconds: berapa lama cache entry valid
            max_size:    maksimal jumlah entry (LRU eviction)
        """
        self._ttl      = ttl_seconds
        self._max_size = max_size
        self._cache: dict[str, tuple[float, list]] = {}  # key → (timestamp, nodes)
        self._order: list[str] = []  # untuk LRU tracking

    def get(self, key: str) -> Optional[list]:
        """Return cached nodes atau None kalau miss/expired."""
        if key not in self._cache:
            return None
        ts, nodes = self._cache[key]
        if time.time() - ts > self._ttl:
            # Expired
            del self._cache[key]
            if key in self._order:
                self._order.remove(key)
            return None
        # LRU: pindah ke akhir (most recently used)
        if key in self._order:
            self._order.remove(key)
        self._order.append(key)
        return nodes

    def set(self, key: str, nodes: list):
        """Simpan nodes ke cache."""
        # Evict LRU kalau penuh
        while len(self._cache) >= self._max_size and self._order:
            lru_key = self._order.pop(0)
            self._cache.pop(lru_key, None)

        self._cache[key] = (time.time(), nodes)
        if key in self._order:
            self._order.remove(key)
        self._order.append(key)

    def invalidate(self, user_id: str):
        """Hapus semua cache entry untuk user tertentu."""
        to_delete = [k for k in self._cache if k.startswith(user_id + ":")]
        for k in to_delete:
            del self._cache[k]
            if k in self._order:
                self._order.remove(k)

    def clear(self):
        """Hapus semua cache."""
        self._cache.clear()
        self._order.clear()

    @property
    def size(self) -> int:
        return len(self._cache)

    @staticmethod
    def make_key(user_id: str, query: str, intent: str) -> str:
        """Buat cache key dari user_id + query + intent."""
        raw = f"{user_id}:{query.lower().strip()}:{intent}"
        return user_id + ":" + hashlib.md5(raw.encode()).hexdigest()[:12]

    def __repr__(self):
        return f"<ContextCache size={self.size} ttl={self._ttl}s>"
