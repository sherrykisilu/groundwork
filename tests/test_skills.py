"""Tests for SKILL.md loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from groundwork.core.skills import (
    Skill,
    SkillError,
    discover_skills,
    find_skill,
    load_skill,
    parse_skill,
)

GOOD = """---
name: example
description: Does a thing.
owner: sherry
---

## Procedure

1. Do the thing.
"""


def test_parse_skill_reads_frontmatter_and_body() -> None:
    skill = parse_skill(GOOD)
    assert skill.name == "example"
    assert skill.description == "Does a thing."
    assert "Do the thing." in skill.body
    assert skill.metadata == {"owner": "sherry"}


def test_as_system_prompt_includes_name_and_body() -> None:
    rendered = parse_skill(GOOD).as_system_prompt()
    assert rendered.startswith("# Skill: example")
    assert "Do the thing." in rendered


def test_leading_byte_order_mark_is_tolerated() -> None:
    assert parse_skill("\ufeff" + GOOD).name == "example"


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("no frontmatter here", "missing YAML frontmatter"),
        ("---\nname: x\ndescription: y\n\nbody", "never closed"),
        ("---\nname: [unclosed\n---\nbody", "not valid YAML"),
        ("---\njust a string\n---\nbody", "must be a mapping"),
        ("---\nname: x\n---\nbody", "missing required keys"),
        ("---\nname: x\ndescription: y\n---\n\n   \n", "body is empty"),
    ],
)
def test_malformed_skills_raise(text: str, fragment: str) -> None:
    with pytest.raises(SkillError) as excinfo:
        parse_skill(text)
    assert fragment in str(excinfo.value)


def test_load_skill_accepts_a_directory(tmp_path: Path) -> None:
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "SKILL.md").write_text(GOOD, encoding="utf-8")
    assert load_skill(folder).name == "example"


def test_load_skill_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SkillError, match="no such skill file"):
        load_skill(tmp_path / "nope")


def test_discover_skills_requires_a_directory(tmp_path: Path) -> None:
    with pytest.raises(SkillError, match="does not exist"):
        discover_skills(tmp_path / "missing")


def test_find_skill_error_lists_available(tmp_path: Path) -> None:
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "SKILL.md").write_text(GOOD, encoding="utf-8")
    with pytest.raises(SkillError, match="available: example"):
        find_skill(tmp_path, "other")


def test_repository_skills_all_load(repo_root: Path) -> None:
    skills = discover_skills(repo_root / "skills")
    names = {skill.name for skill in skills}
    assert {"adf-triage", "compliance-answer"} <= names
    for skill in skills:
        assert isinstance(skill, Skill)
        # A skill that does not say when to stop is not a procedure, it is a vibe.
        assert "stop" in skill.body.lower()
        assert len(skill.body) > 800
