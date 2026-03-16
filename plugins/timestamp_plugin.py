"""
Timestamp Injector Plugin
Inject waktu & info session ke system message sebelum LLM dipanggil.
Demonstrasi: on_before_llm hook + depends_on dependency.

Bergantung pada logger_plugin (harus diload lebih dulu).

Config:
    plugins:
      timestamp_plugin:
        enabled: true
        format: "%Y-%m-%d %H:%M UTC"
"""

from datetime import datetime, timezone
from simplecontext.plugins.base import BasePlugin


class TimestampPlugin(BasePlugin):
    name        = "timestamp_plugin"
    version     = "1.0.0"
    description = "Inject waktu saat ini ke system prompt sebelum LLM dipanggil."
    depends_on  = ["logger_plugin"]   # logger_plugin harus ada dulu

    def setup(self):
        self.fmt = self.config.get("format", "%Y-%m-%d %H:%M UTC")

    def on_before_llm(self, user_id, agent_id, messages):
        """Tambahkan info waktu ke system message pertama."""
        now = datetime.now(timezone.utc).strftime(self.fmt)

        if messages and messages[0]["role"] == "system":
            messages[0]["content"] += f"\n\nWaktu saat ini: {now}"
        else:
            messages.insert(0, {
                "role": "system",
                "content": f"Waktu saat ini: {now}"
            })

        # Track via state
        self.state.increment("injections")
        return messages

    def on_after_llm(self, user_id, agent_id, response):
        """Tidak mengubah response, hanya tracking."""
        return response
