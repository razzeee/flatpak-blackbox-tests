# SPDX-License-Identifier: LGPL-2.1-or-later
"""Check coverage accounting through its public reporting CLI."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from json_validation import JSONValue, object_map
from report_schema import EvidenceRecord, RunReport, parse_report

SCRIPT = Path(__file__).with_name("coverage_report.py")


class CoverageReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="coverage-accounting-")
        self.addCleanup(self.temporary.cleanup)
        self.suite = Path(self.temporary.name)
        (self.suite / "coverage-data").mkdir()
        (self.suite / "run.py").write_text("# test runner definition\n")
        (self.suite / "client.c").write_text("/* test client definition */\n")
        self.write("coverage-data/surfaces.json", {
            "schema": 1, "reference": {"commit": "reference", "sources": {}},
            "limitations": ["A test denominator."],
            "surfaces": [
                {"id": "cli.command.install", "kind": "cli-command", "name": "install"},
                {"id": "cli.command.update", "kind": "cli-command", "name": "update"},
                {"id": "library.function.install", "kind": "library-function", "name": "install"},
            ],
        })
        self.write("coverage-data/cli-requirements.json", {
            "schema": 1, "scope": "cli", "limitations": ["Not exhaustive."],
            "requirements": [
                self.requirement("cli.install", "cli", "user", "cli.command.install"),
                self.requirement("cli.update", "cli", "user", "cli.command.update"),
                self.requirement("cli.system", "cli", "system", "cli.command.install"),
            ],
        })
        self.write("coverage-data/library-requirements.json", {
            "schema": 1, "scope": "library", "limitations": ["Not exhaustive."],
            "requirements": [
                self.requirement("library.install", "library", "user", "library.function.install"),
            ],
        })
        self.write("inventory.json", {"schema": 1, "behaviors": [
            {"id": "first", "scenario": "first", "profile": "user", "drivers": ["cli", "library"]},
            {"id": "second", "scenario": "second", "profile": "user", "drivers": ["cli"]},
        ]})
        self.write("coverage-data/mapping.json", {"schema": 1, "cases": [
            {"behavior_id": "first", "driver": "cli", "profile": "user",
             "requirements": ["cli.install"], "rationale": "Assert installed state."},
            {"behavior_id": "second", "driver": "cli", "profile": "user",
             "requirements": ["cli.install", "cli.update"], "rationale": "Assert both states."},
            {"behavior_id": "first", "driver": "library", "profile": "user",
             "requirements": ["library.install"], "rationale": "Assert installed state."},
        ]})

    @staticmethod
    def requirement(identifier: str, interface: str, profile: str,
                    surface: str) -> dict[str, JSONValue]:
        return {"id": identifier, "interface": interface, "profile": profile,
                "category": "lifecycle", "description": "Observable test requirement.",
                "required_capabilities": ["cli" if interface == "cli" else "libflatpak"],
                "sources": [{"path": "doc/test.xml", "anchor": "Description"}],
                "surfaces": [surface]}

    def write(self, path: str, value: object) -> None:
        (self.suite / path).write_text(json.dumps(value))

    def command(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(SCRIPT), "--suite", str(self.suite),
                               "--json", *arguments], text=True, capture_output=True, check=False)

    def test_mapped_requirements_are_not_verified_without_a_run(self) -> None:
        result = self.command()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        cli = output["metrics"]["behaviors"]["cli"]
        self.assertEqual(cli["total"], 3)
        self.assertEqual(cli["implemented"], 2)
        self.assertEqual(cli["implemented_percent"], 66.67)
        self.assertIsNone(cli["passed"])
        self.assertIsNone(cli["passed_percent"])
        self.assertEqual(output["verification"]["status"], "not-run")

    def execution_report(self, statuses: tuple[str, str, str]) -> RunReport:
        definition = json.loads(self.command().stdout)["definition"]
        return parse_report({"schema": 1, "complete": True, "coverage_definition": definition,
                "target": "synthetic target", "target_version": "test 1.0",
                "started_at": "2026-09-14T00:00:00+00:00",
                "finished_at": "2026-09-14T00:00:01+00:00",
                "target_provenance": {
                    "configuration_sha256": "0" * 64, "cli_path": "/synthetic/cli",
                    "cli_sha256": "1" * 64,
                    "adapter_files": [{"path": "/synthetic/adapter", "sha256": "2" * 64}],
                },
                "library_provenance": {"path": "/synthetic/lib", "sha256": "3" * 64,
                                       "client_sha256": "4" * 64, "package_version": "test 1.0"},
                "fixture_provenance": {"path": "/synthetic/fixtures", "manifest_sha256": "5" * 64},
                "artifact_integrity": {"status": "verified"},
                "results": [
                    {"behavior_id": behavior, "driver": driver, "profile": "user", "status": status,
                     "cleanup_complete": True, "evidence": [{
                         "argv": ["/synthetic/client", behavior], "interface": driver,
                         "api_calls": ["install"] if driver == "library" else [],
                         "signals": [],
                         "exit_status": 0, "stdout": "", "stderr": "",
                     }]}
                    for (behavior, driver), status in zip(
                        (("first", "cli"), ("second", "cli"), ("first", "library")), statuses,
                        strict=True,
                    )
                ]})

    def test_passing_evidence_is_deduplicated_and_system_stays_uncovered(self) -> None:
        self.write("run.json", self.execution_report(("passed", "passed", "passed")))
        result = self.command("--report", str(self.suite / "run.json"))
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["verification"]["status"], "current")
        self.assertEqual(output["metrics"]["behaviors"]["cli"]["passed"], 2)
        self.assertEqual(output["metrics"]["behaviors"]["cli"]["passed_percent"], 66.67)
        self.assertEqual(output["metrics"]["profiles"]["cli"]["system"]["total"], 1)
        self.assertEqual(output["metrics"]["profiles"]["cli"]["system"]["passed"], 0)
        self.assertEqual(output["metrics"]["surfaces"]["cli-command"]["passed"], 2)

    def test_filtered_failed_and_unsupported_cases_do_not_shrink_denominators(self) -> None:
        statuses = ("not-selected", "failed", "unsupported", "setup-error", "unmet-prerequisite")
        for status in statuses:
            with self.subTest(status=status):
                self.write("run.json", self.execution_report(("passed", status, "unsupported")))
                result = self.command("--report", str(self.suite / "run.json"))
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)
                self.assertEqual(output["metrics"]["behaviors"]["cli"]["total"], 3)
                self.assertEqual(output["metrics"]["behaviors"]["cli"]["passed_percent"], 33.33)
                self.assertEqual(output["metrics"]["behaviors"]["library"]["passed_percent"], 0)
                self.assertEqual(output["metrics"]["surfaces"]["library-signal"]["total"], 0)
                self.assertIsNone(output["metrics"]["surfaces"]["library-signal"]["passed_percent"])

    def test_stale_assertions_and_catalogue_receive_no_verified_credit(self) -> None:
        for path in ("run.py", "client.c", "coverage-data/cli-requirements.json",
                     "coverage-data/mapping.json", "coverage-data/surfaces.json"):
            with self.subTest(path=path):
                self.write("run.json", self.execution_report(("passed", "passed", "passed")))
                file = self.suite / path
                original = file.read_text()
                file.write_text(original + "\n")
                result = self.command("--report", str(self.suite / "run.json"))
                self.assertEqual(result.returncode, 1)
                output = json.loads(result.stdout)
                self.assertEqual(output["verification"]["status"], "stale")
                self.assertIsNone(output["metrics"]["behaviors"]["cli"]["passed"])
                file.write_text(original)

    def test_incomplete_and_unversioned_reports_receive_no_credit(self) -> None:
        for state in ("incomplete", "unversioned"):
            with self.subTest(state=state):
                report = self.execution_report(("passed", "passed", "passed"))
                if state == "incomplete":
                    report["complete"] = False
                else:
                    del report["coverage_definition"]
                self.write("run.json", report)
                result = self.command("--report", str(self.suite / "run.json"))
                self.assertEqual(result.returncode, 1)
                output = json.loads(result.stdout)
                self.assertEqual(output["verification"]["status"], state)
                self.assertIsNone(output["metrics"]["surfaces"]["cli-command"]["passed"])

    def test_missing_duplicate_unknown_and_unfinished_results_are_invalid(self) -> None:
        for mutation in ("missing", "duplicate", "unknown", "pending", "cleanup"):
            with self.subTest(mutation=mutation):
                report = self.execution_report(("passed", "passed", "passed"))
                if mutation == "missing":
                    report["results"].pop()
                elif mutation == "duplicate":
                    report["results"].append(report["results"][0])
                elif mutation == "unknown":
                    report["results"][0]["behavior_id"] = "unknown"
                elif mutation == "pending":
                    report["results"][0]["status"] = "pending"
                else:
                    report["results"][0]["cleanup_error"] = "state cleanup failed"
                self.write("run.json", report)
                result = self.command("--report", str(self.suite / "run.json"))
                self.assertEqual(result.returncode, 1)
                self.assertEqual(json.loads(result.stdout)["verification"]["status"], "invalid")

    def test_unknown_obligations_and_wrong_profiles_cannot_be_mapped(self) -> None:
        mapping = self.suite / "coverage-data/mapping.json"
        original = mapping.read_text()
        for requirement in ("unknown", "cli.system", "library.install"):
            with self.subTest(requirement=requirement):
                document = json.loads(original)
                document["cases"][0]["requirements"] = [requirement]
                self.write("coverage-data/mapping.json", document)
                result = self.command()
                self.assertEqual(result.returncode, 1)
                self.assertIn("coverage:", result.stderr)

    def test_unknown_surfaces_and_duplicate_requirements_fail_closed(self) -> None:
        path = self.suite / "coverage-data/cli-requirements.json"
        original = path.read_text()
        for mutation in ("surface", "duplicate"):
            with self.subTest(mutation=mutation):
                document = json.loads(original)
                if mutation == "surface":
                    document["requirements"][0]["surfaces"] = ["cli.command.unknown"]
                else:
                    document["requirements"].append(document["requirements"][0])
                self.write("coverage-data/cli-requirements.json", document)
                self.assertEqual(self.command().returncode, 1)

    def test_malformed_report_is_rejected_without_a_traceback(self) -> None:
        values: tuple[object, ...] = ([], {"schema": 99}, {"schema": 1, "complete": True})
        for value in values:
            with self.subTest(value=value):
                self.write("run.json", value)
                result = self.command("--report", str(self.suite / "run.json"))
                self.assertEqual(result.returncode, 1)
                self.assertNotIn("Traceback", result.stderr)

    def test_markdown_reports_undefined_percentages_as_not_applicable(self) -> None:
        result = subprocess.run([sys.executable, str(SCRIPT), "--suite", str(self.suite)],
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0/0 (n/a)", result.stdout)
        self.assertNotIn("None%", result.stdout)

    def test_json_output_is_written_atomically(self) -> None:
        json_output = self.suite / "nested" / "summary.json"
        json_output.parent.mkdir()
        result = self.command("--json", "--output", str(json_output))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(json.loads(json_output.read_text())["verification"]["status"], "not-run")
        self.assertEqual(list(json_output.parent.glob(".*.tmp")), [])

    def test_markdown_output_writes_file(self) -> None:
        markdown_output = self.suite / "summary.md"
        result = subprocess.run([sys.executable, str(SCRIPT), "--suite", str(self.suite),
                                 "--output", str(markdown_output)],
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("# Black-box coverage", markdown_output.read_text())

    def test_malformed_typed_evidence_never_receives_credit(self) -> None:
        for field, value in (("exit_status", True), ("api_calls", [7]), ("signals", False),
                             ("stdout", {}), ("argv", [None])):
            with self.subTest(field=field):
                report = self.execution_report(("passed", "passed", "passed"))
                command = report["results"][0]["evidence"][0]
                malformed = object_map(command, "command")
                malformed[field] = value
                # Mutate raw input deliberately, outside the producer DTO contract.
                raw = object_map(report, "report")
                raw["results"] = [{**report["results"][0], "evidence": [malformed]},
                                  *report["results"][1:]]
                self.write("run.json", raw)
                result = self.command("--report", str(self.suite / "run.json"))
                self.assertEqual(result.returncode, 1)
                self.assertIn(f"report.results[0].evidence[0].{field}", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_early_library_error_does_not_credit_unreached_run_call(self) -> None:
        surface_path = self.suite / "coverage-data/surfaces.json"
        surfaces = json.loads(surface_path.read_text())
        surfaces["surfaces"].append({"id": "library.function.run", "kind": "library-function",
                                     "name": "run"})
        self.write("coverage-data/surfaces.json", surfaces)
        path = self.suite / "coverage-data/library-requirements.json"
        requirements = json.loads(path.read_text())
        requirements["requirements"][0]["surfaces"].append("library.function.run")
        self.write("coverage-data/library-requirements.json", requirements)
        report = self.execution_report(("not-selected", "not-selected", "passed"))
        report["results"][2]["evidence"][0]["exit_status"] = 4
        self.write("run.json", report)
        result = self.command("--report", str(self.suite / "run.json"))
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["metrics"]["behaviors"]["library"]["passed"], 1)
        self.assertEqual(output["metrics"]["surfaces"]["library-function"]["implemented"], 2)
        self.assertEqual(output["metrics"]["surfaces"]["library-function"]["passed"], 1)

    def test_passing_reports_need_provenance_and_command_evidence(self) -> None:
        for field in ("target", "target_version", "started_at", "finished_at",
                      "target_provenance", "fixture_provenance", "library_provenance",
                      "artifact_integrity", "evidence", "artifact-changed"):
            with self.subTest(field=field):
                report = self.execution_report(("passed", "passed", "passed"))
                if field == "evidence":
                    report["results"][0]["evidence"] = []
                elif field == "artifact-changed":
                    report["artifact_integrity"]["status"] = "changed"
                raw = object_map(report, "report")
                if field not in ("evidence", "artifact-changed"):
                    del raw[field]
                self.write("run.json", raw)
                result = self.command("--report", str(self.suite / "run.json"))
                self.assertEqual(result.returncode, 1)
                output = json.loads(result.stdout)
                self.assertIsNone(output["metrics"]["behaviors"]["cli"]["passed"])

    def test_explicit_option_assertions_do_not_inflate_behavior_coverage(self) -> None:
        path = self.suite / "coverage-data/surfaces.json"
        catalogue = json.loads(path.read_text())
        catalogue["surfaces"].append({"id": "cli.option.install.--arch", "kind": "cli-option",
                                      "name": "--arch"})
        self.write("coverage-data/surfaces.json", catalogue)
        path = self.suite / "coverage-data/mapping.json"
        mapping = json.loads(path.read_text())
        mapping["cases"][0]["requirements"] = []
        mapping["cases"][0]["surface_assertions"] = [{
            "id": "cli.option.install.--arch", "rationale": "Observe selected alternate ref.",
        }]
        self.write("coverage-data/mapping.json", mapping)
        report = self.execution_report(("passed", "not-selected", "not-selected"))
        self.write("run.json", report)
        result = self.command("--report", str(self.suite / "run.json"))
        self.assertEqual(result.returncode, 0, result.stderr)
        metrics = json.loads(result.stdout)["metrics"]
        self.assertEqual(metrics["surfaces"]["cli-option"]["passed"], 1)
        self.assertEqual(metrics["surfaces"]["cli-command"]["passed"], 0)
        self.assertEqual(metrics["behaviors"]["cli"]["passed"], 0)
        self.assertEqual(metrics["behaviors"]["cli"]["total"], 3)
        self.assertEqual(json.loads(result.stdout)["interface_evidence"], {
            "cli.option.install.--arch": [
                {"behavior_id": "first", "driver": "cli", "profile": "user"},
            ],
        })

    def test_explicit_library_assertions_require_observation_without_behavior_credit(self) -> None:
        path = self.suite / "coverage-data/surfaces.json"
        catalogue = json.loads(path.read_text())
        catalogue["surfaces"].append({"id": "library.signal.Test.ready",
                                      "kind": "library-signal", "name": "ready"})
        self.write("coverage-data/surfaces.json", catalogue)
        path = self.suite / "coverage-data/mapping.json"
        mapping = json.loads(path.read_text())
        mapping["cases"][2]["requirements"] = []
        mapping["cases"][2]["surface_assertions"] = [
            {"id": "library.function.install", "rationale": "Assert installed state."},
            {"id": "library.signal.Test.ready", "rationale": "Assert readiness payload."},
        ]
        self.write("coverage-data/mapping.json", mapping)
        for observed, status, interface in ((False, "passed", "library"),
                                             (True, "passed", "library"),
                                             (True, "failed", "library"),
                                             (True, "passed", "setup")):
            with self.subTest(observed=observed, status=status, interface=interface):
                report = self.execution_report(("not-selected", "not-selected", status))
                command = report["results"][2]["evidence"][0]
                command["api_calls"] = ["install", "install"] if observed else []
                command["signals"] = ["Test.ready", "Test.ready"] if observed else []
                command["interface"] = interface
                if interface == "setup":
                    report["results"][2]["evidence"].append({
                        "argv": ["/synthetic/client"], "interface": "library", "api_calls": [],
                        "signals": [], "exit_status": 0, "stdout": "", "stderr": "",
                    })
                self.write("run.json", report)
                result = self.command("--report", str(self.suite / "run.json"))
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)
                metrics = output["metrics"]
                self.assertEqual(metrics["behaviors"]["library"]["total"], 1)
                self.assertEqual(metrics["behaviors"]["library"]["implemented"], 0)
                self.assertEqual(metrics["behaviors"]["library"]["passed"], 0)
                credit = int(observed and status == "passed" and interface == "library")
                for kind in ("library-function", "library-signal"):
                    self.assertEqual(metrics["surfaces"][kind]["implemented"], 1)
                    self.assertEqual(metrics["surfaces"][kind]["passed"], credit)
                self.assertEqual(len(output["interface_evidence"]), 2 * credit)

    def test_equivalent_options_are_separate_verified_and_deduplicated(self) -> None:
        catalogue = json.loads((self.suite / "coverage-data/surfaces.json").read_text())
        identifier = "cli.option.install.--noninteractive"
        catalogue["surfaces"].append({"id": identifier, "kind": "cli-option",
                                       "name": "--noninteractive"})
        self.write("coverage-data/surfaces.json", catalogue)
        mapping = json.loads((self.suite / "coverage-data/mapping.json").read_text())
        for case in mapping["cases"][:2]:
            case["requirements"] = []
        assertion = {"id": identifier, "rationale": "Test ordinary output equivalence."}
        mapping["cases"][0]["equivalent_options"] = [assertion]
        self.write("coverage-data/mapping.json", mapping)
        equivalence_only = json.loads(self.command().stdout)
        self.assertEqual(equivalence_only["metrics"]["surfaces"]["cli-option"]["implemented"], 0)
        self.assertEqual(equivalence_only["cli_option_accounting"]["accounted"]["implemented"], 1)
        mapping["cases"][1]["surface_assertions"] = [
            {"id": identifier, "rationale": "A separate case demonstrates automatic consent."}]
        self.write("coverage-data/mapping.json", mapping)
        initial = json.loads(self.command().stdout)
        self.assertEqual(initial["metrics"]["surfaces"]["cli-option"]["implemented"], 1)
        self.assertEqual(initial["cli_option_accounting"]["accounted"]["implemented"], 1)
        self.assertIsNone(initial["cli_option_accounting"]["accounted"]["passed"])
        for status, observed, interface, effect_status in (
            ("passed", True, "cli", "not-selected"),
            ("failed", True, "cli", "not-selected"),
            ("passed", False, "cli", "not-selected"),
            ("passed", True, "setup", "not-selected"),
            ("passed", True, "cli", "passed"),
        ):
            with self.subTest(status=status, observed=observed, interface=interface,
                              effect_status=effect_status):
                report = self.execution_report((status, effect_status, "not-selected"))
                record = report["results"][0]["evidence"][0]
                record["argv"] = ["/synthetic/cli", "install"] + (
                    ["--noninteractive"] if observed else [])
                record["interface"] = interface
                if interface == "setup":
                    report["results"][0]["evidence"].append({
                        "argv": ["/synthetic/cli", "list"], "interface": "cli",
                        "exit_status": 0, "stdout": "", "stderr": "",
                    })
                self.write("run.json", report)
                result = self.command("--report", str(self.suite / "run.json"))
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)
                equivalent = int(status == "passed" and observed and interface == "cli")
                effect = int(effect_status == "passed")
                self.assertEqual(output["metrics"]["surfaces"]["cli-option"]["passed"], effect)
                self.assertEqual(output["metrics"]["behaviors"]["cli"]["passed"], 0)
                accounting = output["cli_option_accounting"]
                self.assertEqual(accounting["equivalence_checks"]["passed"], equivalent)
                self.assertEqual(accounting["accounted"]["passed"], int(bool(effect or equivalent)))
                self.assertEqual(len(accounting["equivalence_evidence"]), equivalent)
        report.pop("coverage_definition")
        self.write("run.json", report)
        unverified = self.command("--report", str(self.suite / "run.json"))
        self.assertEqual(unverified.returncode, 1)
        accounting = json.loads(unverified.stdout)["cli_option_accounting"]
        self.assertIsNone(accounting["equivalence_checks"]["passed"])
        self.assertIsNone(accounting["accounted"]["passed"])
        self.assertEqual(accounting["equivalence_evidence"], {})

    def test_equivalent_options_cannot_claim_effect_or_cross_interface(self) -> None:
        catalogue = json.loads((self.suite / "coverage-data/surfaces.json").read_text())
        identifier = "cli.option.install.--verbose"
        catalogue["surfaces"].append({"id": identifier, "kind": "cli-option", "name": "--verbose"})
        self.write("coverage-data/surfaces.json", catalogue)
        original = (self.suite / "coverage-data/mapping.json").read_text()
        for index, surface, rationale, copies, effect in (
            (0, "cli.command.install", "Wrong kind", 1, False),
            (2, identifier, "Wrong interface", 1, False),
            (0, "cli.option.install.--absent", "Unknown", 1, False),
            (0, identifier, " ", 1, False),
            (0, identifier, "Duplicate", 2, False),
            (0, identifier, "Cannot claim both", 1, True),
        ):
            with self.subTest(index=index, surface=surface, rationale=rationale):
                mapping = json.loads(original)
                assertion = {"id": surface, "rationale": rationale}
                mapping["cases"][index]["equivalent_options"] = [assertion] * copies
                if effect:
                    mapping["cases"][index]["surface_assertions"] = [assertion]
                self.write("coverage-data/mapping.json", mapping)
                result = self.command()
                self.assertEqual(result.returncode, 1)
                self.assertIn("invalid equivalent option", result.stderr)

    def test_equivalence_trace_distinguishes_cli_options_from_payload_arguments(self) -> None:
        from coverage_report import invoked_option

        cli, command, option = "/selected/flatpak", "info", "--verbose"
        direct = [cli, command, option, "org.example.App"]
        for argv, inner, expected in (
            (direct, None, True),
            ([cli, "run", "info", option], None, False),
            ([cli, command, "--", option], None, False),
            ([cli, command, "org.example.App", option], None, False),
            ([cli, "run", *direct], direct, False),
            (["/wrapper", *direct], None, False),
            (["/wrapper", *direct], direct, True),
            (["/wrapper", cli, "run", option], direct, False),
        ):
            with self.subTest(argv=argv, inner=inner):
                record: EvidenceRecord = {"argv": argv, "interface": "cli"}
                if inner is not None:
                    record["cli_argv"] = inner
                self.assertEqual(invoked_option(record, cli, command, option), expected)

    def test_explicit_assertions_reject_wrong_interface_kind_duplicates_and_missing_rationale(
        self,
    ) -> None:
        path = self.suite / "coverage-data/mapping.json"
        original = path.read_text()
        for index, identifier, duplicate, rationale in (
            (0, "library.function.install", False, "Cross-interface"),
            (2, "cli.command.install", False, "Cross-interface"),
            (0, "cli.command.install", False, "Commands require behavior assertions"),
            (2, "library.function.missing", False, "Unknown"),
            (2, "library.function.install", True, "Duplicate"),
            (2, "library.function.install", False, ""),
        ):
            with self.subTest(identifier=identifier, rationale=rationale):
                mapping = json.loads(original)
                assertions = [{"id": identifier, "rationale": rationale}]
                mapping["cases"][index]["surface_assertions"] = assertions * (2 if duplicate else 1)
                self.write("coverage-data/mapping.json", mapping)
                result = self.command()
                self.assertEqual(result.returncode, 1)
                self.assertIn("invalid explicit surface assertion", result.stderr)

    def test_unobserved_signal_cannot_receive_reach_credit(self) -> None:
        path = self.suite / "coverage-data/surfaces.json"
        catalogue = json.loads(path.read_text())
        for name in ("ready", "error"):
            catalogue["surfaces"].append({"id": f"library.signal.Test.{name}",
                                          "kind": "library-signal", "name": name})
        self.write("coverage-data/surfaces.json", catalogue)
        path = self.suite / "coverage-data/library-requirements.json"
        requirements = json.loads(path.read_text())
        requirements["requirements"][0]["surfaces"] += [
            "library.signal.Test.ready", "library.signal.Test.error",
        ]
        self.write("coverage-data/library-requirements.json", requirements)
        report = self.execution_report(("not-selected", "not-selected", "passed"))
        report["results"][2]["evidence"][0]["signals"] = ["Test.ready"]
        self.write("run.json", report)
        result = self.command("--report", str(self.suite / "run.json"))
        self.assertEqual(result.returncode, 0, result.stderr)
        metric = json.loads(result.stdout)["metrics"]["surfaces"]["library-signal"]
        self.assertEqual(metric["implemented"], 2)
        self.assertEqual(metric["passed"], 1)

    def test_supplemental_observations_cannot_replace_command_evidence(self) -> None:
        report = self.execution_report(("passed", "passed", "passed"))
        note: EvidenceRecord = {"observation": "metadata", "data": {"key": "value"}}
        report["results"][0]["evidence"].append(note)
        self.write("run.json", report)
        self.assertEqual(self.command("--report", str(self.suite / "run.json")).returncode, 0)
        report["results"][0]["evidence"] = [note]
        self.write("run.json", report)
        self.assertEqual(self.command("--report", str(self.suite / "run.json")).returncode, 1)

    def test_assertion_helpers_are_part_of_the_definition(self) -> None:
        directory = self.suite / "scenario-data"
        directory.mkdir()
        self.write("scenario-data/extra.json", {"schema": 1, "behaviors": [], "mappings": []})
        header = self.suite / "test-extension.h"
        header.write_text("/* an assertion helper */\n")
        bridge = self.suite / "ci/system_helper.py"
        bridge.parent.mkdir()
        bridge.write_text("# assertions executed through a privileged bridge\n")
        for path in (directory / "extra.json", header, bridge):
            report = self.execution_report(("passed", "passed", "passed"))
            self.write("run.json", report)
            path.write_text(path.read_text() + "\n")
            result = self.command("--report", str(self.suite / "run.json"))
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["verification"]["status"], "stale")


if __name__ == "__main__":
    unittest.main()
