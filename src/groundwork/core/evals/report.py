"""Reporting.

Two audiences. The console table is for the engineer who just changed something and
wants to know in one second whether it still works. The markdown report is for the
customer, who was not in the room and needs to see what was checked and what was not.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .runner import CaseResult, SuiteResult

PASS_MARK = "PASS"
FAIL_MARK = "FAIL"


def _status(passed: bool) -> Text:
    return Text(PASS_MARK, style="bold green") if passed else Text(FAIL_MARK, style="bold red")


def print_report(
    result: SuiteResult, *, console: Console | None = None, verbose: bool = False
) -> None:
    """Print a suite result as a table, with failure detail underneath."""
    console = console or Console()

    table = Table(
        title=f"{result.suite}  (provider: {result.provider})",
        title_style="bold",
        header_style="bold",
        show_lines=False,
    )
    table.add_column("", width=4)
    table.add_column("case", overflow="fold")
    table.add_column("scorers", justify="right")
    table.add_column("tools", justify="right")
    table.add_column("turns", justify="right")
    table.add_column("ms", justify="right")

    for case in result.results:
        passed_scores = sum(1 for score in case.scores if score.passed)
        table.add_row(
            _status(case.passed),
            case.case_id,
            f"{passed_scores}/{len(case.scores)}",
            str(case.tool_call_count),
            str(case.transcript.turn_count),
            f"{case.duration_ms:.0f}",
        )

    console.print(table)

    for case in result.results:
        if case.passed and not verbose:
            continue
        console.print()
        console.print(Text(f"{case.case_id}", style="bold"))
        if case.error:
            console.print(Text(f"  run error: {case.error}", style="red"))
        for score in case.scores:
            style = "green" if score.passed else "red"
            mark = PASS_MARK if score.passed else FAIL_MARK
            console.print(Text(f"  {mark} {score.scorer}: {score.reason}", style=style))
        if not case.passed:
            answer = case.transcript.final_text.strip() or "(no final answer)"
            console.print(Text("  final answer:", style="dim"))
            for line in answer.splitlines()[:12]:
                console.print(Text(f"    {line}", style="dim"))

    summary_style = "bold green" if result.passed else "bold red"
    console.print()
    console.print(
        Text(
            f"{result.pass_count}/{len(result.results)} cases passed "
            f"in {result.duration_ms / 1000:.1f}s",
            style=summary_style,
        )
    )


def _case_markdown(case: CaseResult) -> list[str]:
    mark = PASS_MARK if case.passed else FAIL_MARK
    lines = [
        f"### {mark}  `{case.case_id}`",
        "",
        (
            f"- tool calls: {case.tool_call_count} "
            f"({', '.join(case.transcript.tool_names) or 'none'})"
        ),
        f"- model turns: {case.transcript.turn_count}",
        f"- duration: {case.duration_ms:.0f} ms",
    ]
    if case.error:
        lines.append(f"- run error: `{case.error}`")
    lines.append("")
    lines.append("| scorer | result | detail |")
    lines.append("| --- | --- | --- |")
    for score in case.scores:
        detail = score.reason.replace("|", "\\|")
        lines.append(
            f"| `{score.scorer}` | {PASS_MARK if score.passed else FAIL_MARK} | {detail} |"
        )
    lines.append("")
    return lines


def render_markdown(result: SuiteResult) -> str:
    """Render a suite result as a markdown report."""
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Eval report: {result.suite}",
        "",
        f"- provider: `{result.provider}`",
        f"- generated: {stamp}",
        f"- result: **{result.pass_count}/{len(result.results)} passed**",
        f"- wall clock: {result.duration_ms / 1000:.1f}s",
        "",
        "| case | result | scorers passed | tool calls | turns | ms |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for case in result.results:
        passed_scores = sum(1 for score in case.scores if score.passed)
        lines.append(
            f"| `{case.case_id}` | {PASS_MARK if case.passed else FAIL_MARK} | "
            f"{passed_scores}/{len(case.scores)} | {case.tool_call_count} | "
            f"{case.transcript.turn_count} | {case.duration_ms:.0f} |"
        )
    lines.append("")
    lines.append("## Cases")
    lines.append("")
    for case in result.results:
        lines.extend(_case_markdown(case))
    return "\n".join(lines).rstrip() + "\n"


def write_markdown(result: SuiteResult, path: str | Path) -> Path:
    """Write the markdown report to disk."""
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(render_markdown(result), encoding="utf-8")
    return resolved


def write_json(result: SuiteResult, path: str | Path) -> Path:
    """Write the machine readable result to disk, for trend tracking over time."""
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return resolved
