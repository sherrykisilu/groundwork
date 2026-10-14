"""Tests for the ADF dependency graph and run queries.

The point of the domain is that the pipeline that pages you is usually not the
pipeline that broke. These tests pin the traversal that proves it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from groundwork.servers.adf_ops import query
from groundwork.servers.adf_ops.fixtures import FACTORY, NOW, PIPELINES, PIPELINES_BY_NAME, RUNS


class TestFixtureShape:
    def test_the_factory_has_a_realistic_number_of_pipelines(self) -> None:
        assert 8 <= len(PIPELINES) <= 12

    def test_run_ids_are_unique(self) -> None:
        ids = [run.run_id for run in RUNS]
        assert len(ids) == len(set(ids))

    def test_runs_are_deterministic_across_calls(self) -> None:
        """Durations are derived from a stable hash, not Python's salted hash()."""
        from importlib import reload

        from groundwork.servers.adf_ops import fixtures

        before = [(run.run_id, run.duration_ms) for run in RUNS]
        reload(fixtures)
        after = [(run.run_id, run.duration_ms) for run in fixtures.RUNS]
        assert before == after

    def test_every_run_belongs_to_a_known_pipeline(self) -> None:
        assert all(run.pipeline in PIPELINES_BY_NAME for run in RUNS)


class TestFactoryValidation:
    def test_wrong_factory_is_a_clear_error(self) -> None:
        with pytest.raises(query.AdfError, match="not found"):
            query.check_factory("some-other-adf")

    def test_right_factory_passes(self) -> None:
        query.check_factory(FACTORY)


class TestDirectUpstream:
    def test_an_ingest_pipeline_has_no_upstream(self) -> None:
        assert query.direct_upstream("ingest_sales_raw") == []

    def test_a_transform_depends_on_its_ingest(self) -> None:
        edges = query.direct_upstream("transform_sales_clean")
        assert any(edge["pipeline"] == "ingest_sales_raw" for edge in edges)

    def test_edges_say_why_they_exist(self) -> None:
        edges = query.direct_upstream("transform_sales_clean")
        assert {edge["edge"] for edge in edges} <= {"dataset", "execute_pipeline"}
        assert all(edge["via"] for edge in edges)

    def test_unknown_pipeline_raises(self) -> None:
        with pytest.raises(query.AdfError, match="not found"):
            query.direct_upstream("sales_ingest_pipeline")


class TestFindUpstream:
    def test_two_hop_traversal_reaches_the_real_root(self) -> None:
        result = query.find_upstream("publish_sales_dashboard")
        assert result["upstream_pipelines"] == ["ingest_sales_raw", "transform_sales_clean"]
        assert result["root_pipelines"] == ["ingest_sales_raw"]

    def test_levels_are_ordered_by_depth(self) -> None:
        levels = query.find_upstream("publish_sales_dashboard")["levels"]
        assert [level["depth"] for level in levels] == list(range(1, len(levels) + 1))

    def test_a_join_pipeline_has_more_than_one_root(self) -> None:
        result = query.find_upstream("transform_customer_360")
        assert result["root_pipelines"] == ["ingest_crm_contacts", "ingest_sales_raw"]

    def test_a_root_pipeline_reports_no_upstream(self) -> None:
        result = query.find_upstream("ingest_sales_raw")
        assert result["upstream_pipelines"] == []
        assert result["levels"] == []

    def test_max_depth_truncates_the_walk(self) -> None:
        shallow = query.find_upstream("publish_sales_dashboard", max_depth=1)
        assert shallow["upstream_pipelines"] == ["transform_sales_clean"]

    def test_traversal_terminates_on_every_pipeline(self) -> None:
        for pipeline in PIPELINES_BY_NAME:
            result = query.find_upstream(pipeline)
            assert pipeline not in result["upstream_pipelines"]


class TestParseSince:
    def test_relative_days_window_is_right(self) -> None:
        assert (NOW - query._parse_since("3d")).days == 3

    def test_relative_hours(self) -> None:
        assert (NOW - query._parse_since("6h")).seconds == 6 * 3600

    def test_iso_date(self) -> None:
        assert query._parse_since("2026-03-11") == datetime(2026, 3, 11, tzinfo=UTC)

    def test_iso_datetime_with_z(self) -> None:
        assert query._parse_since("2026-03-11T06:00:00Z") == datetime(2026, 3, 11, 6, 0, tzinfo=UTC)

    def test_default_window(self) -> None:
        assert (NOW - query._parse_since(None)).days == 7

    def test_garbage_raises_with_an_example(self) -> None:
        with pytest.raises(query.AdfError, match="2026-03-11"):
            query._parse_since("last tuesday")


class TestFilterRuns:
    def test_window_excludes_older_runs(self) -> None:
        cutoff = query._parse_since("1d")
        assert all(run.start >= cutoff for run in query.filter_runs(since="1d", limit=999))

    def test_status_filter_is_case_insensitive(self) -> None:
        runs = query.filter_runs(status="failed", since="30d", limit=999)
        assert runs and all(run.status == "Failed" for run in runs)

    def test_pipeline_filter(self) -> None:
        runs = query.filter_runs(pipeline="ingest_sales_raw", since="30d", limit=999)
        assert runs and all(run.pipeline == "ingest_sales_raw" for run in runs)

    def test_unknown_pipeline_raises(self) -> None:
        with pytest.raises(query.AdfError, match="not found"):
            query.filter_runs(pipeline="nope")

    def test_limit_is_respected(self) -> None:
        assert len(query.filter_runs(since="30d", limit=3)) == 3


class TestGetRun:
    def test_unknown_run_points_at_the_listing_tool(self) -> None:
        with pytest.raises(query.AdfError, match="list_pipeline_runs"):
            query.get_run("00000000-0000-0000-0000-000000000000")

    def test_known_run_round_trips(self) -> None:
        run = RUNS[0]
        assert query.get_run(run.run_id) is run


class TestSummarizeFailures:
    def test_the_cascade_window_has_six_failures(self) -> None:
        summary = query.summarize_failures("3d")
        assert summary["failed_run_count"] == 6

    def test_distinct_error_codes_look_unrelated(self) -> None:
        """Six failures, six codes. Grouping by code would suggest six incidents."""
        summary = query.summarize_failures("3d")
        assert len(summary["by_error_code"]) == 6

    def test_the_note_warns_against_treating_codes_as_causes(self) -> None:
        assert "find_upstream_dependencies" in query.summarize_failures("3d")["note"]

    def test_every_bucket_names_an_example_run(self) -> None:
        for bucket in query.summarize_failures("3d")["by_error_code"]:
            assert query.get_run(bucket["example_run_id"])


class TestShortCode:
    def test_extracts_the_quoted_token(self) -> None:
        message = "Failure happened. ErrorCode=RestSourceCallFailed,'Type=Microsoft.DataTransfer'"
        assert query._short_code(message) == "RestSourceCallFailed"

    def test_absent_marker_returns_empty(self) -> None:
        assert query._short_code("something went wrong") == ""


class TestTheCascadeNarrative:
    """The specific story the eval suite depends on."""

    def _run(self, index: int):
        return query.get_run(f"3f1a9c20-0e51-4a1b-0311-7c1f2d0a{index:04d}")

    def test_the_only_true_cause_is_a_throttled_copy(self) -> None:
        run = self._run(1)
        assert run.pipeline == "ingest_sales_raw"
        failing = list(query.failed_activities(run))
        assert [a.activity_name for a in failing] == ["CopySalesFromRestApi"]
        assert "RestSourceCallFailed" in failing[0].error["message"]

    def test_downstream_failures_look_unrelated_at_the_activity_level(self) -> None:
        downstream = {self._run(i).pipeline: self._run(i) for i in (2, 3)}
        codes = {
            query._short_code(a.error.get("message", "")) or a.error.get("errorCode")
            for run in downstream.values()
            for a in query.failed_activities(run)
        }
        assert "RestSourceCallFailed" not in codes

    def test_skipped_activities_are_not_failures(self) -> None:
        run = self._run(1)
        skipped = [a.activity_name for a in run.activities if a.status == "Skipped"]
        assert skipped
        assert not any(a.status == "Skipped" for a in query.failed_activities(run))

    def test_the_marketing_failure_is_genuinely_independent(self) -> None:
        run = self._run(6)
        assert run.pipeline == "ingest_marketing_events"
        assert query.find_upstream(run.pipeline)["upstream_pipelines"] == []

    def test_the_rerun_the_next_morning_succeeded(self) -> None:
        run = query.get_run("3f1a9c20-0e51-4a1b-0312-7c1f2d0a0001")
        assert run.status == "Succeeded"
        assert run.pipeline == "ingest_sales_raw"
