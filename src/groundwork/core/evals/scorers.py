"""Scorers.

A scorer takes a transcript and returns a pass or fail plus a short human readable
reason. The reason matters as much as the verdict: when a suite goes red at 6pm on a
customer site, "failed" is useless and "expected find_upstream_dependencies, agent
called get_activity_error twice then stopped" tells you what to do next.

Three groups:

- Output scorers (contains, not_contains, regex, cites_source) look at the final answer.
- Behaviour scorers (tool_called, tool_sequence, no_tool_errors) look at what the agent
  actually did. These are the ones that catch an agent producing plausible prose without
  having checked anything.
- Budget scorers (max_turns, max_tool_calls) look at cost.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from ..agent.loop import Transcript
from ..agent.providers import ModelProvider, ProviderError, ToolSpec, UserTurn


class ScorerError(ValueError):
    """Raised when a scorer is misconfigured in the suite YAML."""


@dataclass(frozen=True)
class ScoreResult:
    """The outcome of one scorer against one transcript."""

    scorer: str
    passed: bool
    reason: str
    score: float = 1.0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scorer": self.scorer,
            "passed": self.passed,
            "score": self.score,
            "reason": self.reason,
            "details": self.details,
        }


@dataclass
class ScoringContext:
    """Everything a scorer may need beyond the transcript itself."""

    provider: ModelProvider | None = None
    judge_enabled: bool = False


Scorer = Callable[[Transcript, dict[str, Any], ScoringContext], ScoreResult]

_REGISTRY: dict[str, Scorer] = {}


def register(name: str) -> Callable[[Scorer], Scorer]:
    """Register a scorer under a name usable in suite YAML."""

    def decorator(func: Scorer) -> Scorer:
        _REGISTRY[name] = func
        return func

    return decorator


def available_scorers() -> list[str]:
    """Every registered scorer name, sorted."""
    return sorted(_REGISTRY)


def get_scorer(name: str) -> Scorer:
    """Look up a scorer, with a useful error when the name is wrong."""
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise ScorerError(
            f"unknown scorer '{name}'. Available: {', '.join(available_scorers())}."
        ) from exc


def run_scorer(
    name: str,
    transcript: Transcript,
    params: dict[str, Any],
    context: ScoringContext | None = None,
) -> ScoreResult:
    """Run one scorer by name."""
    return get_scorer(name)(transcript, params, context or ScoringContext())


def _as_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        raise ScorerError(f"missing required parameter '{field_name}'")
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(item) for item in value]
    raise ScorerError(f"'{field_name}' must be a string or a list of strings")


def _haystack(transcript: Transcript, params: dict[str, Any]) -> str:
    text = transcript.final_text
    if not params.get("case_sensitive", False):
        return text.lower()
    return text


def _needles(values: list[str], params: dict[str, Any]) -> list[str]:
    if not params.get("case_sensitive", False):
        return [value.lower() for value in values]
    return values


@register("contains")
def contains(
    transcript: Transcript, params: dict[str, Any], context: ScoringContext
) -> ScoreResult:
    """Pass when the final answer contains the value, or any/all of a list of values."""
    values = _as_list(params.get("value", params.get("values")), field_name="value")
    mode = params.get("mode", "any")
    if mode not in {"any", "all"}:
        raise ScorerError("contains 'mode' must be 'any' or 'all'")
    text = _haystack(transcript, params)
    needles = _needles(values, params)
    found = [original for original, needle in zip(values, needles, strict=True) if needle in text]
    missing = [original for original in values if original not in found]
    passed = bool(found) if mode == "any" else not missing
    if passed:
        reason = f"found {', '.join(repr(item) for item in found)}"
    elif mode == "any":
        reason = f"none of {', '.join(repr(item) for item in values)} appear in the answer"
    else:
        reason = f"missing {', '.join(repr(item) for item in missing)}"
    return ScoreResult("contains", passed, reason, 1.0 if passed else 0.0, {"found": found})


@register("not_contains")
def not_contains(
    transcript: Transcript, params: dict[str, Any], context: ScoringContext
) -> ScoreResult:
    """Pass when the final answer contains none of the values.

    Useful for the hallucination guards: an answer about the sales cascade should not
    mention the marketing credential failure, because that was a separate incident.
    """
    values = _as_list(params.get("value", params.get("values")), field_name="value")
    text = _haystack(transcript, params)
    needles = _needles(values, params)
    hits = [original for original, needle in zip(values, needles, strict=True) if needle in text]
    passed = not hits
    reason = (
        "none of the forbidden strings appear"
        if passed
        else f"answer contains {', '.join(repr(item) for item in hits)}"
    )
    return ScoreResult("not_contains", passed, reason, 1.0 if passed else 0.0, {"hits": hits})


@register("regex")
def regex(transcript: Transcript, params: dict[str, Any], context: ScoringContext) -> ScoreResult:
    """Pass when the final answer matches a regular expression."""
    pattern = params.get("pattern")
    if not pattern:
        raise ScorerError("regex needs a 'pattern'")
    flags = 0 if params.get("case_sensitive", False) else re.IGNORECASE
    if params.get("dotall", False):
        flags |= re.DOTALL
    try:
        compiled = re.compile(pattern, flags)
    except re.error as exc:
        raise ScorerError(f"bad regex {pattern!r}: {exc}") from exc
    match = compiled.search(transcript.final_text)
    passed = match is not None
    reason = f"matched {match.group(0)!r}" if match else f"no match for /{pattern}/"
    return ScoreResult("regex", passed, reason, 1.0 if passed else 0.0)


def _argument_matches(actual: Any, expected: Any) -> bool:
    """Compare one argument. Strings match case insensitively by substring."""
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.lower() in actual.lower()
    if isinstance(expected, dict) and isinstance(actual, dict):
        return all(_argument_matches(actual.get(key), value) for key, value in expected.items())
    return actual == expected


@register("tool_called")
def tool_called(
    transcript: Transcript, params: dict[str, Any], context: ScoringContext
) -> ScoreResult:
    """Pass when a named tool was called, optionally with matching arguments.

    This is the scorer that separates an agent that works from one that sounds like it
    works. Argument matchers are deliberately forgiving on strings (substring, case
    insensitive) because the agent choosing to pass 'contoso-analytics-adf' rather than
    'Contoso-Analytics-ADF' is not a behaviour difference worth failing over.
    """
    name = params.get("tool") or params.get("name")
    if not name:
        raise ScorerError("tool_called needs a 'tool'")
    expected_args = params.get("args") or params.get("arguments") or {}
    minimum = int(params.get("min_times", 1))

    candidates = [call for call in transcript.tool_calls if call.name == name]
    if not candidates:
        called = ", ".join(sorted({call.name for call in transcript.tool_calls})) or "nothing"
        return ScoreResult(
            "tool_called",
            False,
            f"{name} was never called (agent called: {called})",
            0.0,
        )
    if not expected_args:
        passed = len(candidates) >= minimum
        return ScoreResult(
            "tool_called",
            passed,
            f"{name} called {len(candidates)} time(s)"
            + ("" if passed else f", expected at least {minimum}"),
            1.0 if passed else 0.0,
            {"calls": len(candidates)},
        )

    matching = [
        call
        for call in candidates
        if all(
            _argument_matches(call.arguments.get(key), value)
            for key, value in expected_args.items()
        )
    ]
    passed = len(matching) >= minimum
    if passed:
        reason = f"{name} called with matching arguments {len(matching)} time(s)"
    else:
        seen = json.dumps([call.arguments for call in candidates][:3], default=str)
        reason = f"{name} was called but not with {expected_args}; saw {seen}"
    return ScoreResult(
        "tool_called", passed, reason, 1.0 if passed else 0.0, {"matches": len(matching)}
    )


@register("tool_sequence")
def tool_sequence(
    transcript: Transcript, params: dict[str, Any], context: ScoringContext
) -> ScoreResult:
    """Pass when the named tools were called in order, as a subsequence.

    Subsequence, not contiguous run: we care that the agent looked up the failure before
    it walked the dependency graph, not that it did nothing else in between.
    """
    expected = _as_list(params.get("tools") or params.get("sequence"), field_name="tools")
    actual = transcript.tool_names
    index = 0
    for called in actual:
        if index < len(expected) and called == expected[index]:
            index += 1
    passed = index == len(expected)
    if passed:
        reason = f"saw {' then '.join(expected)}"
    else:
        reason = (
            f"expected {' then '.join(expected)}, got stuck at '{expected[index]}'; "
            f"actual order was {' then '.join(actual) or '(no tool calls)'}"
        )
    return ScoreResult("tool_sequence", passed, reason, index / len(expected) if expected else 1.0)


@register("no_tool_errors")
def no_tool_errors(
    transcript: Transcript, params: dict[str, Any], context: ScoringContext
) -> ScoreResult:
    """Pass when no tool call returned an error.

    Set `allow: N` on cases that deliberately provoke an error to test recovery.
    """
    allowed = int(params.get("allow", 0))
    errors = transcript.tool_errors
    passed = len(errors) <= allowed
    if passed:
        reason = f"{len(errors)} tool error(s), budget {allowed}"
    else:
        failing = ", ".join(f"{call.name}: {call.output[:80]}" for call in errors[:3])
        reason = f"{len(errors)} tool error(s) exceeded budget {allowed}: {failing}"
    return ScoreResult("no_tool_errors", passed, reason, 1.0 if passed else 0.0)


@register("max_turns")
def max_turns(
    transcript: Transcript, params: dict[str, Any], context: ScoringContext
) -> ScoreResult:
    """Pass when the agent finished within a turn budget."""
    limit = params.get("value", params.get("limit"))
    if limit is None:
        raise ScorerError("max_turns needs a 'value'")
    limit = int(limit)
    actual = transcript.turn_count
    passed = actual <= limit
    return ScoreResult(
        "max_turns",
        passed,
        f"{actual} model turn(s), limit {limit}",
        1.0 if passed else 0.0,
        {"turns": actual, "limit": limit},
    )


@register("max_tool_calls")
def max_tool_calls(
    transcript: Transcript, params: dict[str, Any], context: ScoringContext
) -> ScoreResult:
    """Pass when the agent stayed within a tool call budget.

    Cost control, and a proxy for whether the procedure in the skill is actually being
    followed. An agent that needs nineteen calls to answer a four call question has not
    understood the task.
    """
    limit = params.get("value", params.get("limit"))
    if limit is None:
        raise ScorerError("max_tool_calls needs a 'value'")
    limit = int(limit)
    actual = len(transcript.tool_calls)
    passed = actual <= limit
    return ScoreResult(
        "max_tool_calls",
        passed,
        f"{actual} tool call(s), limit {limit}",
        1.0 if passed else 0.0,
        {"tool_calls": actual, "limit": limit},
    )


_CITATION_RE = re.compile(r"\b([A-Z]{2,}-[A-Z0-9]+-\d+)(?:#([A-Za-z0-9]+))?\b")


@register("cites_source")
def cites_source(
    transcript: Transcript, params: dict[str, Any], context: ScoringContext
) -> ScoreResult:
    """Pass when the answer cites an id that a tool actually returned.

    This is a cheap, deterministic grounding check, and it catches the specific failure
    this domain has: a fluent answer citing DOC-TAX-03, which does not exist. We only
    accept a citation if the exact string appears somewhere in the tool output the agent
    received, so a plausible looking invented id fails.
    """
    answer = transcript.final_text
    pattern = params.get("pattern")
    citation_re = re.compile(pattern) if pattern else _CITATION_RE
    found = [match.group(0) for match in citation_re.finditer(answer)]
    minimum = int(params.get("min_citations", 1))

    if not found:
        return ScoreResult("cites_source", False, "the answer cites no source id", 0.0)

    tool_text = transcript.tool_outputs()
    grounded = [citation for citation in found if citation in tool_text]
    ungrounded = [citation for citation in found if citation not in tool_text]

    passed = len(grounded) >= minimum and not ungrounded
    if passed:
        reason = f"cited {', '.join(sorted(set(grounded)))}, all present in tool output"
    elif ungrounded:
        reason = f"cited {', '.join(sorted(set(ungrounded)))} which no tool returned"
    else:
        reason = f"only {len(grounded)} grounded citation(s), needed {minimum}"
    return ScoreResult(
        "cites_source",
        passed,
        reason,
        1.0 if passed else 0.0,
        {"grounded": grounded, "ungrounded": ungrounded},
    )


_JUDGE_SYSTEM = """You are grading one answer produced by an AI agent against a rubric.

Reply with JSON only, no prose around it, in exactly this shape:
{"score": <number between 0 and 1>, "pass": <true or false>, "reasoning": "<two sentences>"}

Be strict. An answer that is fluent but does not satisfy the rubric fails."""


@register("judge")
def judge(transcript: Transcript, params: dict[str, Any], context: ScoringContext) -> ScoreResult:
    """Grade the answer against a written rubric using a model.

    Degrades gracefully: with no provider configured this returns a skip rather than a
    failure, so the offline suite stays green and CI needs no secrets. That is a real
    tradeoff and it is stated in the report rather than hidden: a green run under replay
    has not exercised the judge.
    """
    rubric = params.get("rubric")
    if not rubric:
        raise ScorerError("judge needs a 'rubric'")
    threshold = float(params.get("threshold", 0.7))

    if context.provider is None or not context.judge_enabled:
        return ScoreResult(
            "judge",
            True,
            "skipped: no judge provider configured (set ANTHROPIC_API_KEY and pass --judge)",
            score=1.0,
            details={"skipped": True, "rubric": rubric},
        )

    prompt = (
        f"Rubric:\n{rubric}\n\n"
        f"Question the agent was asked:\n{transcript.prompt}\n\n"
        f"Agent's final answer:\n{transcript.final_text}\n\n"
        f"Tools the agent called: {', '.join(transcript.tool_names) or 'none'}"
    )
    try:
        turn = context.provider.complete(
            messages=[UserTurn(text=prompt)],
            system=_JUDGE_SYSTEM,
            tools=[],
        )
    except ProviderError as exc:
        return ScoreResult("judge", False, f"judge provider failed: {exc}", 0.0)

    raw = turn.text.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return ScoreResult("judge", False, f"judge did not return JSON: {raw[:120]}", 0.0)
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return ScoreResult("judge", False, f"judge returned invalid JSON: {exc}", 0.0)

    score = float(payload.get("score", 0.0))
    reasoning = str(payload.get("reasoning", "")).strip()
    passed = bool(payload.get("pass", score >= threshold)) and score >= threshold
    return ScoreResult(
        "judge",
        passed,
        f"score {score:.2f} (threshold {threshold:.2f}): {reasoning}",
        score,
        {"rubric": rubric, "raw": payload},
    )


__all__ = [
    "ScoreResult",
    "ScorerError",
    "ScoringContext",
    "ToolSpec",
    "available_scorers",
    "get_scorer",
    "register",
    "run_scorer",
]
