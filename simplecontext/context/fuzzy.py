"""
context/fuzzy.py — Fuzzy Search & Misspelling Tolerance
Pure Python Levenshtein distance, zero dependencies.
"""

from __future__ import annotations
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .node import ContextNode


def levenshtein(a: str, b: str) -> int:
    """Hitung Levenshtein distance antara dua string."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    # Pakai rolling array untuk hemat memori
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            curr[j] = min(
                prev[j] + 1,           # delete
                curr[j - 1] + 1,       # insert
                prev[j - 1] + (ca != cb),  # replace
            )
        prev = curr
    return prev[-1]


def levenshtein_ratio(a: str, b: str) -> float:
    """Return similarity ratio 0.0–1.0 (1.0 = identical)."""
    if not a and not b:
        return 1.0
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    return 1.0 - levenshtein(a, b) / max_len


def fuzzy_word_match(query_word: str, text_words: list[str],
                     threshold: float = 0.80) -> tuple[bool, float]:
    """
    Cek apakah query_word punya fuzzy match di text_words.
    Return (matched, best_score).
    """
    best = 0.0
    for w in text_words:
        score = levenshtein_ratio(query_word, w)
        if score > best:
            best = score
    return best >= threshold, best


def fuzzy_match_score(query: str, text: str,
                      threshold: float = 0.80) -> float:
    """
    Hitung fuzzy match score antara query dan text.
    Return nilai 0.0–1.0.

    Cara kerja:
    - Split keduanya jadi kata
    - Tiap kata query dicari match terbaik di text (exact atau fuzzy)
    - Score = proporsi kata query yang match
    """
    if not query or not text:
        return 0.0

    query_words = _tokenize(query)
    text_words  = _tokenize(text)

    if not query_words or not text_words:
        return 0.0

    matched = 0
    total_score = 0.0

    for qw in query_words:
        # Cek exact match dulu (lebih cepat)
        if qw in text_words:
            matched += 1
            total_score += 1.0
        else:
            found, score = fuzzy_word_match(qw, text_words, threshold)
            if found:
                matched += 1
                total_score += score

    # Score = rata-rata score kata yang match × proporsi kata yang match
    if matched == 0:
        return 0.0
    avg_score  = total_score / len(query_words)
    proportion = matched / len(query_words)
    return avg_score * proportion


class FuzzyRetriever:
    """
    Wrapper untuk fuzzy search di atas storage.
    Dipakai sebagai fallback saat exact keyword search tidak cukup.
    """

    def __init__(self, storage, threshold: float = 0.80):
        self._storage  = storage
        self.threshold = threshold

    def search(self, user_id: str, query: str,
               tier: str = None, limit: int = 10) -> list["ContextNode"]:
        """
        Fuzzy search nodes — match meski ada typo.
        Lebih lambat dari exact search, tapi lebih toleran.
        """
        # Ambil candidates dari storage
        candidates = self._storage.get_nodes(
            user_id, tier=tier, status="active", limit=500
        )
        if not candidates:
            return []

        scored: list[tuple[float, "ContextNode"]] = []
        for node in candidates:
            score = fuzzy_match_score(query, node.content, self.threshold)
            if score > 0:
                scored.append((score, node))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [n for _, n in scored[:limit]]

    def is_likely_typo(self, word: str, vocabulary: list[str]) -> tuple[bool, str]:
        """
        Cek apakah word kemungkinan typo dari salah satu kata di vocabulary.
        Return (is_typo, suggested_correction).
        """
        if word in vocabulary:
            return False, word
        best_word  = word
        best_score = 0.0
        for v in vocabulary:
            score = levenshtein_ratio(word, v)
            if score > best_score:
                best_score = score
                best_word  = v
        return best_score >= self.threshold, best_word


def _tokenize(text: str) -> list[str]:
    words = re.findall(r'\b[a-zA-Z0-9\u00C0-\u024F]{2,}\b', text.lower())
    stopwords = {
        "yang","dan","di","ke","dari","ini","itu","dengan","untuk",
        "the","a","an","is","are","i","you","to","of","in","it",
    }
    return [w for w in words if w not in stopwords]
