# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exercise category loading, evidence invalidation, and static JSON formatting."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_coverage_report
from catalogue_schema import load_requirements, parse_requirements
from coverage_report import CoverageModel
from format_json import format_files
from json_validation import ValidationError, load_json


class RequirementLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = test_coverage_report.CoverageReportTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.suite / "coverage-data"
        self.index = self.root / "cli-requirements.json"
        self.original = load_requirements(self.index)
        (self.root / "cli-requirements").mkdir()
        self.shard = self.root / "cli-requirements/lifecycle.json"
        self.shard.write_text(json.dumps({**self.original, "limitations": []}))
        self.index.write_text(json.dumps({
            **self.original, "requirements": [],
            "includes": ["cli-requirements/lifecycle.json"],
        }))

    def test_shards_preserve_monolithic_requirements_and_accounting(self) -> None:
        loaded = load_requirements(self.index)
        del loaded["includes"]
        self.assertEqual(loaded, self.original)
        sharded = CoverageModel(self.fixture.suite)
        self.index.write_text(json.dumps(self.original))
        monolithic = CoverageModel(self.fixture.suite)
        self.assertEqual(sharded.requirements, monolithic.requirements)
        self.assertEqual(sharded.limitations, monolithic.limitations)
        self.assertEqual(sharded.summarize()["metrics"], monolithic.summarize()["metrics"])

    def test_nested_category_change_invalidates_passing_report(self) -> None:
        report = self.fixture.execution_report(("passed", "passed", "passed"))
        self.fixture.write("run.json", report)
        result = self.fixture.command("--report", str(self.fixture.suite / "run.json"))
        self.assertEqual(result.returncode, 0, result.stderr)
        original = parse_requirements(load_json(self.shard))
        original["requirements"][0]["description"] = "Changed contract"
        self.shard.write_text(json.dumps(original))
        result = self.fixture.command("--report", str(self.fixture.suite / "run.json"))
        self.assertEqual(result.returncode, 1, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["verification"]["status"], "stale")
        self.assertIsNone(summary["metrics"]["behaviors"]["cli"]["passed"])

    def test_invalid_includes_are_diagnosed_without_tracebacks(self) -> None:
        index = load_json(self.index)
        shard = load_json(self.shard)
        mutations: list[tuple[Path, object, str]] = [
            (self.index, {**self.original, "includes": ["missing.json"]}, "missing.json"),
            (self.index, {**self.original, "includes": "lifecycle.json"}, "includes"),
            (self.index, {**self.original, "includes": [False]}, "includes"),
            (self.index, {**self.original, "includes": ["../inventory.json"]}, "include path"),
            (self.index, {**self.original, "includes": [str(self.shard)]}, "include path"),
            (self.index, {**self.original, "includes": [""]}, "include path"),
            (self.index, {**self.original, "includes": ["cli-requirements/data.txt"]},
             "include path"),
            (self.index, {**self.original, "includes": ["cli-requirements.json"]}, "include path"),
            (self.shard, {**self.original, "scope": "library"}, "scope"),
            (self.shard, {**self.original, "includes": []}, "recursive"),
            (self.index, {**self.original, "includes": ["cli-requirements/lifecycle.json"]},
             "duplicate requirement ID"),
            (self.index, {**self.original, "requirements": [], "includes": [
                "cli-requirements/lifecycle.json", "cli-requirements/./lifecycle.json",
            ]}, "duplicate requirement include"),
        ]
        for path, value, diagnostic in mutations:
            with self.subTest(value=value):
                path.write_text(json.dumps(value))
                result = self.fixture.command()
                self.assertEqual(result.returncode, 1)
                self.assertIn(diagnostic, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.index.write_text(json.dumps(index))
                self.shard.write_text(json.dumps(shard))

    def test_shard_records_are_validated_and_cannot_cross_interfaces(self) -> None:
        for field, value in (("interface", "library"), ("required_capabilities", [False]),
                             ("description", 12)):
            with self.subTest(field=field):
                document = load_json(self.shard)
                # Use the JSON boundary to inject deliberately malformed values.
                malformed = json.loads(json.dumps(document))
                malformed["requirements"][0][field] = value
                self.shard.write_text(json.dumps(malformed))
                with self.assertRaises(ValidationError):
                    load_requirements(self.index)
                self.shard.write_text(json.dumps(document))

    def test_duplicate_ids_across_distinct_shards_are_rejected(self) -> None:
        other = self.shard.with_name("other.json")
        other.write_text(self.shard.read_text())
        index = parse_requirements(load_json(self.index))
        index["includes"].append("cli-requirements/other.json")
        self.index.write_text(json.dumps(index))
        with self.assertRaisesRegex(ValidationError, "duplicate requirement ID"):
            load_requirements(self.index)

    def test_symlink_cannot_escape_category_directory(self) -> None:
        self.shard.unlink()
        self.shard.symlink_to(self.fixture.suite / "inventory.json")
        with self.assertRaisesRegex(ValidationError, "include path"):
            load_requirements(self.index)


class JSONFormattingTests(unittest.TestCase):
    def test_check_identifies_file_and_write_is_semantic_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("format_json.py", "json_validation.py"):
                (root / name).write_text(Path(__file__).with_name(name).read_text())
            path = root / "inventory.json"
            text = '{"second": [true, null, 1.25], "first": "caf\\u00e9"}'
            path.write_text(text)
            command = [sys.executable, str(root / "format_json.py")]
            result = subprocess.run([*command, "--check"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("inventory.json", result.stdout)
            self.assertEqual(path.read_text(), text)
            result = subprocess.run([*command, "--write"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(load_json(path), json.loads(text))
            self.assertLess(path.read_text().index('"second"'), path.read_text().index('"first"'))
            formatted = path.read_text()
            self.assertTrue(formatted.endswith("\n"))
            self.assertIn('\n  "second": [\n    true,', formatted)
            self.assertEqual(format_files(root, write=True), [])
            self.assertEqual(path.read_text(), formatted)
            result = subprocess.run([*command, "--check"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_only_static_data_is_formatted_including_nested_categories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            names = ["target.example.json", "coverage-data/cli/category.json",
                     "scenario-data/topic.json", "_build/report.json", ".venv/data.json",
                     "reports/report.json"]
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{"key": 1}')
            self.assertEqual(set(format_files(root, write=True)),
                             {root / name for name in names[:3]})
            for name in names[3:]:
                self.assertEqual((root / name).read_text(), '{"key": 1}')

    def test_duplicate_keys_are_rejected_before_rewriting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "inventory.json"
            text = '{"key": 1, "key": 2}'
            path.write_text(text)
            with self.assertRaises(ValidationError):
                format_files(root, write=True)
            self.assertEqual(path.read_text(), text)


if __name__ == "__main__":
    unittest.main()
