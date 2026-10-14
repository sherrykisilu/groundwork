"""Query layer over the synthetic ADF fixture.

This module holds the logic that is worth testing: dependency graph traversal and
failure aggregation. The MCP server in `server.py` is a thin wrapper over it, which
keeps the interesting code reachable from plain unit tests.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from .fixtures import (
    FACTORY,
    NOW,
    PIPELINES,
    PIPELINES_BY_NAME,
    RUNS,
    RUNS_BY_ID,
    PipelineRun,
)


class AdfError(ValueError):
    """Raised when a caller asks for something that does not exist."""


def check_factory(factory: str) -> None:
    """Validate the factory name, mirroring a 404 from the real API."""
    if factory != FACTORY:
        raise AdfError(f"factory '{factory}' not found. The only factory here is '{FACTORY}'.")


def _producers() -> dict[str, list[str]]:
    """Map each dataset to the pipelines that write it."""
    mapping: dict[str, list[str]] = {}
    for pipeline in PIPELINES:
        for dataset in pipeline.outputs:
            mapping.setdefault(dataset, []).append(pipeline.name)
    return mapping


def _invokers() -> dict[str, list[str]]:
    """Map each pipeline to the pipelines that launch it with ExecutePipeline."""
    mapping: dict[str, list[str]] = {}
    for pipeline in PIPELINES:
        for activity in pipeline.activities:
            if activity.invokes:
                mapping.setdefault(activity.invokes, []).append(pipeline.name)
    return mapping


def direct_upstream(pipeline: str) -> list[dict[str, str]]:
    """Pipelines one hop upstream of `pipeline`, with the reason for each edge."""
    if pipeline not in PIPELINES_BY_NAME:
        raise AdfError(f"pipeline '{pipeline}' not found in factory '{FACTORY}'.")
    producers = _producers()
    edges: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for dataset in PIPELINES_BY_NAME[pipeline].inputs:
        for producer in producers.get(dataset, []):
            if producer == pipeline:
                continue
            key = (producer, dataset)
            if key in seen:
                continue
            seen.add(key)
            edges.append({"pipeline": producer, "edge": "dataset", "via": dataset})
    for invoker in _invokers().get(pipeline, []):
        if (invoker, "execute_pipeline") in seen:
            continue
        seen.add((invoker, "execute_pipeline"))
        edges.append({"pipeline": invoker, "edge": "execute_pipeline", "via": pipeline})
    return sorted(edges, key=lambda edge: (edge["pipeline"], edge["via"]))


def find_upstream(pipeline: str, *, max_depth: int = 8) -> dict[str, Any]:
    """Walk the dependency graph upstream from `pipeline`, breadth first.

    Two kinds of edge are followed: dataset lineage (another pipeline writes a dataset
    this one reads) and control flow (another pipeline launches this one with an
    ExecutePipeline activity). Both matter during triage, because the thing that
    actually broke is frequently two hops away from the thing that paged you.
    """
    if pipeline not in PIPELINES_BY_NAME:
        raise AdfError(f"pipeline '{pipeline}' not found in factory '{FACTORY}'.")
    levels: list[dict[str, Any]] = []
    visited: set[str] = {pipeline}
    frontier = [pipeline]
    for depth in range(1, max_depth + 1):
        next_frontier: list[str] = []
        edges: list[dict[str, str]] = []
        for node in frontier:
            for edge in direct_upstream(node):
                edges.append(
                    {"from": edge["pipeline"], "to": node, "edge": edge["edge"], "via": edge["via"]}
                )
                if edge["pipeline"] not in visited:
                    visited.add(edge["pipeline"])
                    next_frontier.append(edge["pipeline"])
        if not edges:
            break
        levels.append({"depth": depth, "edges": sorted(edges, key=lambda e: (e["from"], e["to"]))})
        if not next_frontier:
            break
        frontier = next_frontier
    roots = [name for name in sorted(visited - {pipeline}) if not direct_upstream(name)]
    return {
        "factory": FACTORY,
        "pipeline": pipeline,
        "upstream_pipelines": sorted(visited - {pipeline}),
        "levels": levels,
        "root_pipelines": roots,
        "note": (
            "root_pipelines have no upstream of their own. During an incident they are "
            "the first place to look for a real cause."
        ),
    }


def _parse_since(since: str | None, *, default_days: int = 7) -> datetime:
    """Parse an ISO 8601 date or datetime, or a relative string such as '2d'."""
    if not since:
        return NOW - timedelta(days=default_days)
    text = since.strip()
    if text.endswith("d") and text[:-1].isdigit():
        return NOW - timedelta(days=int(text[:-1]))
    if text.endswith("h") and text[:-1].isdigit():
        return NOW - timedelta(hours=int(text[:-1]))
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise AdfError(
            f"could not parse since='{since}'. Use an ISO 8601 timestamp such as "
            "'2026-03-11' or a relative window such as '2d'."
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def filter_runs(
    *,
    pipeline: str | None = None,
    status: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[PipelineRun]:
    """Filter the run history. Returns newest first."""
    if pipeline and pipeline not in PIPELINES_BY_NAME:
        raise AdfError(f"pipeline '{pipeline}' not found in factory '{FACTORY}'.")
    cutoff = _parse_since(since)
    selected: list[PipelineRun] = []
    for run in RUNS:
        if run.start < cutoff:
            continue
        if pipeline and run.pipeline != pipeline:
            continue
        if status and run.status.lower() != status.lower():
            continue
        selected.append(run)
    return selected[:limit]


def get_run(run_id: str) -> PipelineRun:
    """Look up one pipeline run."""
    run = RUNS_BY_ID.get(run_id)
    if run is None:
        raise AdfError(f"run '{run_id}' not found. Use list_pipeline_runs to get valid run ids.")
    return run


def summarize_failures(since: str | None = None) -> dict[str, Any]:
    """Group failures in the window by the error code of the failing activity."""
    cutoff = _parse_since(since)
    failures = [run for run in RUNS if run.start >= cutoff and run.status in {"Failed", "TimedOut"}]
    by_code: dict[str, dict[str, Any]] = {}
    for run in failures:
        for activity in run.activities:
            if activity.status not in {"Failed", "TimedOut"} or not activity.error:
                continue
            code = _short_code(activity.error.get("message", "")) or str(
                activity.error.get("errorCode", "unknown")
            )
            bucket = by_code.setdefault(
                code,
                {
                    "error_code": code,
                    "run_count": 0,
                    "pipelines": set(),
                    "example_run_id": run.run_id,
                },
            )
            bucket["run_count"] += 1
            bucket["pipelines"].add(run.pipeline)
    grouped = [
        {
            "error_code": bucket["error_code"],
            "run_count": bucket["run_count"],
            "pipelines": sorted(bucket["pipelines"]),
            "example_run_id": bucket["example_run_id"],
        }
        for bucket in by_code.values()
    ]
    grouped.sort(key=lambda item: (-item["run_count"], item["error_code"]))
    return {
        "factory": FACTORY,
        "since": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "failed_run_count": len(failures),
        "failed_pipelines": sorted({run.pipeline for run in failures}),
        "by_error_code": grouped,
        "note": (
            "Grouping by error code does not group by cause. Several of these codes can "
            "share one upstream cause. Use find_upstream_dependencies to check."
        ),
    }


def _short_code(message: str) -> str:
    """Pull the `ErrorCode=X` token out of a message, which is what operators quote."""
    marker = "ErrorCode="
    if marker not in message:
        return ""
    tail = message.split(marker, 1)[1]
    return tail.split(",", 1)[0].strip().strip("'\"")


def failed_activities(run: PipelineRun) -> Iterable[Any]:
    """Activity runs in `run` that did not succeed."""
    return (activity for activity in run.activities if activity.status in {"Failed", "TimedOut"})
