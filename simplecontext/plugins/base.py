"""
BasePlugin v3
Tambahan dari v2:
- on_before_llm / on_after_llm hooks
- Plugin state permanen via self.state
- Plugin dependency via depends_on
"""

from abc import ABC
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .state import PluginState


class BasePlugin(ABC):
    """
    Base class untuk semua plugin SimpleContext v3.
    Override hanya method yang kamu butuhkan.
    """

    # ── Deklarasi di subclass ─────────────────────────────
    name:        str       = ""
    version:     str       = "1.0.0"
    description: str       = ""
    depends_on:  list[str] = []   # nama plugin yang harus ada sebelum plugin ini

    def __init__(self, config: dict = None):
        self.config  = config or {}
        self.enabled = self.config.get("enabled", True)
        self.state: Optional["PluginState"] = None  # di-inject oleh PluginLoader
        self.setup()

    def setup(self):
        """
        Dipanggil saat plugin diinisialisasi.
        Override untuk setup resource (koneksi, file, dll).
        Saat setup() dipanggil, self.state sudah tersedia.
        """

    def teardown(self):
        """Dipanggil saat SimpleContext ditutup. Override untuk cleanup."""

    # ── Hooks Memory ──────────────────────────────────────

    def on_message_saved(self, user_id: str, role: str, content: str,
                         tags: list, metadata: dict):
        """Dipanggil setiap pesan baru disimpan ke memori."""

    def on_messages_cleared(self, user_id: str):
        """Dipanggil saat memori user dihapus."""

    def on_context_build(self, user_id: str, messages: list[dict]) -> list[dict]:
        """
        Dipanggil saat history messages akan dikirim ke LLM.
        Bisa modifikasi, filter, atau enrich messages.
        Wajib return list messages.
        """
        return messages

    # ── Hooks LLM ─────────────────────────────────────────

    def on_before_llm(self, user_id: str, agent_id: str,
                      messages: list[dict]) -> list[dict]:
        """
        Dipanggil SEBELUM pesan dikirim ke LLM.
        Bisa inject pesan tambahan, modifikasi system prompt, dll.
        Wajib return list messages.

        Contoh: inject timestamp ke system message
            messages[0]["content"] += f"\\nWaktu sekarang: {datetime.now()}"
            return messages
        """
        return messages

    def on_after_llm(self, user_id: str, agent_id: str,
                     response: str) -> str:
        """
        Dipanggil SETELAH LLM menghasilkan response.
        Bisa modifikasi, filter, atau tambahkan sesuatu ke response.
        Wajib return string response.

        Contoh: tambahkan disclaimer
            return response + "\\n\\n_Jawaban dihasilkan oleh AI._"
        """
        return response

    # ── Hooks Skills ──────────────────────────────────────

    def on_skill_saved(self, agent_id: str, name: str, content: str):
        """Dipanggil saat skill disimpan atau diupdate."""

    def on_skill_deleted(self, agent_id: str, name: str):
        """Dipanggil saat skill dihapus."""

    def on_prompt_build(self, agent_id: str, prompt: str) -> str:
        """
        Dipanggil saat system prompt selesai dibangun dari skills.
        Wajib return string prompt.
        """
        return prompt

    # ── Hooks Agent ───────────────────────────────────────

    def on_agent_routed(self, user_id: str, agent_id: str, message: str):
        """Dipanggil saat pesan user di-route ke agent tertentu."""

    def on_agent_chain(self, user_id: str, from_agent: str,
                       to_agent: str, reason: str):
        """Dipanggil saat terjadi chain dari satu agent ke agent lain."""

    # ── Hooks Export/Import ───────────────────────────────

    def on_export(self, data: dict) -> dict:
        """Dipanggil saat data di-export. Wajib return dict."""
        return data

    def on_import(self, data: dict) -> dict:
        """Dipanggil saat data akan di-import. Wajib return dict."""
        return data

    def __repr__(self):
        return f"<Plugin name={self.name!r} v{self.version} enabled={self.enabled} deps={self.depends_on}>"
