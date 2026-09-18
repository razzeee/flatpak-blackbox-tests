# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exercise the report boundary independently of coverage eligibility."""

import unittest

from json_validation import ValidationError
from report_schema import parse_report
from test_fixture_manifest import basic


class ReportSchemaTests(unittest.TestCase):
    def test_optional_seconds_are_finite_nonnegative_numbers(self) -> None:
        case = {"behavior_id": "test", "driver": "cli", "profile": "user", "status": "failed"}
        for value in (-1, True, False, float("nan"), float("inf"), "1", None,
                      10**400, -(10**400)):
            for field in ("duration_seconds", "setup_seconds", "execution_seconds",
                          "cleanup_seconds"):
                with self.subTest(value=value, field=field), \
                        self.assertRaises(ValidationError) as caught:
                    fields = ({field: value} if field == "duration_seconds" else {
                        "timings": {"setup_seconds": 0, "execution_seconds": 0,
                                    "cleanup_seconds": 0, field: value},
                    })
                    parse_report({"schema": 1, "results": [{**case, **fields}]})
                prefix = "" if field == "duration_seconds" else "timings."
                self.assertIn(f"report.results[0].{prefix}{field}", str(caught.exception))
            with self.subTest(run=value), self.assertRaises(ValidationError) as caught:
                parse_report({"schema": 1, "duration_seconds": value})
            self.assertIn("report.duration_seconds", str(caught.exception))
        report = parse_report({"schema": 1, "duration_seconds": 3, "results": [
            {**case, "duration_seconds": 2.5, "timings": {
                "setup_seconds": 0, "execution_seconds": 2, "cleanup_seconds": 0.5}},
        ]})
        self.assertEqual(report["results"][0]["duration_seconds"], 2.5)

    def test_incremental_reports_and_supplemental_json(self) -> None:
        raw = {"schema": 1, "complete": False, "library_provenance": {}, "results": [
            {"behavior_id": "test", "driver": "cli", "profile": "user", "status": "pending",
             "target_version": None, "evidence": [
                 {"argv": ["client"]},
                 {"observation": "metadata", "data": {"nested": [None, 1, True, "text"]}},
             ]},
        ]}
        parsed = parse_report(raw)
        self.assertEqual(parsed, raw)
        self.assertIsNot(parsed, raw)
        self.assertEqual(parse_report({"schema": 1}), {"schema": 1})

    def test_output_text_retains_control_characters(self) -> None:
        report = parse_report({"schema": 1, "setup_evidence": [
            {"argv": ["client"], "stdout": "before\0after", "stderr": "line\nnext"},
        ]})
        self.assertEqual(report["setup_evidence"][0]["stdout"], "before\0after")

    def test_present_nested_fields_are_checked_even_without_a_definition(self) -> None:
        malformed: list[tuple[dict[str, object], str]] = [
            ({"schema": True}, "report.schema"),
            ({"complete": 1}, "report.complete"),
            ({"target_version": []}, "report.target_version"),
            ({"results": {}}, "report.results"),
            ({"results": [{}]}, "report.results[0]"),
            ({"target_provenance": {"adapter_files": [{"sha256": 1}]}},
             "report.target_provenance.adapter_files[0].sha256"),
            ({"fixture_provenance": {"manifest_sha256": False}},
             "report.fixture_provenance.manifest_sha256"),
            ({"library_provenance": {"package_version": []}},
             "report.library_provenance.package_version"),
            ({"artifact_integrity": {"changed_paths": [1]}},
             "report.artifact_integrity.changed_paths[0]"),
            ({"declared_unsupported_capabilities": {"cli": False}},
             "report.declared_unsupported_capabilities.cli"),
            ({"setup_evidence": [{"exit_status": True}]},
             "report.setup_evidence[0].exit_status"),
        ]
        for fields, path in malformed:
            with self.subTest(fields=fields), self.assertRaises(ValidationError) as caught:
                parse_report({"schema": 1, **fields})
            self.assertIn(path, str(caught.exception))

    def test_every_case_evidence_field_is_checked_before_use(self) -> None:
        for field, value in (("exit_status", True), ("argv", [1]), ("stdout", None),
                             ("stderr", []), ("api_calls", [False]), ("signals", {}),
                             ("observation", 3), ("interface", []), ("timed_out", 1)):
            with self.subTest(field=field), self.assertRaises(ValidationError) as caught:
                parse_report({"schema": 1, "results": [
                    {"behavior_id": "test", "driver": "cli", "profile": "user",
                     "status": "failed", "evidence": [{field: value}]},
                ]}, "input")
            self.assertIn(f"input.results[0].evidence[0].{field}", str(caught.exception))

    def test_unknown_fields_and_observations_must_be_json(self) -> None:
        for value in (object(), float("nan"), {1: "non-string key"}):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                parse_report({"schema": 1, "extension": value})
            with self.subTest(value=value), self.assertRaises(ValidationError):
                parse_report({"schema": 1, "setup_evidence": [
                    {"observation": "metadata", "data": value},
                ]})

    def test_embedded_fixture_uses_the_fixture_parser(self) -> None:
        fixture = basic()
        report = parse_report({"schema": 1, "complete": False, "fixture": fixture})
        self.assertEqual(report["fixture"], fixture)
        malformed: list[object] = [
            [], {}, {**fixture, "schema": True}, {**fixture, "arch": []},
            {**fixture, "arch": ""}, {**fixture, "commits": {"A": "app-a"}},
            {**fixture, "sizes": {"A": {"app/ref": {"installed": -1, "download": 2}}}},
            {**fixture, "sizes": {"A": {"app/ref": {"installed": True, "download": 2}}}},
        ]
        for value in malformed:
            with self.subTest(value=value), self.assertRaises(ValidationError) as caught:
                parse_report({"schema": 1, "complete": False, "fixture": value}, "input")
            self.assertIn("input.fixture", str(caught.exception))

    def test_embedded_gaps_require_valid_behavior_metadata(self) -> None:
        gap = {"id": "unimplemented", "gap": "Needs a VM", "profile": "system",
               "drivers": ["cli"], "extension": {"note": "Preserved"}}
        self.assertEqual(parse_report({"schema": 1, "gaps": [gap]})["gaps"], [gap])
        malformed: list[object] = [
            False, {}, {"id": "missing-explanation"}, {**gap, "gap": ""},
            {**gap, "gap": False}, {**gap, "id": ""}, {**gap, "profile": "root"},
            {**gap, "references": [1]}, {**gap, "handler": "not:a:handler"},
        ]
        for value in malformed:
            with self.subTest(value=value), self.assertRaises(ValidationError) as caught:
                parse_report({"schema": 1, "complete": False, "gaps": [value]}, "input")
            self.assertIn("input.gaps[0]", str(caught.exception))

    def test_named_network_observations_check_requests_and_counts(self) -> None:
        request = {"path": "/summary", "version": "A", "blocked": False}
        observations: dict[str, dict[str, object]] = {
            "query_network_observation": {"requests": [request],
                                          "cached_query_requests": 0,
                                          "uncached_query_requests": 0},
            "sideload_image_network_observation": {"requests": [request],
                                                  "remote_contains_images": False},
            "sideload_network_observation": {"requests": [request]},
        }
        for name, observation in observations.items():
            valid = {"schema": 1, "complete": False, "setup_evidence": [{name: observation}]}
            self.assertEqual(parse_report(valid), valid)
            malformed: list[object] = [
                [], {}, {**observation, "requests": False},
                {**observation, "requests": [{}]},
                {**observation, "requests": [{**request, "path": []}]},
                {**observation, "requests": [{**request, "version": None}]},
                {**observation, "requests": [{**request, "blocked": 1}]},
            ]
            if name == "query_network_observation":
                for count in ("cached_query_requests", "uncached_query_requests"):
                    malformed.extend({**observation, count: value} for value in (-1, True, "0"))
            elif name == "sideload_image_network_observation":
                malformed.append({**observation, "remote_contains_images": 0})
            for value in malformed:
                for location in ("setup_evidence", "results"):
                    with self.subTest(name=name, value=value, location=location):
                        record = {name: value}
                        report: dict[str, object] = {"schema": 1, "complete": False}
                        if location == "setup_evidence":
                            report[location] = [record]
                        else:
                            report[location] = [{"behavior_id": "test", "driver": "cli",
                                                 "profile": "user", "status": "pending",
                                                 "evidence": [record]}]
                        with self.assertRaises(ValidationError) as caught:
                            parse_report(report, "input")
                        self.assertIn(name, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
