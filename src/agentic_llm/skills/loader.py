from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any
from xml.sax.saxutils import escape


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<body>.*?)\n---\s*\n?", re.DOTALL)


@dataclass(frozen=True, slots=True)
class SkillMetadata:
    name: str
    description: str
    location: Path
    available: bool = True
    always: bool = False
    requires: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "location": str(self.location),
            "available": self.available,
            "always": self.always,
            "requires": self.requires,
        }


class SkillLoader:
    """Loads skill metadata and skill bodies from workspace skill directories."""

    def __init__(self, *, workspace_root: Path | str, skills_dir: str = "skills") -> None:
        self._workspace_root = Path(workspace_root).resolve()
        self._skills_root = (self._workspace_root / skills_dir).resolve()

    @property
    def skills_root(self) -> Path:
        return self._skills_root

    def list_skills(self) -> list[SkillMetadata]:
        if not self._skills_root.exists():
            return []

        skills: list[SkillMetadata] = []
        for path in sorted(self._skills_root.glob("*/SKILL.md")):
            if not path.is_file():
                continue
            metadata = self._load_metadata(path)
            if metadata is not None:
                skills.append(metadata)
        return skills

    def build_index_xml(self) -> str:
        skills = self.list_skills()
        if not skills:
            return ""

        lines = ["<skills>"]
        for skill in skills:
            lines.append(f'  <skill available="{str(skill.available).lower()}">')
            lines.append(f"    <name>{escape(skill.name)}</name>")
            lines.append(f"    <description>{escape(skill.description)}</description>")
            lines.append(f"    <location>{escape(str(skill.location))}</location>")
            lines.append(f"    <always>{str(skill.always).lower()}</always>")
            if skill.requires:
                lines.append(f"    <requires>{escape(skill.requires)}</requires>")
            lines.append("  </skill>")
        lines.append("</skills>")
        return "\n".join(lines)

    def read_skill(self, name: str) -> str:
        metadata = self.get_skill(name)
        if metadata is None:
            raise KeyError(f"Unknown skill: {name}")
        return metadata.location.read_text(encoding="utf-8")

    def get_skill(self, name: str) -> SkillMetadata | None:
        for skill in self.list_skills():
            if skill.name == name:
                return skill
        return None

    def _load_metadata(self, path: Path) -> SkillMetadata | None:
        raw = path.read_text(encoding="utf-8")
        parsed = _parse_frontmatter(raw)
        inferred_name = path.parent.name
        name = str(parsed.get("name") or inferred_name).strip()
        description = str(parsed.get("description") or "").strip()
        if not name or not description:
            return None

        requires = parsed.get("requires")
        return SkillMetadata(
            name=name,
            description=description,
            location=path,
            available=_to_bool(parsed.get("available"), default=True),
            always=_to_bool(parsed.get("always"), default=False),
            requires=str(requires).strip() if requires else None,
        )


def _parse_frontmatter(raw: str) -> dict[str, Any]:
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        return {}

    values: dict[str, Any] = {}
    for line in match.group("body").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _to_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
