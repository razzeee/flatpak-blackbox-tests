# SPDX-License-Identifier: LGPL-2.1-or-later
"""Report source-interface reach and coverage of explicitly catalogued behavior."""

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import scenario_catalogue
from catalogue_schema import (
    ExecutableBehavior,
    Requirement,
    executable_behavior,
    indexed,
    load_requirements,
    parse_catalogue,
)
from json_validation import json_value, load_json
from report_schema import (
    CaseIdentity,
    CaseResult,
    CoverageMetric,
    CoverageMetrics,
    CoverageSummary,
    Definition,
    RunReport,
    Verification,
    parse_report,
)
from scenario_catalogue import load_behaviors, load_mappings

KINDS = ("cli-command", "cli-option", "library-function", "library-signal")
STATUSES = {"passed", "failed", "unmet-prerequisite", "unsupported", "setup-error", "not-selected"}
POLICY = [
    ("Behavior percentages apply only to the curated obligations, "
     "not all possible Flatpak behavior."),
    ("Interface reach means at least one directly related assertion, "
     "not complete coverage of an interface."),
    ("Mapped requirements are implemented coverage; "
     "only complete passing cases provide run evidence."),
    ("Repeated evidence is counted once. Failed, unselected, unsupported "
     "and system cases do not shrink denominators."),
    ("User evidence cannot cover system obligations. "
     "Profile 'any' does not mean both profiles were tested."),
    ("Setup calls, fixture preparation, option presence and logged signals "
     "receive no automatic credit."),
    ("Verification applies to the recorded target and fixture, "
     "not other versions or implementations."),
    ("Current suite hashes are checked; reference-source drift is checked "
     "separately by catalogue.py --check."),
    ("Verified function reach also requires a call-stage trace from the library client. "
     "An early error cannot credit an unreached function."),
]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(json_value(value), indent=2) + "\n")
    temporary.replace(path)


def case_key(case: CaseIdentity) -> tuple[str, str, str]:
    return case["behavior_id"], case["driver"], case["profile"]


def percentage(count: int, total: int) -> float | None:
    return round(count * 100 / total, 2) if total else None


def metric(universe: set[str], implemented: set[str], passed: set[str] | None) -> CoverageMetric:
    total = len(universe)
    implemented_count = len(universe & implemented)
    passed_count = len(universe & passed) if passed is not None else None
    return {
        "total": total, "implemented": implemented_count,
        "implemented_percent": percentage(implemented_count, total),
        "passed": passed_count,
        "passed_percent": percentage(passed_count, total) if passed_count is not None else None,
    }


def subject_problem(report: RunReport, results: list[CaseResult]) -> str | None:
    """Require inspectable attribution and command evidence before granting credit."""
    passing = [result for result in results if result["status"] == "passed"]
    if not passing:
        return None

    def text(value: object) -> bool:
        return isinstance(value, str) and bool(value)

    def sha256(value: object) -> bool:
        return isinstance(value, str) and len(value) == 64 and set(value) <= set("0123456789abcdef")

    for field in ("target", "target_version", "started_at", "finished_at"):
        if not text(report.get(field)):
            return f"Passing report lacks {field}."
    target = report.get("target_provenance")
    if not isinstance(target, dict) or not text(target.get("cli_path")) or not all(
        sha256(target.get(field)) for field in ("configuration_sha256", "cli_sha256")
    ):
        return "Passing report lacks selected target provenance."
    adapters = target.get("adapter_files")
    if not isinstance(adapters, list) or not adapters or not all(
        isinstance(item, dict) and text(item.get("path")) and sha256(item.get("sha256"))
        for item in adapters
    ):
        return "Passing report lacks adapter provenance."
    fixture = report.get("fixture_provenance")
    if not isinstance(fixture, dict) or not text(fixture.get("path")) or not sha256(
        fixture.get("manifest_sha256")
    ):
        return "Passing report lacks fixture provenance."
    if any(result["driver"] == "library" for result in passing):
        library = report.get("library_provenance")
        if not isinstance(library, dict) or not text(library.get("path")) or not text(
            library.get("package_version")
        ) or not all(sha256(library.get(field)) for field in ("sha256", "client_sha256")):
            return "Passing library cases lack selected library/client provenance."
    integrity = report.get("artifact_integrity")
    if not isinstance(integrity, dict) or integrity.get("status") != "verified":
        return "Selected artifacts were not verified unchanged at completion."
    for result in passing:
        commands = result.get("evidence")
        if not isinstance(commands, list) or not commands:
            return f"Passing case has no command evidence: {case_key(result)}"
        for command in commands:
            if not isinstance(command, dict):
                return "Malformed command evidence."
            if "observation" in command:
                if not text(command["observation"]) or "data" not in command or (
                    "argv" in command or "interface" in command
                ):
                    return "Malformed supplemental observation."
                continue
            argv = command.get("argv")
            if not isinstance(argv, list) or not argv or not text(argv[0]) or not all(
                isinstance(arg, str) for arg in argv
            ):
                return "Command evidence lacks arguments."
            if type(command.get("exit_status")) is not int or not all(
                isinstance(command.get(stream), str) for stream in ("stdout", "stderr")
            ):
                return "Command evidence lacks its result."
            if command.get("interface") == "library":
                calls = command.get("api_calls")
                if not isinstance(calls, list) or not all(text(name) for name in calls):
                    return "Library command evidence lacks a call-stage trace."
                signals = command.get("signals")
                if not isinstance(signals, list) or not all(text(name) for name in signals):
                    return "Library command evidence lacks signal-emission accounting."
        if not any(command.get("interface") == result["driver"] for command in commands):
            return "Passing case has no evidence at its declared interface."
    return None


class CoverageModel:
    def __init__(self, suite: Path) -> None:
        self.suite = suite.resolve()
        catalogue_path = self.suite / "coverage-data/surfaces.json"
        self.catalogue = parse_catalogue(load_json(catalogue_path), str(catalogue_path))
        self.surfaces = indexed(self.catalogue["surfaces"], "surface")
        for surface in self.surfaces.values():
            if surface["kind"] not in KINDS:
                raise ValueError(f"unknown surface kind: {surface['kind']}")
        self.limitations = [*POLICY, *self.catalogue["limitations"]]
        requirements: list[Requirement] = []
        for interface in ("cli", "library"):
            path = self.suite / f"coverage-data/{interface}-requirements.json"
            document = load_requirements(path)
            if document["scope"] != interface:
                raise ValueError("requirement file has incorrect interface scope")
            self.limitations.extend(document["limitations"])
            for requirement in document["requirements"]:
                if requirement["interface"] != interface or requirement["profile"] not in (
                    "user", "system", "any"
                ):
                    raise ValueError(f"invalid interface/profile for {requirement['id']}")
                if not requirement["description"] or not requirement["sources"]:
                    raise ValueError(f"requirement lacks contract/source: {requirement['id']}")
                capabilities = requirement["required_capabilities"]
                if not isinstance(capabilities, list) or not capabilities or not all(
                    isinstance(capability, str) and capability for capability in capabilities
                ) or len(set(capabilities)) != len(capabilities):
                    raise ValueError(f"invalid requirement capabilities: {requirement['id']}")
                if not requirement["surfaces"]:
                    raise ValueError(f"requirement lacks interface references: {requirement['id']}")
                for surface_id in requirement["surfaces"]:
                    if surface_id not in self.surfaces:
                        raise ValueError(f"unknown surface {surface_id} in {requirement['id']}")
                    if not self.surfaces[surface_id]["kind"].startswith(interface + "-"):
                        raise ValueError(f"cross-interface surface reference: {requirement['id']}")
                requirements.append(requirement)
        self.requirements = indexed(requirements, "requirement")
        self.cases: dict[tuple[str, str, str], ExecutableBehavior] = {}
        for behavior in indexed(load_behaviors(self.suite), "behavior").values():
            if "scenario" not in behavior:
                continue
            if behavior["profile"] not in ("user", "system", "any"):
                raise ValueError(f"invalid case profile: {behavior['profile']}")
            for driver in behavior["drivers"]:
                key = (behavior["id"], driver, behavior["profile"])
                if key in self.cases or driver not in ("cli", "library"):
                    raise ValueError(f"invalid or duplicate case: {key}")
                self.cases[key] = executable_behavior(behavior)
        self.mapping: dict[tuple[str, str, str], set[str]] = {}
        self.option_assertions: dict[tuple[str, str, str], set[str]] = {}
        mappings = load_mappings(self.suite)
        for mapping in mappings:
            key = (mapping["behavior_id"], mapping["driver"], mapping["profile"])
            if key not in self.cases or key in self.mapping:
                raise ValueError(f"unknown or duplicate coverage case: {key}")
            if not mapping["rationale"]:
                raise ValueError(f"coverage mapping needs an assertion rationale: {key}")
            ids = mapping["requirements"]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate requirement in coverage mapping: {key}")
            for identifier in ids:
                if identifier not in self.requirements:
                    raise ValueError(f"unknown mapped requirement: {identifier}")
                requirement = self.requirements[identifier]
                if requirement["interface"] != key[1] or (
                    requirement["profile"] not in ("any", key[2])
                ):
                    raise ValueError(
                        f"mapping cannot cover interface/profile: {identifier} from {key}"
                    )
            self.mapping[key] = set(ids)
            options = set()
            for assertion in mapping.get("surface_assertions", []):
                identifier = assertion["id"]
                if key[1] != "cli" or identifier not in self.surfaces or (
                    self.surfaces[identifier]["kind"] != "cli-option"
                ) or not assertion.get("rationale") or identifier in options:
                    raise ValueError(f"invalid explicit option assertion: {identifier} from {key}")
                options.add(identifier)
            self.option_assertions[key] = options
        self.definition = self.snapshot()

    def snapshot(self) -> Definition:
        paths = [self.suite / "inventory.json"]
        paths += sorted((self.suite / "coverage-data").rglob("*.json"))
        paths += sorted((self.suite / "scenario-data").rglob("*.json"))
        paths += sorted(
            path for pattern in ("*.py", "*.c", "*.h") for path in self.suite.glob(pattern)
            if path.suffix != ".py" or not path.name.startswith("test_")
        )
        for case in self.cases.values():
            if "handler" in case:
                module, _ = case["handler"].split(":")
                paths.append(self.suite / (module.replace(".", "/") + ".py"))
        files = {str(path.relative_to(self.suite)): digest(path.read_bytes())
                 for path in sorted(set(paths))}
        # The reporting policy is part of the definition even with --suite pointing
        # at a separate package or a small public-CLI test fixture.
        policy_hash = digest(Path(__file__).read_bytes())
        loader_hash = digest(Path(scenario_catalogue.__file__).read_bytes())
        fingerprint = digest(json.dumps(
            {"files": files, "policy": policy_hash, "loader": loader_hash}, sort_keys=True,
        ).encode())
        return {"schema": 1, "fingerprint": fingerprint, "files": files,
                "policy_sha256": policy_hash,
                "loader_sha256": loader_hash,
                "reference_commit": self.catalogue["reference"]["commit"]}

    def summarize(self, report: object | None = None) -> CoverageSummary:
        report = parse_report(report) if report is not None else None
        verification: Verification = {
            "status": "not-run", "reason": "No execution report supplied.",
        }
        passed: set[str] | None = None
        passed_surfaces: set[str] | None = None
        result_statuses: Counter[str] = Counter()
        evidence: dict[str, list[CaseIdentity]] = {}
        interface_evidence: dict[str, list[CaseIdentity]] = {}
        if report is not None:
            if "coverage_definition" not in report:
                verification = {
                    "status": "unversioned", "reason": "Report has no definition hashes.",
                }
            elif report["coverage_definition"] != self.definition or (
                self.snapshot() != self.definition
            ):
                verification = {
                    "status": "stale",
                    "reason": "Report does not match current suite/catalogue definitions.",
                }
            elif report.get("complete") is not True:
                verification = {
                    "status": "incomplete",
                    "reason": "Run did not complete; no verified credit assigned.",
                }
            else:
                results = report.get("results", [])
                keys = [case_key(result) for result in results]
                if len(set(keys)) != len(keys) or set(keys) != set(self.cases):
                    verification = {
                        "status": "invalid",
                        "reason": "Report has missing, duplicate or unknown cases.",
                    }
                elif any(result["status"] not in STATUSES or
                         (result["status"] == "passed" and
                          (result.get("cleanup_error") or
                           result.get("cleanup_complete") is not True))
                         for result in results):
                    verification = {
                        "status": "invalid",
                        "reason": "Report contains unfinished cases or unconfirmed cleanup.",
                    }
                elif problem := subject_problem(report, results):
                    verification = {"status": "invalid", "reason": problem}
                else:
                    verification = {
                        "status": "current",
                        "reason": "Complete report matches current definitions.",
                    }
                    passed = set()
                    passed_surfaces = set()
                    for result in results:
                        result_statuses[result["status"]] += 1
                        if result["status"] != "passed":
                            continue
                        credited = set(self.option_assertions.get(case_key(result), set()))
                        observed_functions = {
                            f"library.function.{name}" for command in result.get("evidence", [])
                            if command.get("interface") == "library"
                            for name in command.get("api_calls", [])
                        }
                        observed_signals = {
                            f"library.signal.{name}" for command in result.get("evidence", [])
                            if command.get("interface") == "library"
                            for name in command.get("signals", [])
                        }
                        for identifier in self.mapping.get(case_key(result), set()):
                            passed.add(identifier)
                            evidence.setdefault(identifier, []).append({
                                    "behavior_id": result["behavior_id"],
                                    "driver": result["driver"], "profile": result["profile"],
                            })
                            for surface in self.requirements[identifier]["surfaces"]:
                                kind = self.surfaces[surface]["kind"]
                                if kind == "library-function" and surface not in observed_functions:
                                    continue
                                if kind == "library-signal" and surface not in observed_signals:
                                    continue
                                credited.add(surface)
                        passed_surfaces.update(credited)
                        for surface in sorted(credited):
                            interface_evidence.setdefault(surface, []).append({
                                "behavior_id": result["behavior_id"],
                                "driver": result["driver"], "profile": result["profile"],
                            })
        implemented = set().union(*self.mapping.values()) if self.mapping else set()
        reached = {surface for identifier in implemented
                   for surface in self.requirements[identifier]["surfaces"]}
        if self.option_assertions:
            reached.update(set().union(*self.option_assertions.values()))
        metrics: CoverageMetrics = {
            "behaviors": {interface: metric(
                {key for key, item in self.requirements.items() if item["interface"] == interface},
                implemented, passed,
            ) for interface in ("cli", "library")},
            "surfaces": {kind: metric(
                {key for key, item in self.surfaces.items() if item["kind"] == kind},
                reached, passed_surfaces,
            ) for kind in KINDS},
            "profiles": {interface: {profile: metric(
                {key for key, item in self.requirements.items()
                 if item["interface"] == interface and item["profile"] == profile},
                implemented, passed,
            ) for profile in ("user", "system", "any")} for interface in ("cli", "library")},
            "categories": {interface: {category: metric(
                {key for key, item in self.requirements.items()
                 if item["interface"] == interface and item["category"] == category},
                implemented, passed,
            ) for category in sorted({item["category"] for item in self.requirements.values()
                                      if item["interface"] == interface})}
                for interface in ("cli", "library")},
        }
        return {"schema": 1, "definition": self.definition, "verification": verification,
                "metrics": metrics, "case_statuses": dict(result_statuses),
                "evidence": evidence,
                "interface_evidence": interface_evidence,
                "requirement_capabilities": {
                    identifier: requirement["required_capabilities"]
                    for identifier, requirement in self.requirements.items()
                },
                "all_possible_behavior_percent": None,
                "recorded_execution": None if report is None else {
                    key: json_value(report.get(key)) for key in (
                        "target", "target_version", "target_provenance", "library_provenance",
                        "started_at", "finished_at", "declared_unsupported_capabilities",
                    )
                },
                "surfaces_without_catalogued_requirements": sorted(set(self.surfaces) - {
                    surface for requirement in self.requirements.values()
                    for surface in requirement["surfaces"]
                }),
                "unimplemented_requirements": sorted(set(self.requirements) - implemented),
                "unverified_requirements": None if passed is None else sorted(
                    set(self.requirements) - passed
                ),
                "limitations": self.limitations}


def format_summary(summary: CoverageSummary) -> str:
    lines = ["# Black-box coverage", "", f"Evidence: {summary['verification']['status']}.",
             summary["verification"].get("reason", "")]
    execution = summary["recorded_execution"]
    if execution:
        lines.append(
            f"Recorded target: {execution.get('target')} ({execution.get('target_version')})."
        )
    if summary["case_statuses"]:
        lines.append("Cases: " + ", ".join(f"{count} {status}" for status, count
                                          in sorted(summary["case_statuses"].items())) + ".")
    lines += ["",
             "Percentages describe the stated denominators, not all possible behavior.", "",
             "| Denominator | Implemented | Passing evidence |", "| --- | ---: | ---: |"]
    labels = {
        "cli": "CLI catalogued behavior obligations",
        "library": "Library catalogued behavior obligations",
        "cli-command": "CLI commands with assertion evidence",
        "cli-option": "Documented CLI long options with assertion evidence",
        "library-function": "Public library functions with assertion evidence",
        "library-signal": "Public library signals with assertion evidence",
    }
    for group in (summary["metrics"]["behaviors"], summary["metrics"]["surfaces"]):
        for name, values in group.items():
            total = values["total"]
            implemented = "0/0 (n/a)" if not total else (
                f"{values['implemented']}/{total} ({values['implemented_percent']:.2f}%)"
            )
            passed = "unverified" if values["passed"] is None else (
                "0/0 (n/a)" if not total else
                f"{values['passed']}/{total} ({values['passed_percent']:.2f}%)"
            )
            lines.append(f"| {labels[name]} | {implemented} | {passed} |")
    lines += ["", f"Reference source commit: `{summary['definition']['reference_commit']}`.",
              "Source drift is checked separately with `catalogue.py --check`.",
              "No percentage of all possible behavior is inferred from these counts."]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=Path(__file__).parent)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--json", action="store_true", help="emit full machine-readable accounting")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        model = CoverageModel(args.suite)
        report = load_json(args.report) if args.report else None
        summary = model.summarize(report)
        text = json.dumps(summary, indent=2) + "\n" if args.json else format_summary(summary)
        if args.output:
            if args.json:
                write_json(args.output, summary)
            else:
                args.output.write_text(text)
        else:
            print(text, end="")
        return 0 if summary["verification"]["status"] in ("not-run", "current") else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"coverage: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
