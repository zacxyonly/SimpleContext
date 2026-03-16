"""
context/planner.py v4.1 — ContextPlanner + RetrievalPlan
Intent mapping yang lebih akurat dengan context-aware signals.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field

from ..enums import Intent, DEFAULT_BUDGET, DEFAULT_MAX_TOTAL_NODES, DEFAULT_MAX_TOTAL_CHARS


@dataclass
class RetrievalPlan:
    """Rencana retrieval stateless — membawa semua info yang dibutuhkan pipeline."""
    query:           str
    user_id:         str
    intent:          str  = Intent.CONVERSATION.value

    working:         bool = True
    episodic:        bool = True
    semantic:        bool = True
    include_skills:  bool = False

    focus_tags:      list[str] = field(default_factory=list)
    preferred_paths: list[str] = field(default_factory=list)

    budget:          dict = field(default_factory=lambda: dict(DEFAULT_BUDGET))
    max_total_nodes: int  = DEFAULT_MAX_TOTAL_NODES
    max_total_chars: int  = DEFAULT_MAX_TOTAL_CHARS

    metadata:        dict = field(default_factory=dict)


class ContextPlanner:
    """
    Tentukan strategi retrieval berdasarkan query + profil.
    Rule-based, zero dependency, deterministic.
    """

    # ── Intent signals ────────────────────────────────────

    _CODING_KW = {
        "code","kode","bug","error","debug","python","javascript","typescript",
        "golang","rust","php","java","html","css","sql","function","class",
        "import","variable","loop","array","api","database","git","docker",
        "install","package","library","framework","compile","syntax","script",
        "program","algorithm","algoritma","fungsi","method","object","string",
    }

    _PERSONAL_KW = {
        "saya","aku","namaku","profil","preferensi","suka","tidak suka",
        "biasanya","kebiasaan","profile","preference","remember","ingat",
        "siapa aku","siapa saya","nama saya","i am","i use","i like","i prefer",
        "my name","my project","project saya","stack saya","server saya",
    }

    _TASK_KW = {
        "tolong","bantu","buatkan","bikin","buat","generate","create","write",
        "tulis","selesaikan","finish","complete","task","tugas","langkah",
        "step","cara","how to","help me","make","build","setup","configure",
    }

    _KNOWLEDGE_KW = {
        "apa","what","explain","jelaskan","mengapa","why","kapan","when",
        "dimana","where","siapa","who","definisi","definition","artinya",
        "meaning","perbedaan","difference","bagaimana cara","how does",
        "apa itu","what is","cara kerja","how works",
    }

    _HISTORY_KW = {
        "sebelumnya","tadi","kemarin","lalu","sebelum","before","earlier",
        "previously","last time","tadi kita","kita tadi","yang tadi",
        "lanjutkan","continue","sambung",
    }

    # ── Intent → retrieval strategy ───────────────────────

    _STRATEGY = {
        Intent.CONVERSATION.value: {
            "working": True, "episodic": True,  "semantic": False, "skills": False,
            "budget": {"working": 5, "episodic": 2, "semantic": 0, "skills": 0},
        },
        Intent.PERSONAL.value: {
            "working": True, "episodic": False, "semantic": True,  "skills": False,
            "budget": {"working": 3, "episodic": 0, "semantic": 5, "skills": 0},
        },
        Intent.CODING.value: {
            "working": True, "episodic": True,  "semantic": True,  "skills": True,
            "budget": {"working": 5, "episodic": 1, "semantic": 3, "skills": 3},
        },
        Intent.KNOWLEDGE.value: {
            "working": False,"episodic": False, "semantic": True,  "skills": False,
            "budget": {"working": 0, "episodic": 0, "semantic": 6, "skills": 0},
        },
        Intent.TASK.value: {
            "working": True, "episodic": True,  "semantic": True,  "skills": True,
            "budget": {"working": 4, "episodic": 2, "semantic": 2, "skills": 2},
        },
    }

    def plan(self, query: str, user_id: str,
             profile: dict = None, agent_id: str = None) -> RetrievalPlan:
        """
        Buat RetrievalPlan dari query dan profil user.
        """
        profile = profile or {}
        intent  = self._detect_intent(query)

        strategy = self._STRATEGY.get(intent, self._STRATEGY[Intent.CONVERSATION.value])

        # Override skills kalau ada agent_id
        include_skills = strategy["skills"] and bool(agent_id)

        # Focus tags dari query + profil
        focus_tags = self._extract_focus_tags(query, profile)

        # Preferred paths dari intent
        preferred_paths = self._preferred_paths(intent, user_id, agent_id)

        # Budget dari strategy, bisa di-override kalau ada agent
        budget = dict(strategy["budget"])
        if agent_id and include_skills:
            budget["skills"] = max(budget.get("skills", 0), 2)

        meta: dict = {}
        if agent_id:
            meta["agent_id"] = agent_id

        return RetrievalPlan(
            query           = query,
            user_id         = user_id,
            intent          = intent,
            working         = strategy["working"],
            episodic        = strategy["episodic"],
            semantic        = strategy["semantic"],
            include_skills  = include_skills,
            focus_tags      = focus_tags,
            preferred_paths = preferred_paths,
            budget          = budget,
            metadata        = meta,
        )

    # ── Intent detection ──────────────────────────────────

    def _detect_intent(self, query: str) -> str:
        """
        Detect intent dengan multi-signal scoring.
        Context-aware: "sebelumnya" override ke conversation.
        """
        q = query.lower()
        tokens = set(re.findall(r'\b\w+\b', q))

        # History signal paling kuat — override intent lain
        if tokens & self._HISTORY_KW or any(kw in q for kw in self._HISTORY_KW):
            return Intent.CONVERSATION.value

        # Personal: hanya kalau ada pola spesifik tentang diri user
        # Bukan sekadar kata "saya" yang umum dipakai di semua kalimat
        personal_phrases = [
            "nama saya","namaku","nama aku","my name",
            "siapa saya","siapa aku","who am i",
            "project saya","project aku","project ku","my project",
            "stack saya","stack ku","my stack",
            "server saya","server ku","my server",
            "saya pakai","saya menggunakan","saya memakai",
            "i use","i am using","i prefer","i like",
            "ingat","remember me","profil saya","my profile",
        ]
        if any(phrase in q for phrase in personal_phrases):
            return Intent.PERSONAL.value

        # Score berdasarkan jumlah keyword match
        scores = {
            Intent.CODING.value:    len(tokens & self._CODING_KW),
            Intent.TASK.value:      len(tokens & self._TASK_KW),
            Intent.KNOWLEDGE.value: len(tokens & self._KNOWLEDGE_KW),
        }

        best = max(scores, key=scores.get)
        if scores[best] > 0:
            return best

        return Intent.CONVERSATION.value

    # ── Helpers ───────────────────────────────────────────

    def _extract_focus_tags(self, query: str, profile: dict) -> list[str]:
        q = query.lower()
        tech = ["python","javascript","docker","linux","git","sql","api",
                "react","node","golang","rust","proxmox","kubernetes"]
        tags = [t for t in tech if t in q]
        # Dari profil
        if isinstance(profile.get("tags"), list):
            tags += [t for t in profile["tags"] if t in q]
        return list(set(tags))[:5]

    def _preferred_paths(self, intent: str, user_id: str,
                         agent_id: str = None) -> list[str]:
        paths = []
        if intent == Intent.PERSONAL.value:
            paths.append(f"/memory/semantic/{user_id}")
        if intent == Intent.TASK.value:
            paths.append(f"/memory/working/{user_id}")
        if agent_id and intent in (Intent.CODING.value, Intent.TASK.value):
            paths.append(f"/skills/{agent_id}")
        return paths
