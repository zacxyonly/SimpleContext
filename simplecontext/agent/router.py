"""
AgentRouter v3.1
Fix:
- should_chain cek pesan USER bukan response LLM (Bug #1)
- from_agent ditrack dengan benar di chain() (Bug #3)
- Routing pakai TF-IDF sederhana, lebih akurat (Bug #5)
"""

import re
import math
import logging
from typing import Optional, TYPE_CHECKING
from collections import Counter

if TYPE_CHECKING:
    from .registry import AgentRegistry
    from .schema import AgentDef
    from ..storage.base import BaseStorage
    from ..plugins.loader import PluginLoader

logger = logging.getLogger(__name__)

# Stopwords untuk TF-IDF
_STOPWORDS = {
    "yang", "dan", "di", "ke", "dari", "ini", "itu", "dengan", "untuk",
    "adalah", "ada", "juga", "saya", "kamu", "aku", "kita", "mereka",
    "bisa", "mau", "mau", "sudah", "belum", "tidak", "bukan", "gimana",
    "the", "a", "an", "is", "are", "was", "were", "i", "you", "we",
    "to", "of", "in", "it", "that", "this", "and", "or", "but", "my",
    "me", "do", "does", "did", "have", "has", "had", "will", "would",
    "please", "can", "could", "should", "may", "might", "tolong", "minta",
}


class RouteResult:
    """
    Hasil routing — berisi semua info yang dibutuhkan untuk panggil LLM.
    """

    def __init__(self, agent: "AgentDef", system_prompt: str,
                 agent_id: str, personality_level: str = "default",
                 original_message: str = ""):
        self.agent             = agent
        self.agent_id          = agent_id
        self.system_prompt     = system_prompt
        self.personality_level = personality_level
        self._original_message = original_message  # simpan pesan user asli untuk chain check

    def should_chain(self, user_message: str = None) -> Optional[dict]:
        """
        Cek apakah pesan USER mengandung sinyal untuk chain ke agent lain.

        FIX #1: Chain di-trigger dari PESAN USER, bukan response LLM.
        Ini mencegah false positive saat LLM membahas topik chain secara kontekstual.

        Args:
            user_message: pesan user (kalau None, pakai pesan saat routing)
        """
        msg = user_message or self._original_message
        return self.agent.should_chain(msg)

    def __repr__(self):
        return f"<RouteResult agent={self.agent_id!r} personality={self.personality_level!r}>"


class AgentRouter:
    """
    Router yang menentukan agent mana yang menangani pesan.

    Urutan prioritas routing:
    1. Profil user: jika user punya "preferred_agent" → pakai itu
    2. TF-IDF scoring: lebih akurat dari pure keyword matching
    3. Default agent dari config
    """

    def __init__(self, registry: "AgentRegistry", storage: "BaseStorage",
                 plugins: "PluginLoader", default_agent: str = "general"):
        self._registry      = registry
        self._storage       = storage
        self._plugins       = plugins
        self._default_agent = default_agent

    def route(self, user_id: str, message: str,
              skills_builder=None) -> RouteResult:
        """
        Route pesan ke agent yang tepat.

        Args:
            user_id:        ID user
            message:        pesan dari user
            skills_builder: fungsi untuk build system prompt dari skills
                            signature: (agent_id, base_prompt) → str
        """
        # 1. Cek preferensi user
        profile   = self._storage.get_profile(str(user_id))
        preferred = profile.get("preferred_agent")
        agent_id  = preferred if (preferred and self._registry.exists(preferred)) else None

        # 2. Auto-route dengan TF-IDF scoring
        if not agent_id:
            agent_id = self._auto_route(message)

        # 3. Fallback ke default
        if not agent_id:
            agent_id = self._default_agent

        agent = self._registry.get(agent_id)
        if not agent:
            from .schema import AgentDef
            agent = AgentDef.from_dict({
                "name": agent_id,
                "description": "Default agent",
                "personality": {"default": "Kamu adalah asisten AI yang helpful."},
            })

        # 4. Tentukan personality level dari profil user
        level = profile.get("level", "default")

        # 5. Build system prompt
        base_prompt = agent.get_personality(level)
        if skills_builder:
            system_prompt = skills_builder(agent_id, base_prompt)
        else:
            system_prompt = base_prompt

        # 6. Fire plugin hook
        self._plugins.fire_agent_routed(str(user_id), agent_id, message)

        logger.debug(f"Routed user={user_id} → agent={agent_id} (level={level})")
        return RouteResult(agent, system_prompt, agent_id, level,
                           original_message=message)

    def chain(self, user_id: str, original_message: str,
              llm_response: str, chain_rule: dict,
              from_agent_id: str = "unknown",
              skills_builder=None) -> "RouteResult":
        """
        Lakukan chain dari agent saat ini ke agent lain.

        FIX #3: from_agent_id sekarang ditrack dengan benar.

        Args:
            user_id:          ID user
            original_message: pesan asli dari user
            llm_response:     response dari agent pertama (untuk konteks)
            chain_rule:       rule dict dari RouteResult.should_chain()
            from_agent_id:    agent asal (untuk logging & metadata)
            skills_builder:   sama seperti di route()
        """
        to_agent = chain_rule.get("to", self._default_agent)
        reason   = chain_rule.get("condition", "")

        self._plugins.fire_agent_chain(str(user_id), from_agent_id, to_agent, reason)
        logger.info(f"Chain: {from_agent_id} → {to_agent} (reason: {reason!r})")

        profile = self._storage.get_profile(str(user_id))
        level   = profile.get("level", "default")

        agent = self._registry.get(to_agent)
        if not agent:
            from .schema import AgentDef
            agent = AgentDef.from_dict({
                "name": to_agent,
                "description": f"Chain target: {to_agent}",
                "personality": {"default": f"Kamu adalah {to_agent} agent yang helpful."},
            })

        base_prompt = agent.get_personality(level)
        if skills_builder:
            system_prompt = skills_builder(to_agent, base_prompt)
        else:
            system_prompt = base_prompt

        return RouteResult(agent, system_prompt, to_agent, level,
                           original_message=original_message)

    def set_user_agent(self, user_id: str, agent_name: str):
        """Set agent pilihan user secara permanen."""
        if agent_name and not self._registry.exists(agent_name):
            raise ValueError(f"Agent '{agent_name}' tidak ditemukan.")
        self._storage.update_profile(str(user_id), "preferred_agent", agent_name)

    def clear_user_agent(self, user_id: str):
        """Hapus preferensi agent user (kembali ke auto-route)."""
        profile = self._storage.get_profile(str(user_id))
        profile.pop("preferred_agent", None)
        self._storage.set_profile(str(user_id), profile)

    # ── Routing Engine ────────────────────────────────────

    def _auto_route(self, message: str) -> Optional[str]:
        """
        FIX #5: Pilih agent pakai TF-IDF scoring.

        Lebih akurat dari pure keyword — mempertimbangkan:
        - Bobot kata (kata langka lebih informatif dari kata umum)
        - Proporsi keyword yang cocok dari total keyword agent
        - Priority agent sebagai multiplier

        Mencegah false positive seperti "saya tidak bisa code"
        ke-route ke coding hanya karena ada kata "code".
        """
        agents = self._registry.all()
        if not agents:
            return None

        msg_tokens = _tokenize(message)
        if not msg_tokens:
            return None

        # Hitung IDF untuk semua keyword di semua agent
        all_keywords: list[list[str]] = [a.keywords for a in agents]
        idf_map = _compute_idf(all_keywords)

        best_agent = None
        best_score = 0.0

        for agent in agents:
            if not agent.keywords:
                continue
            score = _tfidf_score(msg_tokens, agent.keywords, idf_map)
            # Boost dengan priority agent
            score *= (1 + agent.priority * 0.1)
            if score > best_score:
                best_score = score
                best_agent = agent.name

        # Threshold minimum — hindari routing ke agent yang barely match
        return best_agent if best_score > 0.05 else None

    def __repr__(self):
        return f"<AgentRouter default={self._default_agent!r} agents={len(self._registry.names())}>"


# ── TF-IDF Helpers ────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """Tokenize teks ke list kata bersih."""
    words = re.findall(r'\b[a-zA-Z0-9\u00C0-\u024F]{2,}\b', text.lower())
    return [w for w in words if w not in _STOPWORDS]


def _compute_idf(keyword_lists: list[list[str]]) -> dict[str, float]:
    """
    Hitung IDF (Inverse Document Frequency) untuk semua keyword.
    Keyword yang muncul di banyak agent → IDF rendah (kurang informatif).
    Keyword yang unik untuk satu agent → IDF tinggi (sangat informatif).
    """
    n = len(keyword_lists)
    if n == 0:
        return {}
    doc_freq: Counter = Counter()
    for kws in keyword_lists:
        for kw in set(kws):
            doc_freq[kw] += 1
    return {kw: math.log((n + 1) / (freq + 1)) + 1
            for kw, freq in doc_freq.items()}


def _tfidf_score(msg_tokens: list[str], agent_keywords: list[str],
                 idf_map: dict[str, float]) -> float:
    """
    Hitung skor TF-IDF antara pesan user dan keyword agent.
    Skor = rata-rata bobot IDF dari keyword yang match.
    """
    if not agent_keywords:
        return 0.0

    matched_weights: list[float] = []
    msg_set = set(msg_tokens)

    for kw in agent_keywords:
        # Support multi-word keyword ("code block" → cek semua token ada di pesan)
        kw_tokens = _tokenize(kw) or [kw]
        if all(t in msg_set for t in kw_tokens):
            weight = sum(idf_map.get(t, 1.0) for t in kw_tokens) / len(kw_tokens)
            matched_weights.append(weight)

    if not matched_weights:
        return 0.0

    # Skor = total bobot match / jumlah keyword agent (proporsi coverage)
    coverage = len(matched_weights) / len(agent_keywords)
    avg_weight = sum(matched_weights) / len(matched_weights)
    return avg_weight * coverage
