"""The suite runner.

Runs cases against live MCP servers, scores the transcripts, and reports. Cases run
concurrently because a suite you will not wait for is a suite you stop running.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..agent.loop import Transcript, run_agent
from ..agent.mcp_client import Toolkit
from ..agent.providers import (
    AnthropicProvider,
    ModelProvider,
    ProviderError,
    Recorder,
    ReplayProvider,
)
from ..skills import Skill, find_skill
from .case import EvalCase, EvalSuite
from .scorers import ScoreResult, ScoringContext, run_scorer

DEFAULT_CONCURRENCY = 4


@dataclass
class CaseResult:
    """One case, its transcript, and every scorer verdict."""

    case_id: str
    passed: bool
    transcript: Transcript
    scores: list[ScoreResult] = field(default_factory=list)
    error: str | None = None
    attempts: int = 1

    @property
    def duration_ms(self) -> float:
        return self.transcript.duration_ms

    @property
    def tool_call_count(self) -> int:
        return len(self.transcript.tool_calls)

    @property
    def failures(self) -> list[ScoreResult]:
        return [score for score in self.scores if not score.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "error": self.error,
            "attempts": self.attempts,
            "scores": [score.to_dict() for score in self.scores],
            "transcript": self.transcript.to_dict(),
        }


@dataclass
class SuiteResult:
    """Everything one suite run produced."""

    suite: str
    provider: str
    results: list[CaseResult] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def pass_count(self) -> int:
        return sum(1 for result in self.results if result.passed)

    @property
    def fail_count(self) -> int:
        return len(self.results) - self.pass_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "provider": self.provider,
            "passed": self.passed,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "duration_ms": round(self.duration_ms, 1),
            "cases": [result.to_dict() for result in self.results],
        }


@dataclass
class RunnerOptions:
    """How to run a suite."""

    provider: str = "replay"
    model: str | None = None
    only: list[str] = field(default_factory=list)
    concurrency: int = DEFAULT_CONCURRENCY
    retries: int = 0
    record: bool = False
    judge: bool = False
    skills_dir: Path = Path("skills")
    recordings_dir: Path | None = None


def _recordings_root(suite: EvalSuite, options: RunnerOptions) -> Path:
    if options.recordings_dir is not None:
        return options.recordings_dir
    base = suite.path.parent if suite.path else Path("evals")
    return base / "recordings" / suite.name


def _recording_path(suite: EvalSuite, case: EvalCase, options: RunnerOptions) -> Path:
    name = case.recording or f"{case.id}.json"
    return _recordings_root(suite, options) / name


def _build_provider(
    suite: EvalSuite, case: EvalCase, options: RunnerOptions
) -> tuple[ModelProvider, Recorder | None]:
    if options.provider == "replay":
        return ReplayProvider.from_file(_recording_path(suite, case, options)), None
    if options.provider == "anthropic":
        kwargs: dict[str, Any] = {}
        if options.model:
            kwargs["model"] = options.model
        provider = AnthropicProvider(**kwargs)
        recorder = Recorder(case.id, model=provider.model) if options.record else None
        return provider, recorder
    raise ProviderError(f"unknown provider '{options.provider}'. Use 'replay' or 'anthropic'.")


def _judge_provider(options: RunnerOptions) -> ModelProvider | None:
    """Build a provider for the judge scorer, or None when we cannot."""
    if not options.judge:
        return None
    try:
        return AnthropicProvider(**({"model": options.model} if options.model else {}))
    except ProviderError:
        return None


def _resolve_skill(suite: EvalSuite, case: EvalCase, options: RunnerOptions) -> Skill | None:
    name = case.skill or suite.skill
    if not name:
        return None
    return find_skill(options.skills_dir, name)


def _system_prompt(suite: EvalSuite, skill: Skill | None) -> str:
    parts = [suite.system_preamble.strip()] if suite.system_preamble.strip() else []
    if skill is not None:
        parts.append(skill.as_system_prompt())
    return "\n\n".join(parts)


async def _run_case(
    suite: EvalSuite,
    case: EvalCase,
    toolkit: Toolkit,
    options: RunnerOptions,
    judge: ModelProvider | None,
) -> CaseResult:
    """Run and score one case, retrying only on infrastructure errors."""
    attempts = 0
    last: CaseResult | None = None
    for attempt in range(options.retries + 1):
        attempts = attempt + 1
        try:
            skill = _resolve_skill(suite, case, options)
            provider, recorder = _build_provider(suite, case, options)
        except Exception as exc:
            transcript = Transcript(prompt=case.prompt, error=f"{type(exc).__name__}: {exc}")
            last = CaseResult(case.id, False, transcript, error=str(exc), attempts=attempts)
            continue

        transcript = await run_agent(
            provider=provider,
            toolkit=toolkit,
            prompt=case.prompt,
            system=_system_prompt(suite, skill),
            max_iterations=case.max_iterations,
            sink=recorder,
        )
        if recorder is not None:
            recorder.write(_recording_path(suite, case, options))

        if transcript.error and attempt < options.retries:
            last = CaseResult(case.id, False, transcript, error=transcript.error, attempts=attempts)
            continue

        context = ScoringContext(provider=judge, judge_enabled=judge is not None)
        scores: list[ScoreResult] = []
        for spec in case.scorers:
            try:
                scores.append(run_scorer(spec.type, transcript, spec.params, context))
            except Exception as exc:
                scores.append(
                    ScoreResult(
                        spec.type, False, f"scorer raised: {type(exc).__name__}: {exc}", 0.0
                    )
                )
        passed = bool(scores) and all(score.passed for score in scores) and not transcript.error
        if not case.scorers:
            passed = not transcript.error
        return CaseResult(
            case.id,
            passed,
            transcript,
            scores=scores,
            error=transcript.error,
            attempts=attempts,
        )

    assert last is not None
    return last


async def run_suite(suite: EvalSuite, options: RunnerOptions | None = None) -> SuiteResult:
    """Run every selected case in a suite and return the results."""
    options = options or RunnerOptions()
    cases = suite.select(options.only)
    judge = _judge_provider(options)
    started = time.perf_counter()

    async with Toolkit.connect(suite.server_configs()) as toolkit:
        semaphore = asyncio.Semaphore(max(1, options.concurrency))

        async def guarded(case: EvalCase) -> CaseResult:
            async with semaphore:
                return await _run_case(suite, case, toolkit, options, judge)

        results = await asyncio.gather(*(guarded(case) for case in cases))

    order = {case.id: index for index, case in enumerate(cases)}
    ordered = sorted(results, key=lambda result: order[result.case_id])
    return SuiteResult(
        suite=suite.name,
        provider=options.provider,
        results=list(ordered),
        duration_ms=(time.perf_counter() - started) * 1000,
    )
