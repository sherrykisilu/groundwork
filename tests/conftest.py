"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from groundwork.core.agent.loop import Transcript
from groundwork.core.agent.mcp_client import ToolInvocation

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo_root() -> Path:
    """The repository root, so tests can reach skills/ and evals/."""
    return REPO_ROOT


def invocation(
    name: str,
    arguments: dict | None = None,
    output: str = "",
    *,
    is_error: bool = False,
) -> ToolInvocation:
    """Build a ToolInvocation without going near a real server."""
    return ToolInvocation(
        name=name,
        arguments=arguments or {},
        output=output,
        is_error=is_error,
        duration_ms=1.0,
        server="test",
    )


def transcript(
    final_text: str = "",
    calls: list[ToolInvocation] | None = None,
    *,
    turns: int = 1,
    prompt: str = "test prompt",
) -> Transcript:
    """Build a Transcript directly, for scorer tests."""
    from groundwork.core.agent.providers import AssistantTurn

    return Transcript(
        prompt=prompt,
        final_text=final_text,
        turns=[AssistantTurn(text="") for _ in range(turns)],
        tool_calls=list(calls or []),
    )
