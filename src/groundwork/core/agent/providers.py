"""Model providers.

Two implementations ship with groundwork:

`AnthropicProvider`
    Calls the real Claude API. Used when you are developing a skill, recording
    transcripts, or running a judge scorer.

`ReplayProvider`
    Replays a recorded transcript from disk. No network, no API key, no cost, and
    identical results on every run. This is what CI uses.

The replay design is worth being explicit about, because it is the reason the eval
suite is useful rather than decorative. Only the *model turns* are replayed. Tool
calls are still executed for real against the MCP servers, so a change that breaks a
server, a fixture, or a tool schema still fails the suite. What replay removes is the
model's nondeterminism, not the system under test.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

DEFAULT_MODEL = "claude-sonnet-4-5-20250929"


class ProviderError(RuntimeError):
    """Raised when a provider cannot produce a turn."""


@dataclass(frozen=True)
class ToolSpec:
    """A tool as advertised to the model."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    """A single tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """The outcome of a tool invocation, fed back to the model."""

    tool_use_id: str
    content: str
    is_error: bool = False


@dataclass
class AssistantTurn:
    """One assistant message: optional prose plus zero or more tool calls."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class UserTurn:
    """A user message."""

    text: str


@dataclass
class ToolResultTurn:
    """A batch of tool results answering the previous assistant turn."""

    results: list[ToolResult]


Message = UserTurn | AssistantTurn | ToolResultTurn


@runtime_checkable
class ModelProvider(Protocol):
    """Anything that can produce the next assistant turn in a conversation."""

    name: str

    def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> AssistantTurn:
        """Produce the next assistant turn."""
        ...


def to_anthropic_messages(messages: Iterable[Message]) -> list[dict[str, Any]]:
    """Convert the neutral conversation form into the Anthropic messages format."""
    out: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, UserTurn):
            out.append({"role": "user", "content": message.text})
        elif isinstance(message, AssistantTurn):
            blocks: list[dict[str, Any]] = []
            if message.text:
                blocks.append({"type": "text", "text": message.text})
            for call in message.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": call.arguments,
                    }
                )
            out.append({"role": "assistant", "content": blocks})
        else:
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": result.tool_use_id,
                            "content": result.content,
                            "is_error": result.is_error,
                        }
                        for result in message.results
                    ],
                }
            )
    return out


class AnthropicProvider:
    """Calls the Claude API through the official `anthropic` SDK."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 2048,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.name = "anthropic"
        self.model = model
        self.max_tokens = max_tokens
        if client is not None:
            self._client = client
            return
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderError(
                "ANTHROPIC_API_KEY is not set. Use --provider replay to run offline."
            )
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ProviderError("the 'anthropic' package is not installed") from exc
        self._client = anthropic.Anthropic(api_key=key)

    def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> AssistantTurn:
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": to_anthropic_messages(messages),
        }
        if system:
            request["system"] = system
        if tools:
            request["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                for tool in tools
            ]
        response = self._client.messages.create(**request)
        return turn_from_anthropic(response)


def turn_from_anthropic(response: Any) -> AssistantTurn:
    """Translate an Anthropic response object into an `AssistantTurn`."""
    text_parts: list[str] = []
    calls: list[ToolCall] = []
    for block in getattr(response, "content", []) or []:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text_parts.append(getattr(block, "text", ""))
        elif block_type == "tool_use":
            calls.append(
                ToolCall(
                    id=getattr(block, "id", ""),
                    name=getattr(block, "name", ""),
                    arguments=dict(getattr(block, "input", {}) or {}),
                )
            )
    return AssistantTurn(
        text="\n".join(part for part in text_parts if part).strip(),
        tool_calls=calls,
        stop_reason=getattr(response, "stop_reason", "end_turn") or "end_turn",
    )


class ReplayProvider:
    """Replays a recorded list of assistant turns, in order."""

    def __init__(self, turns: list[AssistantTurn], *, source: str = "<memory>") -> None:
        self.name = "replay"
        self.source = source
        self._turns = list(turns)
        self._cursor = 0

    @classmethod
    def from_file(cls, path: str | Path) -> ReplayProvider:
        """Load a recording written by `Recorder`."""
        resolved = Path(path)
        if not resolved.is_file():
            raise ProviderError(
                f"{resolved}: no recording found. Run with --provider anthropic --record "
                "to create one."
            )
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        return cls(parse_turns(payload.get("turns", [])), source=str(resolved))

    @property
    def remaining(self) -> int:
        """How many recorded turns have not been replayed yet."""
        return len(self._turns) - self._cursor

    def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> AssistantTurn:
        del system, messages, tools  # a replay ignores the live conversation by design
        if self._cursor >= len(self._turns):
            raise ProviderError(
                f"{self.source}: recording exhausted after {len(self._turns)} turns. "
                "The agent asked for more turns than were recorded."
            )
        turn = self._turns[self._cursor]
        self._cursor += 1
        return AssistantTurn(
            text=turn.text,
            tool_calls=[ToolCall(c.id, c.name, dict(c.arguments)) for c in turn.tool_calls],
            stop_reason=turn.stop_reason,
        )


def parse_turns(raw: list[dict[str, Any]]) -> list[AssistantTurn]:
    """Build `AssistantTurn` objects from recording JSON."""
    turns: list[AssistantTurn] = []
    for index, item in enumerate(raw):
        calls = [
            ToolCall(
                id=str(call.get("id") or f"call_{index}_{position}"),
                name=str(call["name"]),
                arguments=dict(call.get("arguments") or {}),
            )
            for position, call in enumerate(item.get("tool_calls") or [])
        ]
        turns.append(
            AssistantTurn(
                text=str(item.get("text") or ""),
                tool_calls=calls,
                stop_reason=str(item.get("stop_reason") or ("tool_use" if calls else "end_turn")),
            )
        )
    return turns


class Recorder:
    """Collects assistant turns during a live run so they can be replayed later."""

    def __init__(self, case_id: str, *, model: str = DEFAULT_MODEL) -> None:
        self.case_id = case_id
        self.model = model
        self.turns: list[AssistantTurn] = []

    def record(self, turn: AssistantTurn) -> None:
        """Append one assistant turn to the recording."""
        self.turns.append(turn)

    def to_dict(self) -> dict[str, Any]:
        """Return the recording as a JSON serialisable dict."""
        return {
            "case_id": self.case_id,
            "model": self.model,
            "turns": [asdict(turn) for turn in self.turns],
        }

    def write(self, path: str | Path) -> Path:
        """Write the recording to disk, creating parent directories."""
        resolved = Path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return resolved
