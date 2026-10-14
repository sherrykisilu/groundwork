"""Synthetic fixture data for the `adf_ops` server.

Everything in this module is invented. It is shaped like the public Azure Data
Factory REST API (pipelines with activities and `dependsOn` edges, pipeline runs,
activity runs, and error payloads with `errorCode` / `failureType` / `message`) so
that the agent is reasoning over a realistic surface, but no real factory, pipeline,
dataset, error taxonomy, or operational data is represented here.

The interesting thing in the data is a failure cascade on 2026-03-11:

    ingest_sales_raw            CopySalesFromRestApi hits HTTP 429 from the source API
      -> transform_sales_clean  MergeSalesDelta reports a missing path
      -> publish_sales_dashboard LoadDashboardMart reports an invalid SQL object
      -> transform_customer_360 BuildCustomer360 reports a missing source file

Only the first of those is a real problem. The other three are symptoms, and each one
reports a symptom that points at the wrong team: storage, the database, and the data
flow runtime respectively. A separate and genuinely independent failure the same day,
`ingest_marketing_events` failing on an expired credential, is there so that "group
the failures by root cause" is a real question rather than a trick one.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

FACTORY = "contoso-analytics-adf"
NOW = datetime(2026, 3, 12, 9, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Activity:
    """One activity inside a pipeline definition."""

    name: str
    type: str
    depends_on: tuple[str, ...] = ()
    invokes: str | None = None

    def to_api(self) -> dict[str, Any]:
        """Render in the shape the public ADF pipeline definition uses."""
        payload: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "dependsOn": [
                {"activity": upstream, "dependencyConditions": ["Succeeded"]}
                for upstream in self.depends_on
            ],
        }
        if self.invokes:
            payload["typeProperties"] = {
                "pipeline": {"referenceName": self.invokes, "type": "PipelineReference"},
                "waitOnCompletion": True,
            }
        return payload


@dataclass(frozen=True)
class Pipeline:
    """A pipeline definition plus its declared dataset lineage."""

    name: str
    folder: str
    activities: tuple[Activity, ...]
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    description: str = ""

    def to_api(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "properties": {
                "description": self.description,
                "folder": {"name": self.folder},
                "activities": [activity.to_api() for activity in self.activities],
                "annotations": sorted({self.folder}),
            },
            "lineage": {"inputs": list(self.inputs), "outputs": list(self.outputs)},
        }


PIPELINES: tuple[Pipeline, ...] = (
    Pipeline(
        name="ingest_sales_raw",
        folder="ingest",
        description="Pulls the point of sale feed from the vendor REST API into landing.",
        activities=(
            Activity("CopySalesFromRestApi", "Copy"),
            Activity("ValidateSalesLanding", "Validation", depends_on=("CopySalesFromRestApi",)),
            Activity(
                "TriggerSalesTransform",
                "ExecutePipeline",
                depends_on=("ValidateSalesLanding",),
                invokes="transform_sales_clean",
            ),
        ),
        inputs=("ds_sales_rest_api",),
        outputs=("ds_sales_landing",),
    ),
    Pipeline(
        name="ingest_crm_contacts",
        folder="ingest",
        description="Nightly contact extract from the CRM.",
        activities=(
            Activity("CopyCrmContacts", "Copy"),
            Activity(
                "TriggerCustomer360",
                "ExecutePipeline",
                depends_on=("CopyCrmContacts",),
                invokes="transform_customer_360",
            ),
        ),
        inputs=("ds_crm_api",),
        outputs=("ds_crm_landing",),
    ),
    Pipeline(
        name="ingest_inventory_feed",
        folder="ingest",
        description="SFTP drop of warehouse stock levels.",
        activities=(
            Activity("CopyInventorySftp", "Copy"),
            Activity(
                "TriggerInventoryPositions",
                "ExecutePipeline",
                depends_on=("CopyInventorySftp",),
                invokes="transform_inventory_positions",
            ),
        ),
        inputs=("ds_inventory_sftp",),
        outputs=("ds_inventory_landing",),
    ),
    Pipeline(
        name="ingest_marketing_events",
        folder="ingest",
        description="Campaign click and impression events from the marketing platform.",
        activities=(Activity("CopyMarketingEvents", "Copy"),),
        inputs=("ds_marketing_api",),
        outputs=("ds_marketing_landing",),
    ),
    Pipeline(
        name="transform_sales_clean",
        folder="transform",
        description="Deduplicates and conforms the landed sales feed into the curated zone.",
        activities=(
            Activity("MergeSalesDelta", "DatabricksNotebook"),
            Activity(
                "RefreshSalesStats", "SqlServerStoredProcedure", depends_on=("MergeSalesDelta",)
            ),
            Activity(
                "TriggerSalesPublish",
                "ExecutePipeline",
                depends_on=("RefreshSalesStats",),
                invokes="publish_sales_dashboard",
            ),
            Activity(
                "TriggerDataQuality",
                "ExecutePipeline",
                depends_on=("RefreshSalesStats",),
                invokes="ops_data_quality_checks",
            ),
        ),
        inputs=("ds_sales_landing",),
        outputs=("ds_sales_curated",),
    ),
    Pipeline(
        name="transform_customer_360",
        folder="transform",
        description="Joins curated sales onto CRM contacts to build the customer 360 table.",
        activities=(
            Activity("WaitForSalesCurated", "Validation"),
            Activity("BuildCustomer360", "ExecuteDataFlow", depends_on=("WaitForSalesCurated",)),
            Activity(
                "TriggerPartnerExtract",
                "ExecutePipeline",
                depends_on=("BuildCustomer360",),
                invokes="publish_partner_extract",
            ),
            Activity(
                "TriggerExecSummary",
                "ExecutePipeline",
                depends_on=("BuildCustomer360",),
                invokes="publish_exec_summary",
            ),
        ),
        inputs=("ds_crm_landing", "ds_sales_curated"),
        outputs=("ds_customer_360",),
    ),
    Pipeline(
        name="transform_inventory_positions",
        folder="transform",
        description="Rolls warehouse stock movements into daily closing positions.",
        activities=(Activity("ComputePositions", "ExecuteDataFlow"),),
        inputs=("ds_inventory_landing",),
        outputs=("ds_inventory_positions",),
    ),
    Pipeline(
        name="publish_sales_dashboard",
        folder="publish",
        description=(
            "Loads the curated sales table into the reporting mart and refreshes the model."
        ),
        activities=(
            Activity("LoadDashboardMart", "Copy"),
            Activity("RefreshSemanticModel", "WebActivity", depends_on=("LoadDashboardMart",)),
        ),
        inputs=("ds_sales_curated",),
        outputs=("ds_sales_mart",),
    ),
    Pipeline(
        name="publish_partner_extract",
        folder="publish",
        description="Writes the daily partner CSV and notifies the partner SFTP endpoint.",
        activities=(
            Activity("ExportPartnerCsv", "Copy"),
            Activity("NotifyPartnerSftp", "WebActivity", depends_on=("ExportPartnerCsv",)),
        ),
        inputs=("ds_customer_360",),
        outputs=("ds_partner_extract",),
    ),
    Pipeline(
        name="publish_exec_summary",
        folder="publish",
        description="Builds the executive daily summary from customer 360 and inventory positions.",
        activities=(
            Activity("WaitForInventory", "Validation"),
            Activity("RenderExecSummary", "DatabricksNotebook", depends_on=("WaitForInventory",)),
        ),
        inputs=("ds_customer_360", "ds_inventory_positions"),
        outputs=("ds_exec_summary",),
    ),
    Pipeline(
        name="ops_data_quality_checks",
        folder="ops",
        description="Runs the data quality suite against the curated zone.",
        activities=(Activity("RunDqSuite", "DatabricksNotebook"),),
        inputs=("ds_sales_curated",),
        outputs=(),
    ),
    Pipeline(
        name="maintenance_vacuum_delta",
        folder="ops",
        description="Weekly vacuum and optimize over the curated Delta tables.",
        activities=(Activity("VacuumDeltaTables", "DatabricksNotebook"),),
        inputs=(),
        outputs=(),
    ),
)

PIPELINES_BY_NAME: dict[str, Pipeline] = {pipeline.name: pipeline for pipeline in PIPELINES}


@dataclass
class ActivityRun:
    """One activity run inside a pipeline run."""

    activity_name: str
    activity_type: str
    status: str
    start: datetime
    duration_ms: int
    error: dict[str, Any] | None = None

    def to_api(self, run_id: str) -> dict[str, Any]:
        return {
            "activityRunId": f"{run_id}:{self.activity_name}",
            "activityName": self.activity_name,
            "activityType": self.activity_type,
            "status": self.status,
            "activityRunStart": _iso(self.start),
            "activityRunEnd": _iso(self.start + timedelta(milliseconds=self.duration_ms)),
            "durationInMs": self.duration_ms,
            "errorCode": (self.error or {}).get("errorCode"),
            "error": self.error,
        }


@dataclass
class PipelineRun:
    """One pipeline run and its activity runs."""

    run_id: str
    pipeline: str
    status: str
    start: datetime
    duration_ms: int
    invoked_by: str
    message: str = ""
    activities: list[ActivityRun] = field(default_factory=list)

    def to_api(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "pipelineName": self.pipeline,
            "status": self.status,
            "runStart": _iso(self.start),
            "runEnd": _iso(self.start + timedelta(milliseconds=self.duration_ms)),
            "durationInMs": self.duration_ms,
            "invokedBy": {
                "name": self.invoked_by,
                "invokedByType": _invoked_by_type(self.invoked_by),
            },
            "message": self.message,
        }


def _invoked_by_type(name: str) -> str:
    if name.endswith("_trigger"):
        return "ScheduleTrigger"
    if name == "Manual":
        return "Manual"
    return "PipelineActivity"


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _error(code: str, message: str, target: str, failure_type: str = "UserError") -> dict[str, Any]:
    return {
        "errorCode": code,
        "message": message,
        "failureType": failure_type,
        "target": target,
        "details": [],
    }


# Deterministic per activity durations, so run history is stable on every machine.
_BASE_DURATION_MS: dict[str, int] = {
    "CopySalesFromRestApi": 412_000,
    "ValidateSalesLanding": 9_000,
    "TriggerSalesTransform": 905_000,
    "CopyCrmContacts": 188_000,
    "TriggerCustomer360": 742_000,
    "CopyInventorySftp": 96_000,
    "TriggerInventoryPositions": 221_000,
    "CopyMarketingEvents": 134_000,
    "MergeSalesDelta": 655_000,
    "RefreshSalesStats": 61_000,
    "TriggerSalesPublish": 180_000,
    "TriggerDataQuality": 95_000,
    "WaitForSalesCurated": 12_000,
    "BuildCustomer360": 538_000,
    "TriggerPartnerExtract": 128_000,
    "TriggerExecSummary": 164_000,
    "ComputePositions": 203_000,
    "LoadDashboardMart": 118_000,
    "RefreshSemanticModel": 54_000,
    "ExportPartnerCsv": 97_000,
    "NotifyPartnerSftp": 7_000,
    "WaitForInventory": 11_000,
    "RenderExecSummary": 149_000,
    "RunDqSuite": 88_000,
    "VacuumDeltaTables": 1_240_000,
}

# Scheduled start time of each root pipeline, UTC, on every day it runs.
_SCHEDULE: dict[str, tuple[int, int]] = {
    "ingest_sales_raw": (1, 0),
    "ingest_crm_contacts": (1, 15),
    "ingest_inventory_feed": (1, 30),
    "ingest_marketing_events": (2, 0),
}

_ROOT_TRIGGERS: dict[str, str] = {
    "ingest_sales_raw": "nightly_sales_trigger",
    "ingest_crm_contacts": "nightly_crm_trigger",
    "ingest_inventory_feed": "nightly_inventory_trigger",
    "ingest_marketing_events": "hourly_marketing_trigger",
}


def _duration(activity: str, day_offset: int) -> int:
    """A stable pseudo jitter so durations vary day to day without being random.

    `hash()` is salted per process, so use a fixed digest instead: the fixture has to
    be byte identical on every machine and every run for replay evals to be stable.
    """
    base = _BASE_DURATION_MS.get(activity, 60_000)
    digest = hashlib.sha256(f"{activity}:{day_offset}".encode()).digest()
    jitter_fraction = (digest[0] / 255.0) - 0.5
    return max(1_000, base + int(base * 0.08 * jitter_fraction))


def _run_id(day: int, index: int) -> str:
    return f"3f1a9c20-0e51-4a1b-{day:04d}-7c1f2d0a{index:04d}"


# Which pipeline each ExecutePipeline activity launches, flattened for the builder.
_CHILD_OF: dict[str, list[tuple[str, str]]] = {}
for _pipeline in PIPELINES:
    for _activity in _pipeline.activities:
        if _activity.invokes:
            _CHILD_OF.setdefault(_pipeline.name, []).append((_activity.name, _activity.invokes))


def _build_successful_day(day_offset: int, counter: list[int]) -> list[PipelineRun]:
    """Build a full green day: every root pipeline runs and its children follow."""
    runs: list[PipelineRun] = []
    day = NOW.date() - timedelta(days=day_offset)

    def emit(pipeline_name: str, start: datetime, invoked_by: str) -> datetime:
        pipeline = PIPELINES_BY_NAME[pipeline_name]
        counter[0] += 1
        run = PipelineRun(
            run_id=_run_id(day_offset, counter[0]),
            pipeline=pipeline_name,
            status="Succeeded",
            start=start,
            duration_ms=0,
            invoked_by=invoked_by,
        )
        cursor = start
        for activity in pipeline.activities:
            duration = _duration(activity.name, day_offset)
            run.activities.append(
                ActivityRun(activity.name, activity.type, "Succeeded", cursor, duration)
            )
            if activity.invokes:
                emit(activity.invokes, cursor, f"{pipeline_name}/{activity.name}")
            cursor += timedelta(milliseconds=duration)
        run.duration_ms = int((cursor - start).total_seconds() * 1000)
        runs.append(run)
        return cursor

    for root, (hour, minute) in _SCHEDULE.items():
        emit(
            root,
            datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC),
            _ROOT_TRIGGERS[root],
        )
    return runs


def _build_cascade_day() -> list[PipelineRun]:
    """2026-03-11: one real failure, three misleading downstream symptoms, one unrelated."""
    day = datetime(2026, 3, 11, tzinfo=UTC)
    runs: list[PipelineRun] = []

    sales_start = day.replace(hour=1, minute=0)
    sales = PipelineRun(
        run_id="3f1a9c20-0e51-4a1b-0311-7c1f2d0a0001",
        pipeline="ingest_sales_raw",
        status="Failed",
        start=sales_start,
        duration_ms=1_793_000,
        invoked_by="nightly_sales_trigger",
        message=(
            "Activity CopySalesFromRestApi failed: Failure happened on 'Source' side. "
            "ErrorCode=RestSourceCallFailed"
        ),
        activities=[
            ActivityRun(
                "CopySalesFromRestApi",
                "Copy",
                "Failed",
                sales_start,
                1_793_000,
                _error(
                    "2200",
                    "Failure happened on 'Source' side. ErrorCode=RestSourceCallFailed, "
                    "'Type=Microsoft.DataTransfer.ClientLibrary.RestClient.RestClientException, "
                    "Message=The HttpStatusCode 429 indicates failure. Response content: "
                    '{"error":"too_many_requests","retry_after_seconds":900,'
                    '"detail":"Tenant request quota exhausted for window 00:00-02:00 UTC"}. '
                    "Request url: https://api.vendor-pos.example/v3/transactions?page=37. "
                    "The copy activity retried 4 times over 00:30:00 and exhausted its "
                    "retry policy.',"
                    "Source=Microsoft.DataTransfer.ClientLibrary,'",
                    "CopySalesFromRestApi",
                ),
            ),
            ActivityRun("ValidateSalesLanding", "Validation", "Skipped", sales_start, 0),
            ActivityRun("TriggerSalesTransform", "ExecutePipeline", "Skipped", sales_start, 0),
        ],
    )
    runs.append(sales)

    # The curated transform still runs on its own schedule and fails on missing input.
    clean_start = day.replace(hour=2, minute=0)
    runs.append(
        PipelineRun(
            run_id="3f1a9c20-0e51-4a1b-0311-7c1f2d0a0002",
            pipeline="transform_sales_clean",
            status="Failed",
            start=clean_start,
            duration_ms=96_000,
            invoked_by="nightly_curated_trigger",
            message="Activity MergeSalesDelta failed: ErrorCode=DFExecutorUserError",
            activities=[
                ActivityRun(
                    "MergeSalesDelta",
                    "DatabricksNotebook",
                    "Failed",
                    clean_start,
                    96_000,
                    _error(
                        "3202",
                        "ErrorCode=DFExecutorUserError, Job failed due to reason: "
                        "org.apache.spark.sql.AnalysisException: Path does not exist: "
                        "abfss://landing@contosoanalytics.dfs.core.windows.net/sales/"
                        "ingest_date=2026-03-11/",
                        "MergeSalesDelta",
                    ),
                ),
                ActivityRun(
                    "RefreshSalesStats", "SqlServerStoredProcedure", "Skipped", clean_start, 0
                ),
                ActivityRun("TriggerSalesPublish", "ExecutePipeline", "Skipped", clean_start, 0),
                ActivityRun("TriggerDataQuality", "ExecutePipeline", "Skipped", clean_start, 0),
            ],
        )
    )

    dashboard_start = day.replace(hour=3, minute=0)
    runs.append(
        PipelineRun(
            run_id="3f1a9c20-0e51-4a1b-0311-7c1f2d0a0003",
            pipeline="publish_sales_dashboard",
            status="Failed",
            start=dashboard_start,
            duration_ms=41_000,
            invoked_by="nightly_publish_trigger",
            message="Activity LoadDashboardMart failed: ErrorCode=SqlOperationFailed",
            activities=[
                ActivityRun(
                    "LoadDashboardMart",
                    "Copy",
                    "Failed",
                    dashboard_start,
                    41_000,
                    _error(
                        "2200",
                        "Failure happened on 'Source' side. ErrorCode=SqlOperationFailed, "
                        "'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException, "
                        "Message=A database operation failed. Invalid object name "
                        "'curated.sales_daily_2026_03_11'.,Source=.Net SqlClient Data Provider,"
                        "SqlErrorNumber=208,'",
                        "LoadDashboardMart",
                    ),
                ),
                ActivityRun("RefreshSemanticModel", "WebActivity", "Skipped", dashboard_start, 0),
            ],
        )
    )

    crm_start = day.replace(hour=1, minute=15)
    runs.append(
        PipelineRun(
            run_id="3f1a9c20-0e51-4a1b-0311-7c1f2d0a0004",
            pipeline="ingest_crm_contacts",
            status="Succeeded",
            start=crm_start,
            duration_ms=188_000,
            invoked_by="nightly_crm_trigger",
            activities=[
                ActivityRun("CopyCrmContacts", "Copy", "Succeeded", crm_start, 188_000),
                ActivityRun(
                    "TriggerCustomer360",
                    "ExecutePipeline",
                    "Failed",
                    crm_start + timedelta(milliseconds=188_000),
                    611_000,
                    _error(
                        "3001",
                        "Operation on target TriggerCustomer360 failed: Activity failed because "
                        "an inner activity failed; Inner activity name: BuildCustomer360.",
                        "TriggerCustomer360",
                    ),
                ),
            ],
        )
    )
    # The parent reports Succeeded on the copy but the child pipeline failed, which is
    # exactly the kind of split signal that makes these incidents confusing to triage.
    runs[-1].status = "Failed"
    runs[-1].message = "Operation on target TriggerCustomer360 failed"

    c360_start = crm_start + timedelta(milliseconds=188_000)
    runs.append(
        PipelineRun(
            run_id="3f1a9c20-0e51-4a1b-0311-7c1f2d0a0005",
            pipeline="transform_customer_360",
            status="Failed",
            start=c360_start,
            duration_ms=611_000,
            invoked_by="ingest_crm_contacts/TriggerCustomer360",
            message="Activity BuildCustomer360 failed: ErrorCode=DF-Executor-SourceFileNotFound",
            activities=[
                ActivityRun("WaitForSalesCurated", "Validation", "Succeeded", c360_start, 12_000),
                ActivityRun(
                    "BuildCustomer360",
                    "ExecuteDataFlow",
                    "Failed",
                    c360_start + timedelta(milliseconds=12_000),
                    599_000,
                    _error(
                        "4502",
                        "ErrorCode=DF-Executor-SourceFileNotFound, Data flow source 'SalesCurated' "
                        "could not read any file matching "
                        "'curated/sales/ingest_date=2026-03-11/*.parquet'. "
                        "Check the source settings and the linked service.",
                        "BuildCustomer360",
                    ),
                ),
                ActivityRun(
                    "TriggerPartnerExtract",
                    "ExecutePipeline",
                    "Skipped",
                    c360_start,
                    0,
                ),
                ActivityRun("TriggerExecSummary", "ExecutePipeline", "Skipped", c360_start, 0),
            ],
        )
    )

    # Genuinely unrelated failure the same night: an expired service principal secret.
    marketing_start = day.replace(hour=2, minute=0)
    runs.append(
        PipelineRun(
            run_id="3f1a9c20-0e51-4a1b-0311-7c1f2d0a0006",
            pipeline="ingest_marketing_events",
            status="Failed",
            start=marketing_start,
            duration_ms=22_000,
            invoked_by="hourly_marketing_trigger",
            message="Activity CopyMarketingEvents failed: ErrorCode=UserErrorInvalidCredential",
            activities=[
                ActivityRun(
                    "CopyMarketingEvents",
                    "Copy",
                    "Failed",
                    marketing_start,
                    22_000,
                    _error(
                        "2200",
                        "Failure happened on 'Source' side. ErrorCode=UserErrorInvalidCredential, "
                        "'Type=Microsoft.DataTransfer.Common.Shared.HybridDeliveryException, "
                        "Message=The client secret for application "
                        "'sp-marketing-ingest' expired on 2026-03-10T23:59:00Z. "
                        "Rotate the secret in the linked service.,'",
                        "CopyMarketingEvents",
                    ),
                ),
            ],
        )
    )

    inventory_start = day.replace(hour=1, minute=30)
    runs.append(
        PipelineRun(
            run_id="3f1a9c20-0e51-4a1b-0311-7c1f2d0a0007",
            pipeline="ingest_inventory_feed",
            status="Succeeded",
            start=inventory_start,
            duration_ms=317_000,
            invoked_by="nightly_inventory_trigger",
            activities=[
                ActivityRun("CopyInventorySftp", "Copy", "Succeeded", inventory_start, 96_000),
                ActivityRun(
                    "TriggerInventoryPositions",
                    "ExecutePipeline",
                    "Succeeded",
                    inventory_start + timedelta(milliseconds=96_000),
                    221_000,
                ),
            ],
        )
    )
    positions_start = inventory_start + timedelta(milliseconds=96_000)
    runs.append(
        PipelineRun(
            run_id="3f1a9c20-0e51-4a1b-0311-7c1f2d0a0008",
            pipeline="transform_inventory_positions",
            status="Succeeded",
            start=positions_start,
            duration_ms=203_000,
            invoked_by="ingest_inventory_feed/TriggerInventoryPositions",
            activities=[
                ActivityRun(
                    "ComputePositions", "ExecuteDataFlow", "Succeeded", positions_start, 203_000
                )
            ],
        )
    )
    return runs


def _build_maintenance_failure() -> PipelineRun:
    """An older, unrelated failure so 'what failed recently' is not a one answer question."""
    start = datetime(2026, 3, 9, 4, 0, tzinfo=UTC)
    return PipelineRun(
        run_id="3f1a9c20-0e51-4a1b-0309-7c1f2d0a0099",
        pipeline="maintenance_vacuum_delta",
        status="Failed",
        start=start,
        duration_ms=7_200_000,
        invoked_by="weekly_maintenance_trigger",
        message="Activity VacuumDeltaTables failed: ErrorCode=UserErrorActivityTimedOut",
        activities=[
            ActivityRun(
                "VacuumDeltaTables",
                "DatabricksNotebook",
                "TimedOut",
                start,
                7_200_000,
                _error(
                    "3204",
                    "ErrorCode=UserErrorActivityTimedOut, Activity exceeded its configured "
                    "timeout of 02:00:00 while vacuuming 41 Delta tables.",
                    "VacuumDeltaTables",
                    failure_type="UserError",
                ),
            )
        ],
    )


def _build_recovery_run() -> list[PipelineRun]:
    """2026-03-12: a manual rerun of the sales ingest succeeds, confirming the 429 was transient."""
    start = datetime(2026, 3, 12, 7, 30, tzinfo=UTC)
    cursor = start
    activities: list[ActivityRun] = []
    for activity in PIPELINES_BY_NAME["ingest_sales_raw"].activities:
        duration = _duration(activity.name, 0)
        activities.append(ActivityRun(activity.name, activity.type, "Succeeded", cursor, duration))
        cursor += timedelta(milliseconds=duration)
    return [
        PipelineRun(
            run_id="3f1a9c20-0e51-4a1b-0312-7c1f2d0a0001",
            pipeline="ingest_sales_raw",
            status="Succeeded",
            start=start,
            duration_ms=int((cursor - start).total_seconds() * 1000),
            invoked_by="Manual",
            message="Rerun after the vendor API quota window reset.",
            activities=activities,
        )
    ]


def _build_runs() -> list[PipelineRun]:
    counter = [100]
    runs: list[PipelineRun] = []
    for day_offset in (5, 4, 3):
        runs.extend(_build_successful_day(day_offset, counter))
    runs.append(_build_maintenance_failure())
    runs.extend(_build_cascade_day())
    runs.extend(_build_recovery_run())
    return sorted(runs, key=lambda run: run.start, reverse=True)


RUNS: list[PipelineRun] = _build_runs()
RUNS_BY_ID: dict[str, PipelineRun] = {run.run_id: run for run in RUNS}
