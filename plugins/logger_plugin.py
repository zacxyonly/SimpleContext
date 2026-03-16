"""
Logger Plugin v2
Catat setiap pesan + statistik penggunaan.
State (total_messages) disimpan permanen ke DB.

Config di config.yaml:
    plugins:
      logger_plugin:
        enabled: true
        log_path: ./sc_messages.log
        log_skills: false
"""

import os, json
from datetime import datetime, timezone
from simplecontext.plugins.base import BasePlugin


class LoggerPlugin(BasePlugin):
    name        = "logger_plugin"
    version     = "2.0.0"
    description = "Catat pesan + statistik ke file log. State permanen."

    def setup(self):
        self.log_path  = self.config.get("log_path", "./sc_messages.log")
        self.log_skills = self.config.get("log_skills", False)
        os.makedirs(os.path.dirname(self.log_path) if os.path.dirname(self.log_path) else ".", exist_ok=True)

    def on_message_saved(self, user_id, role, content, tags, metadata):
        # Increment counter permanen via self.state
        total = self.state.increment("total_messages")

        entry = {
            "ts":              datetime.now(timezone.utc).isoformat(),
            "user_id":         user_id,
            "role":            role,
            "content_preview": content[:80],
            "tags":            tags,
            "total_so_far":    total,
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def on_skill_saved(self, agent_id, name, content):
        if not self.log_skills:
            return
        self.state.increment("total_skill_saves")
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": "skill_saved",
                "agent_id": agent_id,
                "name": name,
            }, ensure_ascii=False) + "\n")

    def on_agent_routed(self, user_id, agent_id, message):
        routes = self.state.get("routes", {})
        routes[agent_id] = routes.get(agent_id, 0) + 1
        self.state.set("routes", routes)

    def on_after_llm(self, user_id, agent_id, response):
        self.state.increment("total_llm_calls")
        return response  # tidak mengubah response
