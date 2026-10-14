"""Tests for suite loading, and consistency checks over the suites in this repo."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from groundwork.core.evals.case import EvalSuite, ScorerSpec, load_suite
from groundwork.core.evals.runner import RunnerOptions, _recording_path
from groundwork.core.evals.scorers import available_scorers
from groundwork.core.skills import discover_skills

MINIMAL = """
name: demo
servers:
  - name: s
    command: "{python}"
    args: ["-m", "nothing"]
cases:
  - id: one
    prompt: do the thing
    scorers:
      - type: contains
        value: thing
      - no_tool_errors
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "suite.yaml"
    path.write_text(text, encoding="utf-8")
    return path


class TestScorerSpec:
    def test_bare_string_form(self) -> None:
        spec = ScorerSpec.parse("no_tool_errors")
        assert spec.type == "no_tool_errors"
        assert spec.params == {}

    def test_mapping_form_collects_params(self) -> None:
        spec = ScorerSpec.parse({"type": "contains", "value": "x", "mode": "all"})
        assert spec.params == {"value": "x", "mode": "all"}

    def test_mapping_without_a_type_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="needs a 'type' key"):
            ScorerSpec.parse({"value": "x"})

    def test_a_list_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="string or a mapping"):
            ScorerSpec.parse(["contains"])


class TestLoadSuite:
    def test_round_trip(self, tmp_path: Path) -> None:
        suite = load_suite(write(tmp_path, MINIMAL))
        assert suite.name == "demo"
        assert suite.path is not None
        assert [spec.type for spec in suite.cases[0].scorers] == ["contains", "no_tool_errors"]

    def test_python_placeholder_expands_to_this_interpreter(self, tmp_path: Path) -> None:
        config = load_suite(write(tmp_path, MINIMAL)).server_configs()[0]
        assert config.command == sys.executable

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="no such eval suite"):
            load_suite(tmp_path / "absent.yaml")

    def test_a_non_mapping_suite_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            load_suite(write(tmp_path, "- just\n- a list\n"))

    def test_name_defaults_to_the_filename(self, tmp_path: Path) -> None:
        assert load_suite(write(tmp_path, "cases: []\n")).name == "suite"

    def test_unknown_keys_are_a_hard_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError):
            load_suite(write(tmp_path, "name: demo\nunexpected: true\n"))

    def test_an_empty_case_id_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError):
            load_suite(write(tmp_path, "name: d\ncases:\n  - id: '  '\n    prompt: x\n"))


class TestSelection:
    def suite(self) -> EvalSuite:
        return EvalSuite(
            name="demo",
            cases=[{"id": "a", "prompt": "x"}, {"id": "b", "prompt": "y"}],  # type: ignore[list-item]
        )

    def test_no_filter_returns_everything_in_order(self) -> None:
        assert [case.id for case in self.suite().select(None)] == ["a", "b"]

    def test_filter_preserves_suite_order(self) -> None:
        assert [case.id for case in self.suite().select(["b", "a"])] == ["a", "b"]

    def test_unknown_case_id_is_an_error(self) -> None:
        with pytest.raises(KeyError, match="unknown case ids: c"):
            self.suite().select(["c"])

    def test_case_lookup_lists_what_exists(self) -> None:
        with pytest.raises(KeyError, match="have: a, b"):
            self.suite().case("c")


class TestTheSuitesInThisRepo:
    def suites(self, repo_root: Path) -> list[EvalSuite]:
        return [load_suite(path) for path in sorted((repo_root / "evals").glob("*.yaml"))]

    def test_both_domains_have_a_suite(self, repo_root: Path) -> None:
        assert {suite.name for suite in self.suites(repo_root)} == {"adf_ops", "ke_compliance"}

    def test_case_ids_are_unique_within_a_suite(self, repo_root: Path) -> None:
        for suite in self.suites(repo_root):
            ids = [case.id for case in suite.cases]
            assert len(ids) == len(set(ids)), suite.name

    def test_every_scorer_name_is_registered(self, repo_root: Path) -> None:
        known = set(available_scorers())
        for suite in self.suites(repo_root):
            for case in suite.cases:
                for spec in case.scorers:
                    assert spec.type in known, f"{suite.name}/{case.id}: {spec.type}"

    def test_every_case_checks_behaviour_not_just_prose(self, repo_root: Path) -> None:
        """An eval that only greps the answer does not prove the agent did anything."""
        behavioural = {"tool_called", "tool_sequence", "no_tool_errors", "max_tool_calls"}
        for suite in self.suites(repo_root):
            for case in suite.cases:
                types = {spec.type for spec in case.scorers}
                assert types & behavioural, f"{suite.name}/{case.id}"

    def test_every_suite_names_a_skill_that_exists(self, repo_root: Path) -> None:
        names = {skill.name for skill in discover_skills(repo_root / "skills")}
        for suite in self.suites(repo_root):
            assert suite.skill in names, suite.name

    def test_every_case_has_a_recording(self, repo_root: Path) -> None:
        for suite in self.suites(repo_root):
            for case in suite.cases:
                path = _recording_path(suite, case, RunnerOptions())
                assert path.is_file(), f"{suite.name}/{case.id}"

    def test_every_recording_belongs_to_a_case(self, repo_root: Path) -> None:
        for suite in self.suites(repo_root):
            folder = (suite.path or Path()).parent / "recordings" / suite.name
            on_disk = {path.stem for path in folder.glob("*.json")}
            assert on_disk == {case.id for case in suite.cases}, suite.name

    def test_each_suite_has_a_tool_error_recovery_case(self, repo_root: Path) -> None:
        for suite in self.suites(repo_root):
            allowances = [
                spec.params.get("allow", 0)
                for case in suite.cases
                for spec in case.scorers
                if spec.type == "no_tool_errors"
            ]
            assert any(int(value) > 0 for value in allowances), suite.name
