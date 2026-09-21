# SPDX-License-Identifier: LGPL-2.1-or-later
"""Execution-report DTOs and the checked boundary used by report consumers.

Optional fields support reports written while a run is still in progress. Their
presence does not establish coverage eligibility; coverage_report checks that.
"""

import math
from typing import TypedDict

from catalogue_schema import GapBehavior, parse_gap
from fixture_manifest import FixtureManifest, parse_fixture
from json_validation import JSONValue, ValidationError, integer
from typed_json import parse_typed as parse_typed


class Definition(TypedDict):
    schema: int
    fingerprint: str
    files: dict[str, str]
    policy_sha256: str
    loader_sha256: str
    reference_commit: str


class CaseIdentity(TypedDict):
    behavior_id: str
    driver: str
    profile: str


class RepositoryRequest(TypedDict):
    path: str
    version: str
    blocked: bool


class SideloadNetworkObservation(TypedDict):
    requests: list[RepositoryRequest]


class QueryNetworkObservation(SideloadNetworkObservation):
    cached_query_requests: int
    uncached_query_requests: int


class SideloadImageNetworkObservation(SideloadNetworkObservation):
    remote_contains_images: bool


class EvidenceRecord(TypedDict, total=False):
    argv: list[str]
    cli_argv: list[str]
    interface: str
    exit_status: int
    stdout: str
    stderr: str
    api_calls: list[str]
    signals: list[str]
    observation: str
    data: JSONValue
    error: str
    timed_out: bool
    role: str
    mode: str
    xdg_data_home: str
    cleanup_confirmed: bool
    query_network_observation: QueryNetworkObservation
    sideload_image_network_observation: SideloadImageNetworkObservation
    sideload_network_observation: SideloadNetworkObservation


class _CaseStatus(CaseIdentity):
    status: str


class CaseTimings(TypedDict):
    setup_seconds: float
    execution_seconds: float
    cleanup_seconds: float


class CaseResult(_CaseStatus, total=False):
    duration_seconds: float
    timings: CaseTimings
    evidence: list[EvidenceRecord]
    cleanup_complete: bool
    cleanup_error: str
    error: str
    target_version: str | None
    required_capabilities: list[str]
    unsupported_capabilities: dict[str, str]
    state_directory: str
    repository_requests: list[RepositoryRequest]


class ArtifactProvenance(TypedDict, total=False):
    path: str
    sha256: str


class TargetProvenance(TypedDict, total=False):
    configuration_sha256: str
    cli_path: str
    cli_sha256: str
    adapter_files: list[ArtifactProvenance]


class FixtureProvenance(TypedDict, total=False):
    path: str
    manifest_sha256: str


class LibraryProvenance(ArtifactProvenance, total=False):
    package_version: str
    client_sha256: str


class ArtifactIntegrity(TypedDict, total=False):
    status: str
    errors: list[str]
    changed_paths: list[str]


class _ReportSchema(TypedDict):
    schema: int


class RunReport(_ReportSchema, total=False):
    duration_seconds: float
    results: list[CaseResult]
    coverage_definition: Definition
    complete: bool
    target: str
    target_configuration: str
    target_version: str
    started_at: str
    finished_at: str
    target_provenance: TargetProvenance
    library_provenance: LibraryProvenance
    fixture_provenance: FixtureProvenance
    artifact_integrity: ArtifactIntegrity
    declared_unsupported_capabilities: dict[str, str]
    setup_evidence: list[EvidenceRecord]
    setup_error: str
    setup_status: str
    full_compatibility: bool
    fixture: FixtureManifest
    gaps: list[GapBehavior]
    coverage: "CoverageSummary"


class CoverageMetric(TypedDict):
    total: int
    implemented: int
    implemented_percent: float | None
    passed: int | None
    passed_percent: float | None


class Verification(TypedDict):
    status: str
    reason: str


class CoverageMetrics(TypedDict):
    behaviors: dict[str, CoverageMetric]
    surfaces: dict[str, CoverageMetric]
    profiles: dict[str, dict[str, CoverageMetric]]
    categories: dict[str, dict[str, CoverageMetric]]


class CLIOptionAccounting(TypedDict):
    equivalence_checks: CoverageMetric
    accounted: CoverageMetric
    equivalence_evidence: dict[str, list[CaseIdentity]]


class _CoverageSummaryRequired(TypedDict):
    schema: int
    definition: Definition
    verification: Verification
    metrics: CoverageMetrics
    case_statuses: dict[str, int]
    evidence: dict[str, list[CaseIdentity]]
    interface_evidence: dict[str, list[CaseIdentity]]
    requirement_capabilities: dict[str, list[str]]
    all_possible_behavior_percent: None
    recorded_execution: dict[str, JSONValue] | None
    surfaces_without_catalogued_requirements: list[str]
    unimplemented_requirements: list[str]
    unverified_requirements: list[str] | None
    limitations: list[str]


class CoverageSummary(_CoverageSummaryRequired, total=False):
    cli_option_accounting: CLIOptionAccounting


def _check_observations(evidence: list[EvidenceRecord], path: str) -> None:
    for index, record in enumerate(evidence):
        if "query_network_observation" in record:
            observation = record["query_network_observation"]
            prefix = f"{path}[{index}].query_network_observation"
            integer(observation["cached_query_requests"],
                    f"{prefix}.cached_query_requests", minimum=0)
            integer(observation["uncached_query_requests"],
                    f"{prefix}.uncached_query_requests", minimum=0)


def parse_report(value: object, path: str = "report") -> RunReport:
    """Validate all present report fields before returning a detached typed DTO."""
    report = parse_typed(value, RunReport, path)
    if "duration_seconds" in report:
        _seconds(report["duration_seconds"], f"{path}.duration_seconds")
    if "fixture" in report:
        report["fixture"] = parse_fixture(report["fixture"], f"{path}.fixture")
    if "gaps" in report:
        report["gaps"] = [parse_gap(gap, f"{path}.gaps[{index}]")
                          for index, gap in enumerate(report["gaps"])]
    _check_observations(report.get("setup_evidence", []), f"{path}.setup_evidence")
    for index, result in enumerate(report.get("results", [])):
        prefix = f"{path}.results[{index}]"
        if "duration_seconds" in result:
            _seconds(result["duration_seconds"], f"{prefix}.duration_seconds")
        for key, value in result.get("timings", {}).items():
            _seconds(value, f"{prefix}.timings.{key}")
        _check_observations(result.get("evidence", []), f"{path}.results[{index}].evidence")
    return report


def _seconds(value: object, path: str) -> None:
    if type(value) not in (int, float) or not isinstance(value, (int, float)):
        raise ValidationError(f"{path}: expected finite nonnegative seconds")
    try:
        valid = math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValidationError(f"{path}: expected finite nonnegative seconds")
