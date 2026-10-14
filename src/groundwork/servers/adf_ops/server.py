"""The `adf_ops` MCP server.

Tool names and shapes follow the public Azure Data Factory REST API. The data behind
them is synthetic and lives in `fixtures.py`. Nothing here is derived from a real
factory, a real incident, or any internal tooling.

Tool descriptions matter more than they look. They are the only documentation the
model gets, and on a real engagement they are where you encode the operational
knowledge that would otherwise live in someone's head: which tool to reach for, what
the arguments mean, and what the result does not tell you.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import query
from .fixtures import PIPELINES, PIPELINES_BY_NAME

mcp = MCPServer(
    name="adf_ops",
    version="0.1.0",
    instructions=(
        "Read only operations tooling for a data platform built on Azure Data Factory. "
        "All data served here is synthetic and shaped like the public ADF REST API. "
        "Start from list_pipeline_runs or summarize_failures, then use "
        "find_upstream_dependencies before you conclude anything about cause."
    ),
    log_level="CRITICAL",
)


def _fail(exc: query.AdfError) -> ToolError:
    return ToolError(str(exc))


@mcp.tool()
def list_pipelines(factory: str) -> dict[str, Any]:
    """List every pipeline in the factory with its folder, description and dataset lineage.

    Use this first when you do not know the pipeline names. The `inputs` and `outputs`
    are dataset names, and they are what the dependency graph is built from.

    Args:
        factory: Factory name. Use 'contoso-analytics-adf'.
    """
    try:
        query.check_factory(factory)
    except query.AdfError as exc:
        raise _fail(exc) from exc
    return {
        "factory": factory,
        "count": len(PIPELINES),
        "pipelines": [
            {
                "name": pipeline.name,
                "folder": pipeline.folder,
                "description": pipeline.description,
                "activity_count": len(pipeline.activities),
                "inputs": list(pipeline.inputs),
                "outputs": list(pipeline.outputs),
            }
            for pipeline in PIPELINES
        ],
    }


@mcp.tool()
def get_pipeline(factory: str, name: str) -> dict[str, Any]:
    """Get one pipeline definition: its activities, their types, and their dependsOn edges.

    `dependsOn` is the within pipeline ordering. An activity of type ExecutePipeline
    launches another pipeline, which is how work crosses a pipeline boundary.

    Args:
        factory: Factory name.
        name: Pipeline name, for example 'transform_sales_clean'.
    """
    try:
        query.check_factory(factory)
    except query.AdfError as exc:
        raise _fail(exc) from exc
    pipeline = PIPELINES_BY_NAME.get(name)
    if pipeline is None:
        available = ", ".join(sorted(PIPELINES_BY_NAME))
        raise ToolError(f"pipeline '{name}' not found. Available pipelines: {available}.")
    return pipeline.to_api()


@mcp.tool()
def list_pipeline_runs(
    factory: str,
    pipeline: str | None = None,
    status: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List pipeline runs, newest first.

    Args:
        factory: Factory name.
        pipeline: Optional pipeline name to filter by.
        status: Optional status filter: Succeeded, Failed, InProgress or TimedOut.
        since: Window start. ISO 8601 such as '2026-03-11', or relative such as '2d'.
            Defaults to the last 7 days.
        limit: Maximum number of runs to return.
    """
    try:
        query.check_factory(factory)
        runs = query.filter_runs(pipeline=pipeline, status=status, since=since, limit=limit)
    except query.AdfError as exc:
        raise _fail(exc) from exc
    return {
        "factory": factory,
        "count": len(runs),
        "runs": [run.to_api() for run in runs],
    }


@mcp.tool()
def get_run_activities(factory: str, run_id: str) -> dict[str, Any]:
    """Get the per activity breakdown of one pipeline run.

    Each entry has a status, a duration, and an error code when it failed. A status of
    'Skipped' means an upstream activity in the same pipeline did not succeed, so a
    skipped activity is never itself the problem.

    Args:
        factory: Factory name.
        run_id: Run id from list_pipeline_runs.
    """
    try:
        query.check_factory(factory)
        run = query.get_run(run_id)
    except query.AdfError as exc:
        raise _fail(exc) from exc
    return {
        "factory": factory,
        "runId": run.run_id,
        "pipelineName": run.pipeline,
        "status": run.status,
        "value": [activity.to_api(run.run_id) for activity in run.activities],
    }


@mcp.tool()
def get_activity_error(factory: str, run_id: str, activity: str) -> dict[str, Any]:
    """Get the full error payload for one failed activity.

    The `message` is the operator facing string and usually contains an inner
    'ErrorCode=' token, which is the part worth quoting in an incident note.

    Args:
        factory: Factory name.
        run_id: Run id from list_pipeline_runs.
        activity: Activity name from get_run_activities.
    """
    try:
        query.check_factory(factory)
        run = query.get_run(run_id)
    except query.AdfError as exc:
        raise _fail(exc) from exc
    for item in run.activities:
        if item.activity_name == activity:
            if not item.error:
                return {
                    "runId": run_id,
                    "activityName": activity,
                    "status": item.status,
                    "error": None,
                    "note": "This activity did not record an error.",
                }
            return {
                "runId": run_id,
                "pipelineName": run.pipeline,
                "activityName": activity,
                "status": item.status,
                "error": item.error,
            }
    names = ", ".join(item.activity_name for item in run.activities)
    raise ToolError(f"activity '{activity}' not found in run {run_id}. Activities: {names}.")


@mcp.tool()
def find_upstream_dependencies(factory: str, pipeline: str, max_depth: int = 8) -> dict[str, Any]:
    """Walk the dependency graph upstream from a pipeline.

    Follows two edge kinds: dataset lineage (another pipeline writes a dataset this one
    reads) and control flow (another pipeline launches this one with ExecutePipeline).
    Use this before concluding that a failing pipeline is the cause of an incident. The
    pipeline that pages you is often three hops downstream of the one that broke.

    Args:
        factory: Factory name.
        pipeline: Pipeline to start from.
        max_depth: How many hops to walk. The graph here is shallow, 8 is plenty.
    """
    try:
        query.check_factory(factory)
        return query.find_upstream(pipeline, max_depth=max_depth)
    except query.AdfError as exc:
        raise _fail(exc) from exc


@mcp.tool()
def summarize_failures(factory: str, since: str | None = None) -> dict[str, Any]:
    """Aggregate failed runs in a window, grouped by the error code of the failing activity.

    This answers 'what broke last night'. It deliberately does not answer 'why', because
    several distinct error codes frequently share a single upstream cause.

    Args:
        factory: Factory name.
        since: Window start. ISO 8601 such as '2026-03-11', or relative such as '2d'.
    """
    try:
        query.check_factory(factory)
        return query.summarize_failures(since)
    except query.AdfError as exc:
        raise _fail(exc) from exc


def main() -> None:
    """Run the server over stdio."""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
