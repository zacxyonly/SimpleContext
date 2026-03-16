"""
context/builder.py v4.1 — PromptBuilder
Format context ringkas dan konsisten.
Tambah system rules agar AI tidak verbose dan tidak memperkenalkan diri.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .node import ContextNode

from ..enums import Tier, NodeKind, SKILL_NAMESPACE_PREFIX

# Urutan tier di prompt
TIER_ORDER = {
    Tier.WORKING.value:  0,
    Tier.EPISODIC.value: 1,
    Tier.SEMANTIC.value: 2,
    "skills":            3,
}

SECTION_LABELS = {
    Tier.WORKING.value:  "Working Context",
    Tier.EPISODIC.value: "Episodic Memory",
    Tier.SEMANTIC.value: "Semantic Knowledge",
    "skills":            "Available Skills",
}

# Safety limit: node content tidak boleh lebih dari ini
MAX_NODE_CHARS = 1000

# System rules yang selalu ditambahkan
SYSTEM_RULES = """
RULES:
- Answer directly without introducing yourself unless asked
- Use context above only when relevant to the question
- Be concise and to the point
- For code always use proper code blocks with language tag"""


class PromptBuilder:
    """
    Build messages list dari ContextNodes secara deterministic.
    Format ringkas: bullet points per node, section per tier.
    """

    def build(self,
              system_base: str,
              nodes: list["ContextNode"],
              user_message: str,
              history: list[dict] = None,
              profile: dict = None) -> list[dict]:
        """
        Build messages array lengkap untuk LLM.

        Args:
            system_base:   system prompt dasar dari agent
            nodes:         context nodes dari ContextEngine
            user_message:  pesan user saat ini
            history:       riwayat percakapan (format LLM)
            profile:       profil user

        Return: [{"role": "system", ...}, ..., {"role": "user", ...}]
        """
        system_content = self._build_system(system_base, nodes, profile)
        messages: list[dict] = [{"role": "system", "content": system_content}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        return messages

    def _build_system(self, base: str, nodes: list["ContextNode"],
                      profile: dict = None) -> str:
        parts: list[str] = []

        # 1. Base prompt agent
        if base:
            parts.append(base.strip())

        # 2. Context sections (ringkas, bullet per node)
        context_block = self._build_context_block(nodes)
        if context_block:
            parts.append(context_block)

        # 3. Profil user (ringkas)
        if profile:
            profile_block = self._build_profile_block(profile)
            if profile_block:
                parts.append(profile_block)

        # 4. System rules (selalu ada)
        parts.append(SYSTEM_RULES.strip())

        return "\n\n".join(parts)

    def _build_context_block(self, nodes: list["ContextNode"]) -> str:
        """Build context block dengan format bullet ringkas per tier."""
        if not nodes:
            return ""

        # Pisahkan ke bucket
        buckets: dict[str, list["ContextNode"]] = {
            Tier.WORKING.value:  [],
            Tier.EPISODIC.value: [],
            Tier.SEMANTIC.value: [],
            "skills":            [],
        }
        for node in nodes:
            if (node.path.startswith(SKILL_NAMESPACE_PREFIX)
                    or node.kind == NodeKind.SKILL):
                buckets["skills"].append(node)
            else:
                buckets[node.tier.value].append(node)

        # Sort tiap bucket: importance desc
        for bkt in buckets.values():
            bkt.sort(key=lambda n: -n.importance)

        sections: list[str] = []
        for tier_key in sorted(buckets.keys(),
                               key=lambda k: TIER_ORDER.get(k, 99)):
            bucket_nodes = buckets[tier_key]
            if not bucket_nodes:
                continue
            label   = SECTION_LABELS.get(tier_key, tier_key.upper())
            section = self._format_section(label, bucket_nodes, tier_key)
            if section:
                sections.append(section)

        if not sections:
            return ""
        return "\n\n".join(sections)

    def _format_section(self, label: str,
                        nodes: list["ContextNode"],
                        tier_key: str) -> str:
        """
        Format satu section dengan bullet ringkas.

        [Working Context]
        - user meminta kode python
        - ada error IndexError di baris 42
        """
        lines = [f"[{label}]"]
        for node in nodes:
            content = self._truncate(node.content, MAX_NODE_CHARS)
            if tier_key == Tier.WORKING.value and node.kind == NodeKind.MESSAGE:
                # Working message: "role: content" ringkas
                role = node.source.capitalize()
                lines.append(f"- {role}: {content}")
            elif tier_key == "skills":
                skill_name = node.path.split("/")[-1] if "/" in node.path else node.id
                lines.append(f"- [{skill_name}] {content}")
            else:
                # Episodic/semantic: bullet langsung
                lines.append(f"- {content}")
        return "\n".join(lines)

    def _build_profile_block(self, profile: dict) -> str:
        """Build profile block ringkas."""
        display = {k: v for k, v in profile.items()
                   if not k.startswith("_") and k != "preferred_agent"}
        if not display:
            return ""
        lines = ["[User Profile]"]
        for k, v in display.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        """Truncate teks panjang, tambahkan '...' kalau dipotong."""
        text = text.strip()
        if len(text) <= max_chars:
            return text
        return text[:max_chars - 3].rstrip() + "..."
