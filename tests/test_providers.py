"""Tests for the model providers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from groundwork.core.agent.providers import (
    AnthropicProvider,
    AssistantTurn,
    ProviderError,
    Recorder,
    ReplayProvider,
    ToolCall,
    ToolResult,
    ToolResultTurn,
    UserTurn,
    parse_turns,
    to_anthropic_messages,
    turn_from_anthropic,
)

RECORDING = {
    "case_id": "demo",
    "model": "claude-sonnet-4-5-20250929",
    "note": "extra keys are ignored on purpose, so recordings can be annotated",
    "turns": [
        {
            "text": "",
            "stop_reason": "tool_use",
            "tool_calls": [{"id": "c1", "name": "list_pipelines", "arguments": {"factory": "f"}}],
        },
        {"text": "done", "stop_reason": "end_turn"},
    ],
}


class TestParseTurns:
    def test_reads_text_and_calls(self) -> None:
        turns = parse_turns(RECORDING["turns"])
        assert turns[0].tool_calls[0].name == "list_pipelines"
        assert turns[1].text == "done"

    def test_infers_stop_reason(self) -> None:
        turns = parse_turns([{"tool_calls": [{"name": "a"}]}, {"text": "hi"}])
        assert turns[0].stop_reason == "tool_use"
        assert turns[1].stop_reason == "end_turn"

    def test_invents_a_call_id_when_absent(self) -> None:
        assert parse_turns([{"tool_calls": [{"name": "a"}]}])[0].tool_calls[0].id

    def test_a_call_without_a_name_is_an_error(self) -> None:
        with pytest.raises(KeyError):
            parse_turns([{"tool_calls": [{"id": "c1"}]}])


class TestReplayProvider:
    def test_replays_in_order(self) -> None:
        provider = ReplayProvider(parse_turns(RECORDING["turns"]))
        first = provider.complete(system="", messages=[], tools=[])
        second = provider.complete(system="", messages=[], tools=[])
        assert first.tool_calls[0].name == "list_pipelines"
        assert second.text == "done"
        assert provider.remaining == 0

    def test_ignores_the_live_conversation_by_design(self) -> None:
        provider = ReplayProvider(parse_turns(RECORDING["turns"]))
        a = provider.complete(system="one", messages=[UserTurn("a")], tools=[])
        provider_b = ReplayProvider(parse_turns(RECORDING["turns"]))
        b = provider_b.complete(system="totally different", messages=[], tools=[])
        assert a.tool_calls[0].name == b.tool_calls[0].name

    def test_arguments_are_copied_not_shared(self) -> None:
        provider = ReplayProvider(parse_turns(RECORDING["turns"]))
        turn = provider.complete(system="", messages=[], tools=[])
        turn.tool_calls[0].arguments["factory"] = "mutated"
        provider_again = ReplayProvider(parse_turns(RECORDING["turns"]))
        assert (
            provider_again.complete(system="", messages=[], tools=[])
            .tool_calls[0]
            .arguments["factory"]
            == "f"
        )

    def test_exhaustion_is_an_explicit_error(self) -> None:
        provider = ReplayProvider(parse_turns(RECORDING["turns"]), source="demo.json")
        provider.complete(system="", messages=[], tools=[])
        provider.complete(system="", messages=[], tools=[])
        with pytest.raises(ProviderError, match="recording exhausted"):
            provider.complete(system="", messages=[], tools=[])

    def test_from_file(self, tmp_path: Path) -> None:
        path = tmp_path / "demo.json"
        path.write_text(json.dumps(RECORDING), encoding="utf-8")
        provider = ReplayProvider.from_file(path)
        assert provider.remaining == 2

    def test_missing_file_tells_you_how_to_record(self, tmp_path: Path) -> None:
        with pytest.raises(ProviderError, match="--record"):
            ReplayProvider.from_file(tmp_path / "absent.json")


class TestRepositoryRecordings:
    def test_every_recording_parses_and_names_its_case(self, repo_root: Path) -> None:
        found = sorted((repo_root / "evals" / "recordings").rglob("*.json"))
        assert len(found) >= 10
        for path in found:
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert payload["case_id"] == path.stem, path
            assert parse_turns(payload["turns"])

    def test_every_recording_ends_with_prose(self, repo_root: Path) -> None:
        for path in sorted((repo_root / "evals" / "recordings").rglob("*.json")):
            turns = parse_turns(json.loads(path.read_text(encoding="utf-8"))["turns"])
            assert not turns[-1].tool_calls, path
            assert turns[-1].text.strip(), path


class TestMessageConversion:
    def test_user_assistant_and_tool_results(self) -> None:
        messages = [
            UserTurn("what failed"),
            AssistantTurn(
                text="checking", tool_calls=[ToolCall("c1", "list_pipelines", {"factory": "f"})]
            ),
            ToolResultTurn(results=[ToolResult("c1", "ok", is_error=False)]),
        ]
        converted = to_anthropic_messages(messages)
        assert converted[0] == {"role": "user", "content": "what failed"}
        assert converted[1]["role"] == "assistant"
        assert [block["type"] for block in converted[1]["content"]] == ["text", "tool_use"]
        assert converted[2]["content"][0]["type"] == "tool_result"

    def test_a_tool_only_turn_has_no_text_block(self) -> None:
        converted = to_anthropic_messages([AssistantTurn(tool_calls=[ToolCall("c1", "a", {})])])
        assert [block["type"] for block in converted[0]["content"]] == ["tool_use"]

    def test_error_flag_survives(self) -> None:
        converted = to_anthropic_messages(
            [ToolResultTurn(results=[ToolResult("c1", "boom", is_error=True)])]
        )
        assert converted[0]["content"][0]["is_error"] is True


class _Block:
    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


class _Response:
    def __init__(self, content: list[object], stop_reason: str = "end_turn") -> None:
        self.content = content
        self.stop_reason = stop_reason


class TestAnthropicProvider:
    def test_turn_from_anthropic_splits_text_and_tool_use(self) -> None:
        response = _Response(
            [
                _Block(type="text", text="let me check"),
                _Block(type="tool_use", id="c1", name="list_pipelines", input={"factory": "f"}),
            ],
            stop_reason="tool_use",
        )
        turn = turn_from_anthropic(response)
        assert turn.text == "let me check"
        assert turn.tool_calls[0].arguments == {"factory": "f"}
        assert turn.stop_reason == "tool_use"

    def test_unknown_block_types_are_ignored(self) -> None:
        assert turn_from_anthropic(_Response([_Block(type="thinking", thinking="hmm")])).text == ""

    def test_missing_api_key_points_at_replay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ProviderError, match="--provider replay"):
            AnthropicProvider()

    def test_builds_the_request_from_the_neutral_form(self) -> None:
        captured: dict[str, object] = {}

        class _Messages:
            def create(self, **kwargs: object):
                captured.update(kwargs)
                return _Response([_Block(type="text", text="ok")])

        class _Client:
            messages = _Messages()

        from groundwork.core.agent.providers import ToolSpec

        provider = AnthropicProvider(client=_Client())
        turn = provider.complete(
            system="be careful",
            messages=[UserTurn("hello")],
            tools=[ToolSpec("a", "does a", {"type": "object", "properties": {}})],
        )
        assert turn.text == "ok"
        assert captured["system"] == "be careful"
        assert captured["tools"][0]["name"] == "a"


class TestRecorder:
    def test_round_trips_through_replay(self, tmp_path: Path) -> None:
        recorder = Recorder("demo")
        recorder.record(
            AssistantTurn(tool_calls=[ToolCall("c1", "a", {"x": 1})], stop_reason="tool_use")
        )
        recorder.record(AssistantTurn(text="finished"))
        path = recorder.write(tmp_path / "nested" / "demo.json")

        provider = ReplayProvider.from_file(path)
        assert provider.complete(system="", messages=[], tools=[]).tool_calls[0].name == "a"
        assert provider.complete(system="", messages=[], tools=[]).text == "finished"

    def test_records_the_case_id_and_model(self) -> None:
        payload = Recorder("demo", model="m").to_dict()
        assert payload["case_id"] == "demo"
        assert payload["model"] == "m"
