"""
BasePlugin v4
Tambahan dari v3:
- app_commands: kontrak resmi untuk expose command ke aplikasi host
  (Telegram bot, Discord bot, CLI, web UI, dll)
- app_info: metadata aplikasi host yang inject plugin
- on_app_command(): hook generik untuk handle command yang tidak punya
  dedicated handler method
- get_app_commands(): helper untuk introspeksi commands yang didaftarkan

app_commands Format:
    {
        "command_name": {
            "description": str,          # wajib — deskripsi singkat
            "usage":       str,          # opsional — contoh penggunaan
            "handler":     str,          # nama method di class ini
                                         # signature: async def(self, context) -> str
                                         # context = AppCommandContext
            "args_hint":   str,          # opsional — hint argumen, misal "<query>"
            "hidden":      bool,         # opsional — sembunyikan dari /help (default False)
        }
    }

Contoh minimal:
    class MyPlugin(BasePlugin):
        name = "my_plugin"

        app_commands = {
            "mycommand": {
                "description": "Lakukan sesuatu",
                "usage":       "/mycommand <arg>",
                "handler":     "handle_mycommand",
            }
        }

        async def handle_mycommand(self, context: "AppCommandContext") -> str:
            return f"Kamu kirim: {context.args_str}"
"""

from abc import ABC
from dataclasses import dataclass, field
from typing import Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .state import PluginState


# ── AppCommandContext ─────────────────────────────────────────────────────────

@dataclass
class AppCommandContext:
    """
    Context yang dikirim ke handler app_command.
    Platform-agnostic — host app yang mengisi field ini.

    Contoh penggunaan di handler plugin:
        async def handle_search(self, ctx: AppCommandContext) -> str:
            query = ctx.args_str
            user  = ctx.user_id
            # ... proses ...
            return f"Hasil untuk: {query}"
    """

    # ── Wajib diisi host ──────────────────────────────────
    command:    str            # nama command yang dipanggil, misal "semantic"
    user_id:    str            # ID user (string, platform-agnostic)
    args:       list[str]      # argumen sebagai list token
    args_str:   str            # argumen sebagai satu string (join args)

    # ── Opsional — tergantung platform host ───────────────
    platform:   str            = "unknown"  # "telegram" | "discord" | "cli" | "web" | dll
    raw:        Any            = None       # object asli dari platform (misal Update Telegram)
    sc:         Any            = None       # SimpleContext instance
    extra:      dict           = field(default_factory=dict)  # data tambahan bebas

    @classmethod
    def create(cls, command: str, user_id: str, args: list[str],
               platform: str = "unknown", raw: Any = None,
               sc: Any = None, **extra) -> "AppCommandContext":
        """Factory helper untuk membuat context."""
        return cls(
            command  = command,
            user_id  = str(user_id),
            args     = args,
            args_str = " ".join(args),
            platform = platform,
            raw      = raw,
            sc       = sc,
            extra    = extra,
        )


# ── BasePlugin ────────────────────────────────────────────────────────────────

class BasePlugin(ABC):
    """
    Base class untuk semua plugin SimpleContext v4.
    Override hanya method yang kamu butuhkan.

    Changelog v4:
    - Tambah app_commands: dict — expose command ke aplikasi host
    - Tambah app_info: dict — diisi host saat plugin di-load
    - Tambah on_app_command() — fallback handler untuk command tanpa dedicated method
    - Tambah get_app_commands() — helper introspeksi
    """

    # ── Deklarasi di subclass ─────────────────────────────
    name:        str       = ""
    version:     str       = "1.0.0"
    description: str       = ""
    depends_on:  list[str] = []

    # ── App Commands (v4) ─────────────────────────────────
    # Override di subclass untuk expose command ke aplikasi host.
    # Host app (bot, CLI, web) membaca ini dan mendaftarkan command secara otomatis.
    #
    # Format:
    #   app_commands = {
    #       "command_name": {
    #           "description": "Deskripsi singkat",   # wajib
    #           "usage":       "/command <arg>",       # opsional
    #           "handler":     "method_name",          # wajib — nama method di class ini
    #           "args_hint":   "<query>",              # opsional
    #           "hidden":      False,                  # opsional
    #       }
    #   }
    app_commands: dict = {}

    # ── App Info (diisi host) ─────────────────────────────
    # Diisi otomatis oleh host saat plugin di-load via PluginLoader.
    # Plugin bisa baca ini untuk tahu di platform apa dia berjalan.
    #
    # Contoh isi oleh Telegram bot:
    #   plugin.app_info = {"platform": "telegram", "version": "1.2.0"}
    app_info: dict = {}

    def __init__(self, config: dict = None):
        self.config  = config or {}
        self.enabled = self.config.get("enabled", True)
        self.state: Optional["PluginState"] = None  # di-inject oleh PluginLoader
        # Instance-level copy agar tidak shared antar class
        self.app_info = {}
        self.setup()

    def setup(self):
        """
        Dipanggil saat plugin diinisialisasi.
        Override untuk setup resource (koneksi, file, dll).
        self.state sudah tersedia saat setup() dipanggil.
        """

    def teardown(self):
        """Dipanggil saat SimpleContext ditutup. Override untuk cleanup."""

    # ── App Commands API (v4) ─────────────────────────────

    def get_app_commands(self) -> dict:
        """
        Return dict app_commands yang valid — hanya command dengan handler
        yang benar-benar ada di instance ini.

        Host app sebaiknya memanggil ini (bukan akses app_commands langsung)
        agar command yang handler-nya tidak ada tidak ikut didaftarkan.
        """
        valid = {}
        for cmd_name, cmd_info in self.__class__.app_commands.items():
            handler_name = cmd_info.get("handler")
            if handler_name and hasattr(self, handler_name):
                valid[cmd_name] = cmd_info
            else:
                import logging
                logging.getLogger(__name__).warning(
                    f"Plugin '{self.name}': app_command '{cmd_name}' "
                    f"deklarasi handler '{handler_name}' tapi method tidak ditemukan — dilewati."
                )
        return valid

    async def on_app_command(self, context: AppCommandContext) -> Optional[str]:
        """
        Fallback hook — dipanggil untuk command yang tidak punya dedicated handler method,
        ATAU oleh host yang ingin routing terpusat (semua command lewat satu titik).

        Return string response, atau None untuk pass-through.

        Override ini jika plugin ingin handle semua command-nya di satu tempat:
            async def on_app_command(self, ctx):
                if ctx.command == "foo": return "foo!"
                if ctx.command == "bar": return "bar!"
        """
        return None

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
        """
        return messages

    def on_after_llm(self, user_id: str, agent_id: str,
                     response: str) -> str:
        """
        Dipanggil SETELAH LLM menghasilkan response.
        Bisa modifikasi, filter, atau tambahkan sesuatu ke response.
        Wajib return string response.
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
        cmds = list(self.__class__.app_commands.keys())
        cmd_str = f" commands={cmds}" if cmds else ""
        return (
            f"<Plugin name={self.name!r} v{self.version} "
            f"enabled={self.enabled} deps={self.depends_on}{cmd_str}>"
        )
