"""
context/patterns.py — Pattern Detection
Deteksi pola berulang dari interaksi user.
Pure Python, zero dependencies.
"""

from __future__ import annotations
import re
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..storage.base import BaseStorage


class PatternDetector:
    """
    Deteksi pola dari riwayat interaksi user.
    Semua analisis berbasis rule + statistik sederhana — zero dep.
    """

    def __init__(self, storage: "BaseStorage"):
        self._storage = storage

    def detect(self, user_id: str,
               time_window_days: int = 7) -> dict:
        """
        Deteksi semua pola untuk user dalam time window.

        Return dict berisi:
        - peak_hours: jam-jam user paling aktif
        - topics_frequency: frekuensi topik yang dibahas
        - common_questions: pertanyaan yang sering diulang
        - sentiment_trend: tren positif/negatif/netral
        - activity_streak: berapa hari berturut-turut aktif
        - most_used_agent: agent yang paling sering dipakai
        """
        nodes = self._get_recent_nodes(user_id, time_window_days)
        if not nodes:
            return self._empty_pattern()

        user_messages = [n for n in nodes if n.source == "user"]

        return {
            "peak_hours":        self._detect_peak_hours(nodes),
            "topics_frequency":  self._detect_topics(user_messages),
            "common_questions":  self._detect_common_questions(user_messages),
            "sentiment_trend":   self._detect_sentiment(user_messages),
            "activity_streak":   self._detect_streak(nodes),
            "most_used_agent":   self._detect_most_used_agent(nodes),
            "total_messages":    len(user_messages),
            "window_days":       time_window_days,
        }

    # ── Peak Hours ────────────────────────────────────────

    def _detect_peak_hours(self, nodes: list) -> list[int]:
        """Jam-jam user paling aktif (0-23)."""
        hours = []
        for node in nodes:
            try:
                dt = node.created_at
                if isinstance(dt, str):
                    dt = datetime.fromisoformat(dt)
                hours.append(dt.hour)
            except Exception:
                continue

        if not hours:
            return []

        counter = Counter(hours)
        # Return top 3 jam
        return [h for h, _ in counter.most_common(3)]

    # ── Topic Detection ───────────────────────────────────

    _TOPIC_KEYWORDS = {
        "coding":     ["code","kode","bug","error","python","javascript","debug","function","api"],
        "devops":     ["deploy","server","docker","nginx","linux","ssh","vps","cloud","kubernetes"],
        "writing":    ["tulis","write","artikel","blog","caption","konten","email","copywriting"],
        "data":       ["data","analisis","chart","grafik","statistik","metric","excel","laporan"],
        "learning":   ["belajar","pelajari","jelaskan","ajarkan","understand","konsep","tutorial"],
        "translate":  ["terjemah","translate","bahasa","english","indonesia","language"],
        "research":   ["riset","research","cari","fakta","sumber","referensi","study"],
        "summarize":  ["ringkas","summarize","ringkasan","tldr","singkat","kondensasi"],
        "support":    ["komplain","complaint","refund","bantuan","masalah","problem","help"],
    }

    def _detect_topics(self, messages: list) -> dict[str, int]:
        """Hitung frekuensi topik dari pesan user."""
        counts: dict[str, int] = Counter()
        for node in messages:
            text = node.content.lower()
            for topic, keywords in self._TOPIC_KEYWORDS.items():
                if any(kw in text for kw in keywords):
                    counts[topic] += 1
        return dict(counts.most_common())

    # ── Common Questions ──────────────────────────────────

    def _detect_common_questions(self, messages: list,
                                  top_n: int = 5) -> list[str]:
        """Deteksi pertanyaan atau frasa yang sering diulang."""
        # Ekstrak trigrams dari pesan
        trigrams: Counter = Counter()
        for node in messages:
            words = _tokenize(node.content)
            for i in range(len(words) - 2):
                trigram = " ".join(words[i:i+3])
                trigrams[trigram] += 1

        # Hanya yang muncul lebih dari sekali
        repeated = [(t, c) for t, c in trigrams.most_common(top_n * 2) if c > 1]
        return [t for t, _ in repeated[:top_n]]

    # ── Sentiment ─────────────────────────────────────────

    _POSITIVE = {
        "bagus","baik","mantap","oke","sukses","berhasil","good","great",
        "thanks","terima kasih","makasih","perfect","awesome","keren","nice",
    }
    _NEGATIVE = {
        "error","bug","masalah","gagal","fail","tidak bisa","ngga bisa",
        "rusak","broken","wrong","salah","susah","sulit","lambat","lama",
    }

    def _detect_sentiment(self, messages: list) -> str:
        """Deteksi tren sentimen: positive / negative / neutral."""
        pos = neg = 0
        for node in messages:
            text = node.content.lower()
            pos += sum(1 for w in self._POSITIVE if w in text)
            neg += sum(1 for w in self._NEGATIVE if w in text)

        if pos == neg == 0:
            return "neutral"
        if pos > neg * 1.5:
            return "positive"
        if neg > pos * 1.5:
            return "negative"
        return "mixed"

    # ── Activity Streak ───────────────────────────────────

    def _detect_streak(self, nodes: list) -> int:
        """Berapa hari berturut-turut user aktif."""
        if not nodes:
            return 0

        dates = set()
        for node in nodes:
            try:
                dt = node.created_at
                if isinstance(dt, str):
                    dt = datetime.fromisoformat(dt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                dates.add(dt.date())
            except Exception:
                continue

        if not dates:
            return 0

        today  = datetime.now(timezone.utc).date()
        streak = 0
        day    = today
        while day in dates:
            streak += 1
            day -= timedelta(days=1)
        return streak

    # ── Most Used Agent ───────────────────────────────────

    def _detect_most_used_agent(self, nodes: list) -> str:
        """Agent yang paling sering dipakai."""
        agents: Counter = Counter()
        for node in nodes:
            agent = node.metadata.get("agent_id")
            if agent:
                agents[agent] += 1
        if not agents:
            return "general"
        return agents.most_common(1)[0][0]

    # ── Helpers ───────────────────────────────────────────

    def _get_recent_nodes(self, user_id: str, days: int) -> list:
        """Ambil nodes dalam time window tertentu."""
        all_nodes = self._storage.get_nodes(
            user_id, status="active", limit=10000
        )
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = []
        for node in all_nodes:
            try:
                dt = node.created_at
                if isinstance(dt, str):
                    dt = datetime.fromisoformat(dt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt >= cutoff:
                    result.append(node)
            except Exception:
                result.append(node)
        return result

    def _empty_pattern(self) -> dict:
        return {
            "peak_hours": [], "topics_frequency": {},
            "common_questions": [], "sentiment_trend": "neutral",
            "activity_streak": 0, "most_used_agent": "general",
            "total_messages": 0, "window_days": 0,
        }


def _tokenize(text: str) -> list[str]:
    stopwords = {
        "yang","dan","di","ke","dari","ini","itu","dengan","untuk",
        "saya","aku","kamu","bisa","mau","the","a","an","i","you","to","is",
    }
    words = re.findall(r'\b[a-zA-Z0-9\u00C0-\u024F]{2,}\b', text.lower())
    return [w for w in words if w not in stopwords]
