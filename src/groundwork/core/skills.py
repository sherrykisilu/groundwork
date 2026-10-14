"""Loading of SKILL.md files.

A skill is a written procedure handed to the agent as part of its system prompt.
The file format is deliberately boring: YAML frontmatter between two `---` fences,
then a markdown body. Keeping it boring means a non engineer on a customer team can
edit the procedure without touching Python.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

FRONTMATTER_FENCE = "---"
REQUIRED_KEYS = ("name", "description")


class SkillError(ValueError):
    """Raised when a SKILL.md file cannot be loaded or is malformed."""


@dataclass(frozen=True)
class Skill:
    """A named procedure with a markdown body."""

    name: str
    description: str
    body: str
    path: Path
    metadata: dict[str, Any]

    def as_system_prompt(self) -> str:
        """Render the skill in the form handed to the model."""
        return f"# Skill: {self.name}\n\n{self.description}\n\n{self.body}".strip()


def parse_skill(text: str, *, path: Path | None = None) -> Skill:
    """Parse the contents of a SKILL.md file.

    Args:
        text: Raw file contents.
        path: Optional source path, used for error messages and the `path` field.

    Raises:
        SkillError: If the frontmatter is missing, unparseable, or incomplete.
    """
    source = path or Path("<string>")
    stripped = text.lstrip("\ufeff")
    lines = stripped.splitlines()

    if not lines or lines[0].strip() != FRONTMATTER_FENCE:
        raise SkillError(f"{source}: missing YAML frontmatter, expected a leading '---' line")

    try:
        closing = next(
            i for i, line in enumerate(lines[1:], start=1) if line.strip() == FRONTMATTER_FENCE
        )
    except StopIteration as exc:
        raise SkillError(f"{source}: frontmatter is never closed with '---'") from exc

    raw_frontmatter = "\n".join(lines[1:closing])
    body = "\n".join(lines[closing + 1 :]).strip()

    try:
        loaded = yaml.safe_load(raw_frontmatter) or {}
    except yaml.YAMLError as exc:
        raise SkillError(f"{source}: frontmatter is not valid YAML: {exc}") from exc

    if not isinstance(loaded, dict):
        raise SkillError(f"{source}: frontmatter must be a mapping, got {type(loaded).__name__}")

    missing = [key for key in REQUIRED_KEYS if not str(loaded.get(key, "")).strip()]
    if missing:
        raise SkillError(f"{source}: frontmatter is missing required keys: {', '.join(missing)}")

    if not body:
        raise SkillError(f"{source}: skill body is empty, a skill needs an actual procedure")

    metadata = {k: v for k, v in loaded.items() if k not in REQUIRED_KEYS}
    return Skill(
        name=str(loaded["name"]).strip(),
        description=str(loaded["description"]).strip(),
        body=body,
        path=source,
        metadata=metadata,
    )


def load_skill(path: str | Path) -> Skill:
    """Load a single SKILL.md file from disk."""
    resolved = Path(path)
    if resolved.is_dir():
        resolved = resolved / "SKILL.md"
    if not resolved.is_file():
        raise SkillError(f"{resolved}: no such skill file")
    return parse_skill(resolved.read_text(encoding="utf-8"), path=resolved)


def discover_skills(root: str | Path) -> list[Skill]:
    """Load every SKILL.md found underneath `root`, sorted by name."""
    base = Path(root)
    if not base.is_dir():
        raise SkillError(f"{base}: skills directory does not exist")
    skills = [load_skill(found) for found in sorted(base.rglob("SKILL.md"))]
    return sorted(skills, key=lambda skill: skill.name)


def find_skill(root: str | Path, name: str) -> Skill:
    """Find a skill by its frontmatter name, or by its containing directory name."""
    base = Path(root)
    direct = base / name / "SKILL.md"
    if direct.is_file():
        return load_skill(direct)
    for skill in discover_skills(base):
        if skill.name == name:
            return skill
    available = ", ".join(skill.name for skill in discover_skills(base)) or "none"
    raise SkillError(f"no skill named '{name}' under {base} (available: {available})")
