"""Tests for the tool calling loop.

The behaviour that matters most here is recovery. On a real engagement tools time
out, return 403, and get rate limited. An agent that dies on the first bad tool
result is not deployable, so the loop must hand the error back to the model and keep
going.
"""

from __future__ import annotations

from typing import Any

import pytest

from groundwork.core.agent.loop import run_agent
from groundwork.core.agent.providers import (
    AssistantTurn,
    ProviderError,
    Recorder,
    ReplayProvider,
    ToolCall,
    ToolSpec,
    parse_turns,
)


class FakeToolkit:
    """A Toolkit stand in. Tools are callables returning (text, is_error)."""

    def __init__(self, tools: dict[str, Any]) -> None:
        self._tools = tools
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def tool_specs(self) -> list[ToolSpec]:
        return [ToolSpec(name, "", {"type": "object", "properties": {}}) for name in self._tools]

    def server_for(self, name: str) -> str:
        return "fake"

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        self.calls.append((name, arguments))
        if name not in self._tools:
            return (f"Unknown tool '{name}'. Available tools: {', '.join(self._tools)}.", True)
        return self._tools[name](arguments)


def replay(*turns: dict[str, Any]) -> ReplayProvider:
    return ReplayProvider(parse_turns(list(turns)))


def call(name: str, **arguments: Any) -> dict[str, Any]:
    return {"id": f"c_{name}", "name": name, "arguments": arguments}


async def test_a_single_turn_answer_calls_nothing() -> None:
    toolkit = FakeToolkit({})
    transcript = await run_agent(
        provider=replay({"text": "no tools needed"}),
        toolkit=toolkit,
        prompt="hello",
    )
    assert transcript.final_text == "no tools needed"
    assert transcript.tool_calls == []
    assert transcript.turn_count == 1


async def test_tool_results_are_recorded_with_timing_and_owner() -> None:
    toolkit = FakeToolkit({"ok": lambda args: ("fine", False)})
    transcript = await run_agent(
        provider=replay({"tool_calls": [call("ok", x=1)]}, {"text": "done"}),
        toolkit=toolkit,
        prompt="go",
    )
    invocation = transcript.tool_calls[0]
    assert invocation.name == "ok"
    assert invocation.arguments == {"x": 1}
    assert invocation.server == "fake"
    assert invocation.duration_ms >= 0
    assert transcript.tool_names == ["ok"]


async def test_several_tools_in_one_turn_all_run() -> None:
    toolkit = FakeToolkit({"a": lambda args: ("1", False), "b": lambda args: ("2", False)})
    transcript = await run_agent(
        provider=replay({"tool_calls": [call("a"), call("b")]}, {"text": "done"}),
        toolkit=toolkit,
        prompt="go",
    )
    assert transcript.tool_names == ["a", "b"]
    assert transcript.tool_outputs() == "1\n2"


class TestErrorRecovery:
    async def test_a_failing_tool_does_not_stop_the_loop(self) -> None:
        toolkit = FakeToolkit(
            {
                "boom": lambda args: ("403 Forbidden", True),
                "fallback": lambda args: ("worked", False),
            }
        )
        transcript = await run_agent(
            provider=replay(
                {"tool_calls": [call("boom")]},
                {"tool_calls": [call("fallback")]},
                {"text": "recovered using the fallback"},
            ),
            toolkit=toolkit,
            prompt="go",
        )
        assert transcript.error is None
        assert transcript.final_text == "recovered using the fallback"
        assert [c.is_error for c in transcript.tool_calls] == [True, False]
        assert len(transcript.tool_errors) == 1

    async def test_the_error_text_is_fed_back_to_the_model(self) -> None:
        """The model only recovers if it can see what went wrong."""
        seen: list[str] = []

        class _Spy:
            name = "spy"

            def __init__(self) -> None:
                self.turns = parse_turns(
                    [{"tool_calls": [call("boom")]}, {"text": "saw the error"}]
                )
                self.cursor = 0

            def complete(self, *, system, messages, tools):
                del system, tools
                for message in messages:
                    for result in getattr(message, "results", []):
                        seen.append(result.content)
                turn = self.turns[self.cursor]
                self.cursor += 1
                return turn

        toolkit = FakeToolkit({"boom": lambda args: ("quota exceeded, retry in 900s", True)})
        await run_agent(provider=_Spy(), toolkit=toolkit, prompt="go")
        assert seen == ["quota exceeded, retry in 900s"]

    async def test_an_unknown_tool_name_lists_the_real_ones(self) -> None:
        toolkit = FakeToolkit({"real_tool": lambda args: ("ok", False)})
        transcript = await run_agent(
            provider=replay({"tool_calls": [call("imaginary_tool")]}, {"text": "oh"}),
            toolkit=toolkit,
            prompt="go",
        )
        assert transcript.tool_calls[0].is_error
        assert "real_tool" in transcript.tool_calls[0].output

    async def test_a_tool_that_raises_is_still_an_error_result(self) -> None:
        def explode(args: dict[str, Any]) -> tuple[str, bool]:
            raise RuntimeError("the server fell over")

        toolkit = FakeToolkit({"explode": explode})
        with pytest.raises(RuntimeError):
            await toolkit.call("explode", {})


class TestBudgets:
    async def test_max_iterations_stops_the_loop(self) -> None:
        toolkit = FakeToolkit({"loop": lambda args: ("again", False)})
        turns = [{"tool_calls": [call("loop")]} for _ in range(10)]
        transcript = await run_agent(
            provider=replay(*turns),
            toolkit=toolkit,
            prompt="go",
            max_iterations=3,
        )
        assert transcript.stopped_early
        assert transcript.turn_count == 3

    async def test_provider_exhaustion_is_captured_not_raised(self) -> None:
        toolkit = FakeToolkit({"a": lambda args: ("ok", False)})
        transcript = await run_agent(
            provider=replay({"tool_calls": [call("a")]}),
            toolkit=toolkit,
            prompt="go",
        )
        assert transcript.error is not None
        assert "recording exhausted" in transcript.error

    async def test_duration_is_measured(self) -> None:
        transcript = await run_agent(
            provider=replay({"text": "hi"}), toolkit=FakeToolkit({}), prompt="go"
        )
        assert transcript.duration_ms > 0


async def test_prose_alongside_a_tool_call_is_kept_as_interim_text() -> None:
    toolkit = FakeToolkit({"a": lambda args: ("ok", False)})
    transcript = await run_agent(
        provider=replay(
            {"text": "checking the graph", "tool_calls": [call("a")]}, {"text": "final"}
        ),
        toolkit=toolkit,
        prompt="go",
    )
    assert transcript.final_text == "final"


async def test_the_sink_sees_every_turn() -> None:
    recorder = Recorder("demo")
    toolkit = FakeToolkit({"a": lambda args: ("ok", False)})
    await run_agent(
        provider=replay({"tool_calls": [call("a")]}, {"text": "done"}),
        toolkit=toolkit,
        prompt="go",
        sink=recorder,
    )
    assert len(recorder.turns) == 2
    assert recorder.to_dict()["turns"][1]["text"] == "done"


async def test_transcript_serialises_for_the_report() -> None:
    toolkit = FakeToolkit({"a": lambda args: ("ok", False)})
    transcript = await run_agent(
        provider=replay({"tool_calls": [call("a", x=1)]}, {"text": "done"}),
        toolkit=toolkit,
        prompt="go",
    )
    payload = transcript.to_dict()
    assert payload["turns"] == 2
    assert payload["tool_calls"][0]["arguments"] == {"x": 1}
    assert payload["error"] is None


def test_provider_error_is_a_runtime_error() -> None:
    assert issubclass(ProviderError, RuntimeError)
    assert AssistantTurn(tool_calls=[ToolCall("c", "a", {})]).wants_tools
