"""The tool calling loop.

Deliberately small. It asks the provider for a turn, runs any tools the turn asked
for, feeds the results back, and repeats until the model stops asking for tools or
the iteration budget runs out. Everything that happens is captured in a `Transcript`,
which is the only thing the scorers ever look at.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .mcp_client import ToolInvocation, Toolkit
from .providers import (
    AssistantTurn,
    Message,
    ModelProvider,
    ToolResult,
    ToolResultTurn,
    UserTurn,
)

DEFAULT_MAX_ITERATIONS = 12


class TurnSink(Protocol):
    """Anything that wants a copy of each assistant turn, such as a `Recorder`."""

    def record(self, turn: AssistantTurn) -> None: ...


@dataclass
class Transcript:
    """Everything one agent run produced."""

    prompt: str
    final_text: str = ""
    turns: list[AssistantTurn] = field(default_factory=list)
    tool_calls: list[ToolInvocation] = field(default_factory=list)
    duration_ms: float = 0.0
    stopped_early: bool = False
    error: str | None = None

    @property
    def tool_names(self) -> list[str]:
        """Tool names in call order."""
        return [call.name for call in self.tool_calls]

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    @property
    def tool_errors(self) -> list[ToolInvocation]:
        return [call for call in self.tool_calls if call.is_error]

    def tool_outputs(self) -> str:
        """Every tool output concatenated. Used by grounding scorers."""
        return "\n".join(call.output for call in self.tool_calls)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "final_text": self.final_text,
            "turns": self.turn_count,
            "duration_ms": round(self.duration_ms, 1),
            "stopped_early": self.stopped_early,
            "error": self.error,
            "tool_calls": [
                {
                    "name": call.name,
                    "arguments": call.arguments,
                    "is_error": call.is_error,
                    "duration_ms": round(call.duration_ms, 1),
                    "server": call.server,
                }
                for call in self.tool_calls
            ],
        }


async def run_agent(
    *,
    provider: ModelProvider,
    toolkit: Toolkit,
    prompt: str,
    system: str = "",
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    sink: TurnSink | None = None,
) -> Transcript:
    """Run the agent until it answers or hits the iteration budget."""
    transcript = Transcript(prompt=prompt)
    messages: list[Message] = [UserTurn(text=prompt)]
    specs = toolkit.tool_specs()
    started = time.perf_counter()

    try:
        for iteration in range(max_iterations):
            turn = provider.complete(system=system, messages=messages, tools=specs)
            transcript.turns.append(turn)
            if sink is not None:
                sink.record(turn)
            messages.append(turn)

            if not turn.wants_tools:
                transcript.final_text = turn.text
                break

            if turn.text:
                # Keep the model's reasoning prose even when it also called a tool.
                transcript.final_text = turn.text

            results: list[ToolResult] = []
            for call in turn.tool_calls:
                call_started = time.perf_counter()
                output, is_error = await toolkit.call(call.name, call.arguments)
                elapsed = (time.perf_counter() - call_started) * 1000
                transcript.tool_calls.append(
                    ToolInvocation(
                        name=call.name,
                        arguments=call.arguments,
                        output=output,
                        is_error=is_error,
                        duration_ms=elapsed,
                        server=toolkit.server_for(call.name),
                    )
                )
                results.append(ToolResult(tool_use_id=call.id, content=output, is_error=is_error))
            messages.append(ToolResultTurn(results=results))

            if iteration == max_iterations - 1:
                transcript.stopped_early = True
    except Exception as exc:
        transcript.error = f"{type(exc).__name__}: {exc}"

    transcript.duration_ms = (time.perf_counter() - started) * 1000
    return transcript
