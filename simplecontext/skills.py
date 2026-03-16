"""
Skills v3
Tambahan: groups, conditions (skill aktif berdasarkan kondisi runtime).
"""

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .storage.base import BaseStorage
    from .plugins.loader import PluginLoader


class Skills:

    def __init__(self, storage: "BaseStorage", plugins: "PluginLoader",
                 agent_id: str, max_inheritance_depth: int = 5):
        self._storage   = storage
        self._plugins   = plugins
        self.agent_id   = str(agent_id)
        self._max_depth = max_inheritance_depth

    # ── CRUD ──────────────────────────────────────────────

    def add(self, name: str, content: str, *,
            description: str = "",
            extends: str = None,
            enabled: bool = True,
            priority: int = 0,
            group: str = None,
            conditions: dict = None,
            tags: list = None,
            metadata: dict = None) -> "Skills":
        """
        Tambah atau update skill.

        Args:
            name:        nama unik skill
            content:     isi instruksi skill (bisa pakai {{variabel}})
            description: deskripsi singkat
            extends:     nama skill yang di-inherit
            enabled:     aktif atau tidak
            priority:    urutan di prompt (makin besar makin atas)
            group:       nama group untuk pengelompokan
            conditions:  dict kondisi agar skill aktif, contoh:
                         {"profile.level": "expert"}
                         {"profile.lang": ["python", "javascript"]}
            tags:        label bebas
            metadata:    data tambahan bebas
        """
        if extends and not self._storage.get_skill(self.agent_id, extends):
            raise ValueError(f"Skill '{extends}' tidak ditemukan untuk di-extend.")

        self._storage.save_skill(
            self.agent_id, name, content,
            description=description, extends=extends,
            enabled=enabled, priority=priority,
            group=group, conditions=conditions or {},
            tags=tags or [], metadata=metadata or {},
        )
        self._plugins.fire_skill_saved(self.agent_id, name, content)
        return self

    def get(self, name: str) -> Optional[dict]:
        return self._storage.get_skill(self.agent_id, name)

    def all(self, enabled_only: bool = True,
            group: str = None, tags: list = None) -> list[dict]:
        return self._storage.get_skills(self.agent_id, enabled_only, group, tags)

    def delete(self, name: str) -> bool:
        result = self._storage.delete_skill(self.agent_id, name)
        if result:
            self._plugins.fire_skill_deleted(self.agent_id, name)
        return result

    def search(self, keyword: str) -> list[dict]:
        return self._storage.search_skills(self.agent_id, keyword)

    def exists(self, name: str) -> bool:
        return self.get(name) is not None

    # ── Enable / Disable / Priority ───────────────────────

    def enable(self, name: str) -> "Skills":
        return self._update(name, enabled=True)

    def disable(self, name: str) -> "Skills":
        return self._update(name, enabled=False)

    def set_priority(self, name: str, priority: int) -> "Skills":
        return self._update(name, priority=priority)

    def set_group(self, name: str, group: str) -> "Skills":
        return self._update(name, group=group)

    def set_conditions(self, name: str, conditions: dict) -> "Skills":
        return self._update(name, conditions=conditions)

    def _update(self, name: str, **kwargs) -> "Skills":
        skill = self.get(name)
        if not skill:
            raise ValueError(f"Skill '{name}' tidak ditemukan")
        skill.update(kwargs)
        self._storage.save_skill(
            self.agent_id, name, skill["content"],
            description=skill.get("description",""),
            extends=skill.get("extends"),
            enabled=skill.get("enabled", True),
            priority=skill.get("priority", 0),
            group=skill.get("group"),
            conditions=skill.get("conditions",{}),
            tags=skill.get("tags",[]),
            metadata=skill.get("metadata",{}),
        )
        return self

    # ── Groups ────────────────────────────────────────────

    def group(self, group_name: str) -> "SkillGroup":
        """
        Akses skill dalam group tertentu.

        Contoh:
            sc.skills("coding").group("output").build_prompt()
        """
        return SkillGroup(self, group_name)

    def list_groups(self) -> list[str]:
        """Daftar semua group yang ada."""
        skills = self.all(enabled_only=False)
        groups = {s.get("group") for s in skills if s.get("group")}
        return sorted(groups)

    # ── Conditions ────────────────────────────────────────

    def check_condition(self, skill: dict, profile: dict) -> bool:
        """
        Evaluasi kondisi skill terhadap profil user.

        Contoh kondisi:
            {"profile.level": "expert"}
            → True jika profile["level"] == "expert"

            {"profile.level": ["expert", "senior"]}
            → True jika profile["level"] ada di list tersebut

            {}  → selalu True (tidak ada kondisi)
        """
        conditions = skill.get("conditions") or {}
        if not conditions:
            return True

        for key, expected in conditions.items():
            # Support dot notation: "profile.level" → profile["level"]
            if key.startswith("profile."):
                field = key[len("profile."):]
                actual = profile.get(field)
            else:
                actual = profile.get(key)

            if isinstance(expected, list):
                if actual not in expected:
                    return False
            else:
                if actual != expected:
                    return False

        return True

    # ── Inheritance ───────────────────────────────────────

    def resolve(self, name: str) -> Optional[dict]:
        return self._resolve_chain(name, depth=0, visited=set())

    def _resolve_chain(self, name, depth, visited) -> Optional[dict]:
        if depth > self._max_depth:
            raise RecursionError(f"Inheritance terlalu dalam (max {self._max_depth})")
        if name in visited:
            raise RecursionError(f"Circular inheritance pada skill '{name}'")

        skill = self.get(name)
        if not skill:
            return None

        visited = visited | {name}
        if not skill.get("extends"):
            return skill.copy()

        parent = self._resolve_chain(skill["extends"], depth + 1, visited)
        if not parent:
            return skill.copy()

        merged = skill.copy()
        merged["content"] = f"{parent['content']}\n\n{skill['content']}"
        merged["_inherited_from"] = skill["extends"]
        return merged

    # ── Build Prompt ──────────────────────────────────────

    def build_prompt(self, names: list[str] = None, group: str = None,
                     tags: list = None, profile: dict = None,
                     resolve_inheritance: bool = True) -> str:
        """
        Buat string prompt dari skills.

        Args:
            names:               skill tertentu saja (None = semua aktif)
            group:               filter by group
            tags:                filter by tag
            profile:             profil user untuk evaluasi conditions
            resolve_inheritance: resolve inheritance chain
        """
        if names:
            raw_skills = [self.get(n) for n in names if self.get(n)]
        else:
            raw_skills = self.all(enabled_only=True, group=group, tags=tags)

        if not raw_skills:
            return ""

        # Filter berdasarkan conditions
        if profile:
            raw_skills = [s for s in raw_skills if self.check_condition(s, profile)]

        if not raw_skills:
            return ""

        parts = []
        for skill in raw_skills:
            if resolve_inheritance and skill.get("extends"):
                display = self.resolve(skill["name"]) or skill
            else:
                display = skill

            part = f"=== {display['name'].upper()} ===\n"
            if display.get("description"):
                part += f"# {display['description']}\n"
            part += display["content"]
            parts.append(part)

        return "\n\n".join(parts)

    def build_system_prompt(self, base: str = "", names: list[str] = None,
                             group: str = None, tags: list = None,
                             profile: dict = None,
                             resolve_inheritance: bool = True) -> str:
        """
        Gabungkan base prompt dengan skills menjadi system prompt lengkap.
        Plugin bisa modifikasi hasil via on_prompt_build hook.
        """
        skills_text = self.build_prompt(names, group, tags, profile, resolve_inheritance)

        if base and skills_text:
            prompt = f"{base}\n\n{skills_text}"
        elif base:
            prompt = base
        else:
            prompt = skills_text

        return self._plugins.fire_prompt_build(self.agent_id, prompt)

    def sync_from_agent(self, agent_skills: list[dict]):
        """
        Sync skills dari definisi agent YAML.
        Skills yang ada di YAML tapi tidak di DB → di-add.
        Skills yang sudah ada → di-update.
        """
        for skill_def in agent_skills:
            name = skill_def.get("name")
            if not name:
                continue
            self.add(
                name=name,
                content=skill_def.get("content", ""),
                description=skill_def.get("description", ""),
                extends=skill_def.get("extends"),
                enabled=skill_def.get("enabled", True),
                priority=skill_def.get("priority", 0),
                group=skill_def.get("group"),
                conditions=skill_def.get("conditions", {}),
                tags=skill_def.get("tags", []),
                metadata=skill_def.get("metadata", {}),
            )

    # ── Info ──────────────────────────────────────────────

    def list_names(self, enabled_only: bool = True) -> list[str]:
        return [s["name"] for s in self.all(enabled_only=enabled_only)]

    def count(self, enabled_only: bool = False) -> int:
        return len(self.all(enabled_only=enabled_only))

    def summary(self) -> dict:
        all_skills = self.all(enabled_only=False)
        return {
            "agent_id": self.agent_id,
            "total":    len(all_skills),
            "enabled":  len([s for s in all_skills if s["enabled"]]),
            "disabled": len([s for s in all_skills if not s["enabled"]]),
            "groups":   self.list_groups(),
            "skills": [
                {"name": s["name"], "description": s.get("description",""),
                 "enabled": s["enabled"], "priority": s.get("priority",0),
                 "group": s.get("group"), "conditions": s.get("conditions",{})}
                for s in all_skills
            ],
        }

    def __repr__(self):
        return f"<Skills agent_id={self.agent_id!r} total={self.count(False)} enabled={self.count(True)}>"


class SkillGroup:
    """Helper untuk operasi pada group skill tertentu."""

    def __init__(self, skills: Skills, group_name: str):
        self._skills = skills
        self._group  = group_name

    def add(self, name: str, content: str, **kwargs) -> "SkillGroup":
        self._skills.add(name, content, group=self._group, **kwargs)
        return self

    def all(self) -> list[dict]:
        return self._skills.all(enabled_only=True, group=self._group)

    def build_prompt(self, profile: dict = None) -> str:
        return self._skills.build_prompt(group=self._group, profile=profile)

    def count(self) -> int:
        return len(self.all())

    def __repr__(self):
        return f"<SkillGroup agent={self._skills.agent_id!r} group={self._group!r} count={self.count()}>"
