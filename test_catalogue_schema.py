# SPDX-License-Identifier: LGPL-2.1-or-later
"""Static input validation through parser boundaries and the public coverage CLI."""

import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Literal, TypedDict

import test_coverage_report
from catalogue_schema import (
    parse_behavior,
    parse_catalogue,
    parse_inventory,
    parse_mappings,
    parse_requirements,
    parse_scenario_group,
)
from coverage_report import CoverageModel
from json_validation import ValidationError, array, load_json, object_map
from report_schema import parse_typed
from scenario_catalogue import extension_clients, load_behaviors


class CatalogueSchemaTests(unittest.TestCase):
    def test_committed_catalogues_preserve_case_and_denominator_counts(self) -> None:
        suite = Path(__file__).parent
        model = CoverageModel(suite)
        self.assertEqual(model.catalogue, load_json(suite / "coverage-data/surfaces.json"))
        self.assertEqual(len(model.cases), 383)
        metrics = model.summarize()["metrics"]
        self.assertEqual({key: item["total"] for key, item in metrics["behaviors"].items()},
                         {"cli": 136, "library": 163})
        self.assertEqual({key: item["implemented"] for key, item in metrics["behaviors"].items()},
                         {"cli": 136, "library": 162})
        self.assertEqual({key: item["total"] for key, item in metrics["surfaces"].items()},
                         {"cli-command": 44, "cli-option": 624,
                          "library-function": 223, "library-signal": 14})
        self.assertEqual({key: item["implemented"] for key, item in metrics["surfaces"].items()},
                           {"cli-command": 44, "cli-option": 429,
                             "library-function": 223, "library-signal": 14})
        self.assertTrue(extension_clients(suite))

    def test_gap_defaults_and_both_contract_text_formats(self) -> None:
        self.assertEqual(parse_behavior({"id": "gap", "gap": "Not implemented"}),
                         {"id": "gap", "gap": "Not implemented"})
        for text in ("Contract", ["Contract", "Another assertion"]):
            raw = {"id": "executable", "scenario": "test", "drivers": ["cli"],
                   "profile": "any", "preconditions": text, "expected": text,
                   "extension": {"future": [True, None]}, "notes": ["A note"]}
            parsed = parse_behavior(raw)
            self.assertEqual(parsed, {**raw, "required_capabilities": []})

    def test_required_executable_fields_and_optional_metadata_are_checked(self) -> None:
        raw = {"id": "test", "scenario": "test", "drivers": ["cli"], "profile": "user"}
        for field in ("id", "drivers", "profile"):
            malformed = {key: value for key, value in raw.items() if key != field}
            with self.subTest(field=field), self.assertRaises(ValidationError):
                parse_behavior(malformed)
        for field, value in (("drivers", ["unknown"]), ("profile", "root"),
                             ("expected", [False]), ("preconditions", {}),
                             ("description", []), ("references", [1]),
                             ("handler", "module:function:extra"),
                             ("notes", "not an array"), ("required_capabilities", [None])):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                parse_behavior({**raw, field: value})

    def test_all_document_schemas_reject_boolean_versions(self) -> None:
        examples: tuple[tuple[Callable[[object], object], dict[str, object]], ...] = (
            (parse_inventory, {"behaviors": []}),
            (parse_scenario_group, {"behaviors": [], "mappings": []}),
            (parse_mappings, {"cases": []}),
            (parse_requirements, {"scope": "cli", "requirements": [], "limitations": []}),
            (parse_catalogue, {"reference": {"commit": "test", "sources": {}},
                               "surfaces": [], "limitations": []}),
        )
        for parser, fields in examples:
            with self.subTest(parser=parser.__name__), self.assertRaises(ValidationError):
                parser({"schema": True, **fields})

    def test_generic_parser_checks_literals_keys_and_extension_json(self) -> None:
        class LiteralFields(TypedDict):
            version: Literal[1]

        self.assertEqual(parse_typed({"version": 1}, LiteralFields, "value"), {"version": 1})
        for value in ({"version": True}, {"version": 2},
                      {"version": 1, "extension": object()}):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                parse_typed(value, LiteralFields, "value")
        with self.assertRaises(ValidationError):
            parse_typed({"1": "value"}, dict[int, str], "value")


class CatalogueCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = test_coverage_report.CoverageReportTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_bad_metadata_is_diagnosed_without_a_traceback(self) -> None:
        mutations: list[tuple[str, tuple[str | int, ...], object]] = [
            ("coverage-data/surfaces.json", ("schema",), True),
            ("coverage-data/surfaces.json", ("reference", "sources"), {"doc.xml": 1}),
            ("coverage-data/surfaces.json", ("surfaces", 0, "kind"), "unknown"),
            ("coverage-data/surfaces.json", ("surfaces", 0, "aliases"), [False]),
            ("coverage-data/surfaces.json", ("surfaces", 0, "command"), "unknown"),
            ("coverage-data/surfaces.json", ("surfaces", 0, "deprecated"), 1),
            ("coverage-data/surfaces.json", ("surfaces", 0, "sources"), [{"path": 7}]),
            ("coverage-data/cli-requirements.json", ("requirements", 0, "category"), []),
            ("coverage-data/cli-requirements.json", ("requirements", 0, "sources"),
             [{"path": "doc.xml", "anchor": False}]),
            ("coverage-data/mapping.json", ("cases", 0, "rationale"), {}),
            ("inventory.json", ("behaviors", 0, "expected"), [1]),
            ("inventory.json", ("behaviors", 0, "drivers"), ["unknown"]),
        ]

        def replace(value: object, keys: tuple[str | int, ...], replacement: object) -> object:
            if not keys:
                return replacement
            key, *remaining = keys
            if isinstance(key, int):
                items = array(value, "test array")
                items[key] = replace(items[key], tuple(remaining), replacement)
                return items
            data = object_map(value, "test object")
            data[key] = replace(data.get(key), tuple(remaining), replacement)
            return data

        for name, keys, value in mutations:
            with self.subTest(name=name, keys=keys):
                path = self.fixture.suite / name
                original = load_json(path)
                self.fixture.write(name, replace(original, keys, value))
                result = self.fixture.command()
                self.assertEqual(result.returncode, 1)
                self.assertIn("coverage:", result.stderr)
                self.assertIn(str(path), result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(result.stdout, "")
                self.fixture.write(name, original)

    def test_group_notes_clients_and_cross_document_duplicate_ids(self) -> None:
        (self.fixture.suite / "scenario-data").mkdir()
        for fields in ({"notes": [False]}, {"client": {"source": 1, "entry": "name"}},
                       {"client": {"source": "../client.c", "entry": "blackbox_test_main"}},
                       {"client": {"source": "client.c", "entry": "unknown"}}):
            with self.subTest(fields=fields):
                self.fixture.write("scenario-data/test.json", {
                    "schema": 1, "behaviors": [], "mappings": [], **fields,
                })
                result = self.fixture.command()
                self.assertEqual(result.returncode, 1)
                self.assertIn("scenario-data/test.json", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
        self.fixture.write("scenario-data/test.json", {
            "schema": 1, "behaviors": [{"id": "first", "gap": "Duplicate"}], "mappings": [],
        })
        with self.assertRaisesRegex(ValidationError, "duplicate behavior ID"):
            load_behaviors(self.fixture.suite)


if __name__ == "__main__":
    unittest.main()
