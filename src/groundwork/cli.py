"""The `groundwork` command line interface."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from rich.console import Console

from . import __version__
from .core.evals.case import load_suite
from .core.evals.report import print_report, write_json, write_markdown
from .core.evals.runner import RunnerOptions, run_suite
from .core.evals.scorers import available_scorers
from .core.skills import SkillError, discover_skills

SERVERS = {
    "adf_ops": "groundwork.servers.adf_ops",
    "ke_compliance": "groundwork.servers.ke_compliance",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="groundwork",
        description="A forward deployed engineering toolkit: MCP tools, skills, and evals.",
    )
    parser.add_argument("--version", action="version", version=f"groundwork {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run-eval", help="run an eval suite")
    run.add_argument("suite", help="path to a suite YAML file")
    run.add_argument(
        "--provider",
        default="replay",
        choices=("replay", "anthropic"),
        help="replay runs offline from recordings, anthropic calls the real API",
    )
    run.add_argument("--model", default=None, help="model id, only used with --provider anthropic")
    run.add_argument(
        "--case",
        action="append",
        default=[],
        dest="cases",
        help="run only this case id, repeatable",
    )
    run.add_argument("--concurrency", type=int, default=4, help="cases to run at once")
    run.add_argument("--retries", type=int, default=0, help="retries on infrastructure errors")
    run.add_argument(
        "--record",
        action="store_true",
        help="write recordings from a live run, for later replay",
    )
    run.add_argument(
        "--judge",
        action="store_true",
        help="enable the judge scorer, needs ANTHROPIC_API_KEY",
    )
    run.add_argument("--skills", default="skills", help="skills directory")
    run.add_argument("--report", default=None, help="write a markdown report to this path")
    run.add_argument("--json", default=None, dest="json_path", help="write raw results as JSON")
    run.add_argument("--verbose", action="store_true", help="show scorer detail for passing cases")

    skills = sub.add_parser("list-skills", help="list the skills in a directory")
    skills.add_argument("--skills", default="skills", help="skills directory")
    skills.add_argument("--show", default=None, help="print the full body of one skill")

    serve = sub.add_parser("serve", help="run one of the bundled MCP servers over stdio")
    serve.add_argument("server", choices=sorted(SERVERS), help="which server to run")

    report = sub.add_parser("report", help="re-render a saved JSON result as markdown")
    report.add_argument("json_path", help="a file written by run-eval --json")
    report.add_argument("--out", default=None, help="write markdown here instead of stdout")

    sub.add_parser("list-scorers", help="list the scorers a suite can use")

    return parser


def _cmd_run_eval(args: argparse.Namespace, console: Console) -> int:
    suite = load_suite(args.suite)
    options = RunnerOptions(
        provider=args.provider,
        model=args.model,
        only=list(args.cases),
        concurrency=args.concurrency,
        retries=args.retries,
        record=args.record,
        judge=args.judge,
        skills_dir=Path(args.skills),
    )
    result = asyncio.run(run_suite(suite, options))
    print_report(result, console=console, verbose=args.verbose)
    if args.report:
        path = write_markdown(result, args.report)
        console.print(f"wrote {path}")
    if args.json_path:
        path = write_json(result, args.json_path)
        console.print(f"wrote {path}")
    return 0 if result.passed else 1


def _cmd_list_skills(args: argparse.Namespace, console: Console) -> int:
    try:
        skills = discover_skills(args.skills)
    except SkillError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    if args.show:
        for skill in skills:
            if skill.name == args.show:
                console.print(skill.as_system_prompt())
                return 0
        console.print(f"[red]no skill named '{args.show}'[/red]")
        return 2
    if not skills:
        console.print(f"no SKILL.md files under {args.skills}")
        return 0
    for skill in skills:
        console.print(f"[bold]{skill.name}[/bold]  ({skill.path})")
        console.print(f"  {skill.description}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import runpy

    sys.argv = [sys.argv[0]]
    runpy.run_module(SERVERS[args.server], run_name="__main__")
    return 0


def _cmd_report(args: argparse.Namespace, console: Console) -> int:
    payload = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    lines = [
        f"# Eval report: {payload.get('suite', 'unknown')}",
        "",
        f"- provider: `{payload.get('provider')}`",
        f"- result: **{payload.get('pass_count')}/{len(payload.get('cases', []))} passed**",
        "",
        "| case | result | tool calls |",
        "| --- | --- | --- |",
    ]
    for case in payload.get("cases", []):
        mark = "PASS" if case.get("passed") else "FAIL"
        calls = len(case.get("transcript", {}).get("tool_calls", []))
        lines.append(f"| `{case.get('case_id')}` | {mark} | {calls} |")
    text = "\n".join(lines) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        console.print(f"wrote {args.out}")
    else:
        console.print(text)
    return 0 if payload.get("passed") else 1


def main(argv: list[str] | None = None) -> int:
    """Entry point for the `groundwork` console script."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    console = Console()

    if args.command == "serve":
        return _cmd_serve(args)
    if args.command == "run-eval":
        return _cmd_run_eval(args, console)
    if args.command == "list-skills":
        return _cmd_list_skills(args, console)
    if args.command == "report":
        return _cmd_report(args, console)
    if args.command == "list-scorers":
        for name in available_scorers():
            console.print(name)
        return 0
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
