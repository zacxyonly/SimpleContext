"""
AgentDef — Parse & Validasi YAML Agent Definition
Satu file YAML = satu agent definition.
"""

import os
import json
from typing import Optional
from ..config.schema import _parse_yaml, _cast


class AgentDef:
    """
    Representasi satu agent yang dibaca dari file YAML.

    Field YAML yang didukung:
        name, description, triggers, personality,
        skills, chain, metadata
    """

    def __init__(self, data: dict, source_file: str = ""):
        self._data       = data
        self.source_file = source_file
        self._validate()

    # ── Properties ────────────────────────────────────────

    @property
    def name(self) -> str:
        return self._data.get("name", "")

    @property
    def description(self) -> str:
        return self._data.get("description", "")

    @property
    def triggers(self) -> dict:
        """
        Aturan auto-routing.
        {
          "keywords": ["code", "bug", ...],
          "priority": 10,
          "regex": ["^/code", ...],   # opsional
        }
        """
        return self._data.get("triggers", {})

    @property
    def keywords(self) -> list[str]:
        return [k.lower() for k in self.triggers.get("keywords", [])]

    @property
    def priority(self) -> int:
        return int(self.triggers.get("priority", 0))

    @property
    def personality(self) -> dict:
        """
        Dict personality per level user.
        {
          "default": "Kamu adalah...",
          "beginner": "Kamu adalah guru yang sabar...",
          "expert": "Senior engineer, jawab singkat...",
        }
        """
        raw = self._data.get("personality", {})
        if isinstance(raw, str):
            return {"default": raw}
        return raw

    def get_personality(self, level: str = "default") -> str:
        """Ambil personality string berdasarkan level user."""
        p = self.personality
        return p.get(level) or p.get("default", "")

    @property
    def skills(self) -> list[dict]:
        """
        List skill yang didefinisikan langsung di YAML agent.
        [
          {"name": "format", "content": "...", "priority": 10, "group": "output"},
          ...
        ]
        """
        return self._data.get("skills", [])

    @property
    def chain_rules(self) -> list[dict]:
        """
        Aturan handoff ke agent lain.
        [
          {"condition": "deploy OR server", "to": "devops", "message": "..."},
          ...
        ]
        """
        return self._data.get("chain", [])

    @property
    def metadata(self) -> dict:
        return self._data.get("metadata", {})

    # ── Methods ───────────────────────────────────────────

    def matches(self, message: str) -> int:
        """
        Cek apakah pesan ini cocok untuk agent ini.
        Return skor match (0 = tidak cocok, > 0 = cocok).
        Skor lebih tinggi = agent lebih relevan.
        """
        msg_lower = message.lower()
        score = 0

        for kw in self.keywords:
            if kw in msg_lower:
                score += 1 + self.priority

        return score

    def should_chain(self, response: str) -> Optional[dict]:
        """
        Cek apakah response LLM mengandung sinyal untuk chain ke agent lain.
        Return rule dict jika harus chain, None jika tidak.
        """
        response_lower = response.lower()
        for rule in self.chain_rules:
            condition = rule.get("condition", "")
            # Parse condition: "deploy OR server OR hosting"
            terms = [t.strip().lower() for t in condition.replace(" OR ", "|").split("|")]
            if any(t in response_lower for t in terms):
                return rule
        return None

    def to_dict(self) -> dict:
        return self._data.copy()

    def _validate(self):
        if not self.name:
            raise ValueError(f"Agent definition harus punya 'name' (file: {self.source_file})")

    # ── Class Methods ─────────────────────────────────────

    @classmethod
    def from_file(cls, path: str) -> "AgentDef":
        """Load AgentDef dari file YAML atau JSON."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Agent file tidak ditemukan: {path}")

        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()

        if path.endswith(".json"):
            data = json.loads(content)
        elif path.endswith((".yaml", ".yml")):
            data = _parse_agent_yaml(content)
        else:
            raise ValueError(f"Format tidak dikenali: {path}")

        return cls(data, source_file=path)

    @classmethod
    def from_dict(cls, data: dict) -> "AgentDef":
        return cls(data)

    def __repr__(self):
        return f"<AgentDef name={self.name!r} keywords={self.keywords[:3]} priority={self.priority}>"


# ── YAML parser khusus untuk agent YAML ───────────────────
# Support list items (- item) dan nested dict

def _parse_agent_yaml(content: str) -> dict:
    """
    Parser YAML yang support:
    - list items (- item)
    - nested dict
    - block scalar multi-line string (|)
    """
    lines = [l.rstrip() for l in content.splitlines()]
    result, _ = _parse_block(lines, 0, 0)
    return result


def _parse_block(lines: list, start: int, base_indent: int) -> tuple[dict, int]:
    result = {}
    i = start

    while i < len(lines):
        raw = lines[i]
        stripped = raw.lstrip()

        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        indent = len(raw) - len(stripped)

        if indent < base_indent:
            break

        if stripped.startswith("- "):
            break

        if ":" not in stripped:
            i += 1
            continue

        key, _, raw_val = stripped.partition(":")
        key     = key.strip()
        val_str = raw_val.strip()

        # Block scalar: value adalah "|" → ambil baris berikutnya sebagai multi-line string
        if val_str in ("|", ">"):
            text_lines = []
            j = i + 1
            while j < len(lines):
                sub_raw = lines[j]
                if not sub_raw.strip():
                    text_lines.append("")
                    j += 1
                    continue
                sub_indent = len(sub_raw) - len(sub_raw.lstrip())
                if sub_indent <= indent:
                    break
                text_lines.append(sub_raw[indent + 2:] if len(sub_raw) > indent + 2 else sub_raw.lstrip())
                j += 1
            result[key] = "\n".join(text_lines).strip()
            i = j
            continue

        if val_str == "" or val_str.startswith("#"):
            # Cek berikutnya: list atau dict
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].strip().startswith("#")):
                j += 1

            if j < len(lines):
                next_stripped = lines[j].lstrip()
                next_indent   = len(lines[j]) - len(next_stripped)

                if next_stripped.startswith("- "):
                    items, i = _parse_list(lines, j, next_indent)
                    result[key] = items
                elif next_indent > indent:
                    sub, i = _parse_block(lines, j, next_indent)
                    result[key] = sub
                else:
                    result[key] = None
                    i = j
            else:
                result[key] = None
                i = j
        else:
            if " #" in val_str:
                val_str = val_str[:val_str.index(" #")].strip()
            result[key] = _cast(val_str)
            i += 1

    return result, i


def _parse_list(lines: list, start: int, base_indent: int) -> tuple[list, int]:
    items = []
    i     = start

    while i < len(lines):
        raw      = lines[i]
        stripped = raw.lstrip()

        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        indent = len(raw) - len(stripped)

        if indent < base_indent:
            break

        if not stripped.startswith("- "):
            break

        item_content = stripped[2:].strip()

        # Kumpulkan baris lanjutan (indentasi lebih dalam)
        j = i + 1
        sub_lines = []
        while j < len(lines):
            sub_raw      = lines[j]
            sub_stripped = sub_raw.lstrip()
            if not sub_stripped or sub_stripped.startswith("#"):
                j += 1
                continue
            sub_indent = len(sub_raw) - len(sub_stripped)
            if sub_indent <= base_indent and not sub_stripped.startswith("- "):
                break
            if sub_indent > base_indent:
                sub_lines.append(sub_raw)
                j += 1
            else:
                break

        if ":" in item_content or sub_lines:
            # Dict item
            all_lines = []
            if ":" in item_content:
                all_lines.append(" " * (base_indent + 2) + item_content)
            all_lines.extend(sub_lines)
            if all_lines:
                sub_dict, _ = _parse_block(all_lines, 0, base_indent + 2)
                items.append(sub_dict)
            else:
                items.append(_cast(item_content))
            i = j
        else:
            items.append(_cast(item_content))
            i += 1

    return items, i
