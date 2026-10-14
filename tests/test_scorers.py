"""Tests for every scorer."""

from __future__ import annotations

import pytest
from conftest import invocation, transcript

from groundwork.core.agent.providers import AssistantTurn
from groundwork.core.evals.scorers import (
    ScorerError,
    ScoringContext,
    available_scorers,
    get_scorer,
    run_scorer,
)


def test_registry_holds_every_documented_scorer() -> None:
    assert set(available_scorers()) == {
        "cites_source",
        "contains",
        "judge",
        "max_tool_calls",
        "max_turns",
        "no_tool_errors",
        "not_contains",
        "regex",
        "tool_called",
        "tool_sequence",
    }


def test_unknown_scorer_names_the_alternatives() -> None:
    with pytest.raises(ScorerError, match="Available: cites_source"):
        get_scorer("vibes")


class TestContains:
    def test_any_mode_passes_on_one_hit(self) -> None:
        result = run_scorer(
            "contains",
            transcript("the ROOT cause was throttling"),
            {"values": ["root cause", "missing"]},
        )
        assert result.passed
        assert "root cause" in result.reason

    def test_all_mode_fails_on_a_miss(self) -> None:
        result = run_scorer(
            "contains",
            transcript("only one of them"),
            {"values": ["one", "two"], "mode": "all"},
        )
        assert not result.passed
        assert "'two'" in result.reason

    def test_case_sensitive_opt_in(self) -> None:
        assert not run_scorer(
            "contains", transcript("ROOT"), {"value": "root", "case_sensitive": True}
        ).passed

    def test_bad_mode_raises(self) -> None:
        with pytest.raises(ScorerError, match="must be 'any' or 'all'"):
            run_scorer("contains", transcript("x"), {"value": "x", "mode": "some"})

    def test_missing_value_raises(self) -> None:
        with pytest.raises(ScorerError, match="missing required parameter"):
            run_scorer("contains", transcript("x"), {})


class TestNotContains:
    def test_passes_when_absent(self) -> None:
        assert run_scorer("not_contains", transcript("sales"), {"values": ["marketing"]}).passed

    def test_fails_and_names_the_hit(self) -> None:
        result = run_scorer(
            "not_contains", transcript("marketing creds"), {"values": ["marketing"]}
        )
        assert not result.passed
        assert "'marketing'" in result.reason


class TestRegex:
    def test_match(self) -> None:
        assert run_scorer("regex", transcript("run 0001 failed"), {"pattern": r"run \d{4}"}).passed

    def test_no_match_reports_the_pattern(self) -> None:
        result = run_scorer("regex", transcript("nothing"), {"pattern": r"run \d+"})
        assert not result.passed
        assert "no match" in result.reason

    def test_bad_pattern_raises(self) -> None:
        with pytest.raises(ScorerError, match="bad regex"):
            run_scorer("regex", transcript("x"), {"pattern": "("})

    def test_missing_pattern_raises(self) -> None:
        with pytest.raises(ScorerError, match="needs a 'pattern'"):
            run_scorer("regex", transcript("x"), {})


class TestToolCalled:
    def test_names_what_was_called_instead(self) -> None:
        result = run_scorer(
            "tool_called",
            transcript("x", [invocation("get_pipeline")]),
            {"tool": "find_upstream_dependencies"},
        )
        assert not result.passed
        assert "get_pipeline" in result.reason

    def test_argument_matching_is_substring_and_case_insensitive(self) -> None:
        calls = [invocation("get_pipeline", {"name": "Ingest_Sales_Raw"})]
        assert run_scorer(
            "tool_called",
            transcript("x", calls),
            {"tool": "get_pipeline", "args": {"name": "sales"}},
        ).passed

    def test_nested_argument_matching(self) -> None:
        calls = [invocation("check", {"profile": {"employees": 4, "sector": "food"}})]
        assert run_scorer(
            "tool_called",
            transcript("x", calls),
            {"tool": "check", "args": {"profile": {"sector": "food"}}},
        ).passed

    def test_argument_mismatch_shows_what_was_seen(self) -> None:
        calls = [invocation("get_pipeline", {"name": "publish"})]
        result = run_scorer(
            "tool_called",
            transcript("x", calls),
            {"tool": "get_pipeline", "args": {"name": "ingest"}},
        )
        assert not result.passed
        assert "publish" in result.reason

    def test_min_times(self) -> None:
        calls = [invocation("a"), invocation("a")]
        assert run_scorer(
            "tool_called", transcript("x", calls), {"tool": "a", "min_times": 2}
        ).passed
        assert not run_scorer(
            "tool_called", transcript("x", calls), {"tool": "a", "min_times": 3}
        ).passed

    def test_missing_tool_name_raises(self) -> None:
        with pytest.raises(ScorerError, match="needs a 'tool'"):
            run_scorer("tool_called", transcript("x"), {})


class TestToolSequence:
    def test_subsequence_allows_gaps(self) -> None:
        calls = [invocation("a"), invocation("z"), invocation("b")]
        assert run_scorer("tool_sequence", transcript("x", calls), {"tools": ["a", "b"]}).passed

    def test_wrong_order_fails_and_says_where(self) -> None:
        calls = [invocation("b"), invocation("a")]
        result = run_scorer("tool_sequence", transcript("x", calls), {"tools": ["a", "b"]})
        assert not result.passed
        assert "stuck at 'b'" in result.reason

    def test_partial_credit_in_score(self) -> None:
        calls = [invocation("a")]
        result = run_scorer("tool_sequence", transcript("x", calls), {"tools": ["a", "b"]})
        assert result.score == pytest.approx(0.5)


class TestToolErrorsAndBudgets:
    def test_no_tool_errors_passes_when_clean(self) -> None:
        assert run_scorer("no_tool_errors", transcript("x", [invocation("a")]), {}).passed

    def test_no_tool_errors_fails_and_quotes_the_error(self) -> None:
        calls = [invocation("a", output="boom: not found", is_error=True)]
        result = run_scorer("no_tool_errors", transcript("x", calls), {})
        assert not result.passed
        assert "boom" in result.reason

    def test_allowance_covers_a_deliberate_error(self) -> None:
        calls = [invocation("a", output="boom", is_error=True)]
        assert run_scorer("no_tool_errors", transcript("x", calls), {"allow": 1}).passed

    def test_max_turns(self) -> None:
        assert run_scorer("max_turns", transcript("x", turns=3), {"value": 3}).passed
        assert not run_scorer("max_turns", transcript("x", turns=4), {"value": 3}).passed

    def test_max_turns_needs_a_value(self) -> None:
        with pytest.raises(ScorerError, match="needs a 'value'"):
            run_scorer("max_turns", transcript("x"), {})

    def test_max_tool_calls(self) -> None:
        calls = [invocation("a"), invocation("b")]
        assert run_scorer("max_tool_calls", transcript("x", calls), {"value": 2}).passed
        assert not run_scorer("max_tool_calls", transcript("x", calls), {"limit": 1}).passed


class TestCitesSource:
    def test_grounded_citation_passes(self) -> None:
        calls = [invocation("get_section", output="DOC-DPA-01#S1 registration ...")]
        result = run_scorer("cites_source", transcript("see DOC-DPA-01#S1", calls), {})
        assert result.passed

    def test_invented_citation_fails(self) -> None:
        calls = [invocation("get_section", output="DOC-TAX-01#S1 ...")]
        result = run_scorer("cites_source", transcript("see DOC-TAX-03#S9", calls), {})
        assert not result.passed
        assert "DOC-TAX-03#S9" in result.reason

    def test_no_citation_at_all_fails(self) -> None:
        result = run_scorer(
            "cites_source", transcript("trust me", [invocation("a", output="DOC-TAX-01")]), {}
        )
        assert not result.passed
        assert "cites no source" in result.reason

    def test_min_citations(self) -> None:
        calls = [invocation("a", output="DOC-TAX-01#S1 DOC-TAX-01#S2")]
        answer = "see DOC-TAX-01#S1 and DOC-TAX-01#S2"
        assert run_scorer("cites_source", transcript(answer, calls), {"min_citations": 2}).passed
        assert not run_scorer(
            "cites_source", transcript("see DOC-TAX-01#S1", calls), {"min_citations": 2}
        ).passed

    def test_custom_pattern(self) -> None:
        calls = [invocation("a", output="run 0001")]
        result = run_scorer(
            "cites_source", transcript("run 0001", calls), {"pattern": r"run \d{4}"}
        )
        assert result.passed


class _StubProvider:
    """Returns a canned judge verdict without touching the network."""

    name = "stub"

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def complete(self, *, system, messages, tools):
        del system, messages, tools
        self.calls += 1
        return AssistantTurn(text=self.text)


class TestJudge:
    def test_skips_without_a_provider(self) -> None:
        result = run_scorer("judge", transcript("x"), {"rubric": "is it good"})
        assert result.passed
        assert result.details["skipped"] is True

    def test_needs_a_rubric(self) -> None:
        with pytest.raises(ScorerError, match="needs a 'rubric'"):
            run_scorer("judge", transcript("x"), {})

    def test_parses_a_verdict(self) -> None:
        provider = _StubProvider(
            '{"score": 0.9, "pass": true, "reasoning": "grounded and specific"}'
        )
        result = run_scorer(
            "judge",
            transcript("x"),
            {"rubric": "is it good"},
            ScoringContext(provider=provider, judge_enabled=True),
        )
        assert result.passed
        assert result.score == pytest.approx(0.9)
        assert "grounded" in result.reason
        assert provider.calls == 1

    def test_threshold_applies_when_pass_is_absent(self) -> None:
        provider = _StubProvider('{"score": 0.4, "reasoning": "thin"}')
        result = run_scorer(
            "judge",
            transcript("x"),
            {"rubric": "is it good", "threshold": 0.7},
            ScoringContext(provider=provider, judge_enabled=True),
        )
        assert not result.passed

    def test_unparseable_verdict_fails_rather_than_crashing(self) -> None:
        provider = _StubProvider("I think it was pretty good actually")
        result = run_scorer(
            "judge",
            transcript("x"),
            {"rubric": "is it good"},
            ScoringContext(provider=provider, judge_enabled=True),
        )
        assert not result.passed
