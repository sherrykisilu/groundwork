"""Tests for the CLI and the report renderers.

The CLI tests double as the integration check for the runner: `run-eval` under
replay spawns the real MCP servers, runs the real scorers, and must exit non zero on
failure, because that exit code is the only thing CI looks at.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from groundwork.cli import main


class TestListCommands:
    def test_list_scorers(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["list-scorers"]) == 0
        assert "cites_source" in capsys.readouterr().out

    def test_list_skills(self, repo_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["list-skills", "--skills", str(repo_root / "skills")]) == 0
        out = capsys.readouterr().out
        assert "adf-triage" in out
        assert "compliance-answer" in out

    def test_show_one_skill(self, repo_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert (
            main(["list-skills", "--skills", str(repo_root / "skills"), "--show", "adf-triage"])
            == 0
        )
        assert "# Skill: adf-triage" in capsys.readouterr().out

    def test_show_an_unknown_skill_exits_non_zero(self, repo_root: Path) -> None:
        assert main(["list-skills", "--skills", str(repo_root / "skills"), "--show", "nope"]) == 2

    def test_a_missing_skills_directory_exits_non_zero(self, tmp_path: Path) -> None:
        assert main(["list-skills", "--skills", str(tmp_path / "absent")]) == 2

    def test_no_command_is_a_usage_error(self) -> None:
        with pytest.raises(SystemExit):
            main([])


class TestRunEval:
    def test_the_adf_suite_passes_offline(
        self, repo_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(
            [
                "run-eval",
                str(repo_root / "evals" / "adf_ops.yaml"),
                "--provider",
                "replay",
                "--skills",
                str(repo_root / "skills"),
            ]
        )
        out = capsys.readouterr().out
        assert code == 0, out
        assert "cases passed" in out

    def test_the_compliance_suite_passes_offline(
        self, repo_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(
            [
                "run-eval",
                str(repo_root / "evals" / "ke_compliance.yaml"),
                "--provider",
                "replay",
                "--skills",
                str(repo_root / "skills"),
            ]
        )
        assert code == 0, capsys.readouterr().out

    def test_case_filtering_and_report_writing(
        self, repo_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        markdown = tmp_path / "report.md"
        raw = tmp_path / "result.json"
        code = main(
            [
                "run-eval",
                str(repo_root / "evals" / "adf_ops.yaml"),
                "--case",
                "root_cause_cascade",
                "--skills",
                str(repo_root / "skills"),
                "--report",
                str(markdown),
                "--json",
                str(raw),
            ]
        )
        capsys.readouterr()
        assert code == 0
        assert "root_cause_cascade" in markdown.read_text(encoding="utf-8")
        payload = json.loads(raw.read_text(encoding="utf-8"))
        assert payload["pass_count"] == 1
        assert payload["cases"][0]["case_id"] == "root_cause_cascade"

    def test_a_failing_suite_exits_non_zero(
        self, repo_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CI only knows the suite failed because of this exit code."""
        suite = tmp_path / "broken.yaml"
        suite.write_text(
            "name: adf_ops\n"
            "servers:\n"
            "  - name: adf_ops\n"
            "    args: ['-m', 'groundwork.servers.adf_ops']\n"
            "cases:\n"
            "  - id: root_cause_cascade\n"
            "    prompt: what broke\n"
            "    scorers:\n"
            "      - type: contains\n"
            "        value: a string that will never appear\n",
            encoding="utf-8",
        )
        # Point the recordings at the real ones by name, so only the scorer fails.
        recordings = tmp_path / "recordings" / "adf_ops"
        recordings.mkdir(parents=True)
        source = repo_root / "evals" / "recordings" / "adf_ops" / "root_cause_cascade.json"
        (recordings / "root_cause_cascade.json").write_text(
            source.read_text(encoding="utf-8"), encoding="utf-8"
        )
        code = main(["run-eval", str(suite), "--skills", str(repo_root / "skills")])
        out = capsys.readouterr().out
        assert code == 1
        assert "FAIL" in out

    def test_a_missing_recording_fails_the_case_rather_than_the_run(
        self, repo_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        suite = tmp_path / "norec.yaml"
        suite.write_text(
            "name: norec\n"
            "servers:\n"
            "  - name: adf_ops\n"
            "    args: ['-m', 'groundwork.servers.adf_ops']\n"
            "cases:\n"
            "  - id: ghost\n"
            "    prompt: hello\n"
            "    scorers:\n"
            "      - no_tool_errors\n",
            encoding="utf-8",
        )
        code = main(["run-eval", str(suite), "--skills", str(repo_root / "skills")])
        out = capsys.readouterr().out
        assert code == 1
        assert "recording" in out.lower()

    def test_an_unknown_case_id_is_reported(self, repo_root: Path) -> None:
        with pytest.raises(KeyError, match="unknown case ids"):
            main(
                [
                    "run-eval",
                    str(repo_root / "evals" / "adf_ops.yaml"),
                    "--case",
                    "no_such_case",
                    "--skills",
                    str(repo_root / "skills"),
                ]
            )


class TestReportCommand:
    def test_rerenders_a_saved_result(
        self, repo_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        raw = tmp_path / "result.json"
        main(
            [
                "run-eval",
                str(repo_root / "evals" / "adf_ops.yaml"),
                "--case",
                "already_recovered",
                "--skills",
                str(repo_root / "skills"),
                "--json",
                str(raw),
            ]
        )
        capsys.readouterr()
        out_path = tmp_path / "again.md"
        assert main(["report", str(raw), "--out", str(out_path)]) == 0
        assert "already_recovered" in out_path.read_text(encoding="utf-8")

    def test_prints_to_stdout_without_out(
        self, repo_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        raw = tmp_path / "result.json"
        main(
            [
                "run-eval",
                str(repo_root / "evals" / "adf_ops.yaml"),
                "--case",
                "already_recovered",
                "--skills",
                str(repo_root / "skills"),
                "--json",
                str(raw),
            ]
        )
        capsys.readouterr()
        assert main(["report", str(raw)]) == 0
        assert "Eval report" in capsys.readouterr().out


class TestMarkdownRendering:
    def test_report_contains_the_scorer_detail(
        self, repo_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        markdown = tmp_path / "report.md"
        main(
            [
                "run-eval",
                str(repo_root / "evals" / "ke_compliance.yaml"),
                "--case",
                "out_of_scope_refusal",
                "--skills",
                str(repo_root / "skills"),
                "--report",
                str(markdown),
            ]
        )
        capsys.readouterr()
        text = markdown.read_text(encoding="utf-8")
        assert "| scorer | result | detail |" in text
        assert "`tool_called`" in text
        assert "search_corpus" in text
