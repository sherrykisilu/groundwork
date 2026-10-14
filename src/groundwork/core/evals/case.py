"""Suite and case models.

A suite is a YAML file. Keeping it declarative is the point: on an engagement the
person who knows what "correct" means is usually not the person writing Python, and
they need to be able to add a case without a pull request to the harness.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from ..agent.mcp_client import ServerConfig


class ScorerSpec(BaseModel):
    """One scorer and its parameters, as written in YAML."""

    type: str
    params: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    @classmethod
    def parse(cls, raw: Any) -> ScorerSpec:
        """Accept either `{type: contains, value: x}` or a bare string."""
        if isinstance(raw, str):
            return cls(type=raw)
        if not isinstance(raw, dict):
            raise ValueError(f"a scorer must be a string or a mapping, got {type(raw).__name__}")
        data = dict(raw)
        scorer_type = data.pop("type", None)
        if not scorer_type:
            raise ValueError("a scorer mapping needs a 'type' key")
        return cls(type=str(scorer_type), params=data)


class EvalCase(BaseModel):
    """One case: a prompt, the scorers that decide whether the answer was good."""

    id: str
    prompt: str
    description: str = ""
    skill: str | None = None
    recording: str | None = None
    max_iterations: int = 12
    scorers: list[ScorerSpec] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

    @field_validator("id")
    @classmethod
    def _id_is_usable(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("case id cannot be empty")
        return value.strip()


class EvalSuite(BaseModel):
    """A named set of cases run against the same servers and skill."""

    name: str
    description: str = ""
    skill: str | None = None
    servers: list[dict[str, Any]] = Field(default_factory=list)
    system_preamble: str = ""
    cases: list[EvalCase] = Field(default_factory=list)
    path: Path | None = None

    model_config = {"extra": "forbid", "arbitrary_types_allowed": True}

    def server_configs(self) -> list[ServerConfig]:
        """Resolve the raw server entries into launchable configs."""
        return [ServerConfig.from_dict(entry) for entry in self.servers]

    def case(self, case_id: str) -> EvalCase:
        """Look up one case by id."""
        for item in self.cases:
            if item.id == case_id:
                return item
        known = ", ".join(item.id for item in self.cases)
        raise KeyError(f"no case '{case_id}' in suite '{self.name}' (have: {known})")

    def select(self, only: list[str] | None) -> list[EvalCase]:
        """Filter cases by id, preserving suite order."""
        if not only:
            return list(self.cases)
        wanted = set(only)
        unknown = wanted - {item.id for item in self.cases}
        if unknown:
            raise KeyError(f"unknown case ids: {', '.join(sorted(unknown))}")
        return [item for item in self.cases if item.id in wanted]


def load_suite(path: str | Path) -> EvalSuite:
    """Load and validate a suite from YAML."""
    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"{resolved}: no such eval suite")
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{resolved}: a suite must be a YAML mapping")
    raw.setdefault("name", resolved.stem)
    cases = []
    for entry in raw.pop("cases", []) or []:
        case_data = dict(entry)
        case_data["scorers"] = [ScorerSpec.parse(item) for item in case_data.get("scorers", [])]
        cases.append(EvalCase(**case_data))
    suite = EvalSuite(**raw, cases=cases)
    suite.path = resolved
    return suite
