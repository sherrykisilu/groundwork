"""End to end tests against both MCP servers over real stdio transports.

These spawn the servers as subprocesses exactly the way the eval runner does, list
their tools through a real `Client`, and call them. They are slower than the unit
tests and they are the ones that would catch a broken tool schema, a serialisation
problem, or a server that fails to start at all.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from groundwork.core.agent.mcp_client import ServerConfig, Toolkit, ToolkitError

ADF = ServerConfig.from_dict({"name": "adf_ops", "args": ["-m", "groundwork.servers.adf_ops"]})
KE = ServerConfig.from_dict(
    {"name": "ke_compliance", "args": ["-m", "groundwork.servers.ke_compliance"]}
)


async def payload(toolkit: Toolkit, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call a tool and parse its JSON body, asserting it did not error."""
    text, is_error = await toolkit.call(name, arguments)
    assert not is_error, f"{name} failed: {text}"
    return json.loads(text)


class TestAdfServerOverStdio:
    async def test_lists_the_documented_tools(self) -> None:
        async with Toolkit.connect([ADF]) as toolkit:
            assert set(toolkit.tool_names()) == {
                "list_pipelines",
                "get_pipeline",
                "list_pipeline_runs",
                "get_run_activities",
                "get_activity_error",
                "find_upstream_dependencies",
                "summarize_failures",
            }

    async def test_every_tool_advertises_a_description_and_schema(self) -> None:
        async with Toolkit.connect([ADF]) as toolkit:
            for spec in toolkit.tool_specs():
                assert len(spec.description) > 80, spec.name
                assert spec.input_schema["type"] == "object"

    async def test_a_full_triage_walk(self) -> None:
        """The exact path the skill tells the agent to take, over a real transport."""
        async with Toolkit.connect([ADF]) as toolkit:
            summary = await payload(
                toolkit, "summarize_failures", {"factory": "contoso-analytics-adf", "since": "3d"}
            )
            assert summary["failed_run_count"] == 6

            upstream = await payload(
                toolkit,
                "find_upstream_dependencies",
                {"factory": "contoso-analytics-adf", "pipeline": "publish_sales_dashboard"},
            )
            assert upstream["root_pipelines"] == ["ingest_sales_raw"]

            runs = await payload(
                toolkit,
                "list_pipeline_runs",
                {
                    "factory": "contoso-analytics-adf",
                    "pipeline": "ingest_sales_raw",
                    "status": "Failed",
                    "since": "3d",
                },
            )
            run_id = runs["runs"][0]["runId"]

            activities = await payload(
                toolkit,
                "get_run_activities",
                {"factory": "contoso-analytics-adf", "run_id": run_id},
            )
            failing = [a for a in activities["value"] if a["status"] == "Failed"]
            assert [a["activityName"] for a in failing] == ["CopySalesFromRestApi"]

            error = await payload(
                toolkit,
                "get_activity_error",
                {
                    "factory": "contoso-analytics-adf",
                    "run_id": run_id,
                    "activity": "CopySalesFromRestApi",
                },
            )
            assert "RestSourceCallFailed" in json.dumps(error)

    async def test_an_unknown_pipeline_is_a_recoverable_tool_error(self) -> None:
        async with Toolkit.connect([ADF]) as toolkit:
            text, is_error = await toolkit.call(
                "get_pipeline",
                {"factory": "contoso-analytics-adf", "name": "sales_ingest_pipeline"},
            )
            assert is_error
            assert "not found" in text

    async def test_an_unknown_factory_is_a_recoverable_tool_error(self) -> None:
        async with Toolkit.connect([ADF]) as toolkit:
            text, is_error = await toolkit.call("list_pipelines", {"factory": "other-adf"})
            assert is_error
            assert "contoso-analytics-adf" in text

    async def test_an_unknown_tool_name_never_reaches_the_server(self) -> None:
        async with Toolkit.connect([ADF]) as toolkit:
            text, is_error = await toolkit.call("drop_database", {})
            assert is_error
            assert "Available tools" in text


class TestKeComplianceServerOverStdio:
    async def test_lists_the_documented_tools(self) -> None:
        async with Toolkit.connect([KE]) as toolkit:
            assert set(toolkit.tool_names()) == {
                "search_corpus",
                "list_documents",
                "get_document",
                "get_section",
                "list_obligations",
                "check_applicability_for_profile",
            }

    async def test_tool_descriptions_say_the_corpus_is_synthetic(self) -> None:
        async with Toolkit.connect([KE]) as toolkit:
            blob = " ".join(spec.description.lower() for spec in toolkit.tool_specs())
            assert "synthetic" in blob
            assert "not legal advice" in blob

    async def test_search_then_cite(self) -> None:
        async with Toolkit.connect([KE]) as toolkit:
            hits = await payload(
                toolkit, "search_corpus", {"query": "register as a data controller", "top_k": 3}
            )
            top = hits["results"][0]
            assert top["citation"].startswith("DOC-DPA-01#")

            section = await payload(
                toolkit,
                "get_section",
                {"doc_id": "DOC-DPA-01", "section_id": top["citation"].split("#")[1]},
            )
            assert section["citation"] == top["citation"]
            assert "SYNTHETIC" in json.dumps(section)

    async def test_applicability_over_the_wire(self) -> None:
        async with Toolkit.connect([KE]) as toolkit:
            result = await payload(
                toolkit,
                "check_applicability_for_profile",
                {
                    "profile": {
                        "employees": 4,
                        "annual_turnover_kes": 3_200_000,
                        "sector": "food",
                        "handles_personal_data": True,
                        "has_physical_premises": True,
                    }
                },
            )
            ids = {item["obligation_id"] for item in result["applicable"]}
            assert "OB-TAX-TOT" in ids
            assert "OB-TAX-VAT" not in ids

    async def test_an_invented_document_id_errors_and_names_the_real_ones(self) -> None:
        async with Toolkit.connect([KE]) as toolkit:
            text, is_error = await toolkit.call("get_document", {"doc_id": "DOC-TAX-03"})
            assert is_error
            assert "DOC-TAX-01" in text

    async def test_a_bad_profile_errors_rather_than_guessing(self) -> None:
        async with Toolkit.connect([KE]) as toolkit:
            _text, is_error = await toolkit.call(
                "check_applicability_for_profile",
                {"profile": {"employees": 1, "sector": "aerospace"}},
            )
            assert is_error


class TestBothServersTogether:
    async def test_tools_from_two_servers_share_one_namespace(self) -> None:
        async with Toolkit.connect([ADF, KE]) as toolkit:
            names = set(toolkit.tool_names())
            assert "list_pipelines" in names
            assert "search_corpus" in names
            assert toolkit.server_for("search_corpus") == "ke_compliance"
            assert toolkit.server_for("list_pipelines") == "adf_ops"
            assert toolkit.has_tool("get_document")
            assert not toolkit.has_tool("nope")


async def test_a_server_that_cannot_start_is_a_clear_error() -> None:
    broken = ServerConfig.from_dict({"name": "broken", "args": ["-m", "groundwork.not_a_module"]})
    with pytest.raises(ToolkitError, match="could not start"):
        async with Toolkit.connect([broken]):
            pass


def test_server_config_requires_a_name() -> None:
    with pytest.raises(ToolkitError, match="missing 'name'"):
        ServerConfig.from_dict({"command": "python"})


def test_server_config_splits_a_string_arg_list() -> None:
    config = ServerConfig.from_dict({"name": "s", "args": "-m groundwork.servers.adf_ops"})
    assert config.args == ["-m", "groundwork.servers.adf_ops"]
