# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exercise runner attribution through its CLI with controlled executables."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import run

RUNNER = Path(__file__).with_name("run.py")


@unittest.skipUnless(shutil.which("dbus-daemon"), "runner isolation requires dbus-daemon")
class RunnerAttributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="runner-attribution-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.selected = self.root / "selected"
        self.poison = self.root / "poison"
        self.selected.mkdir()
        self.poison.mkdir()
        self.fixtures = self.root / "fixtures"
        self.fixtures.mkdir()
        (self.fixtures / "fixture.json").write_text(json.dumps({
            "schema": 1, "arch": "x86_64", "app": "org.flatpak.RunnerTest",
            "runtime": "org.flatpak.RunnerPlatform", "branch": "test", "sha256": {},
            "commits": {"A": "a", "B": "b"}, "runtime_commit": "runtime",
        }))
        self.target = self.root / "target.json"
        self.adapter = self.root / "adapter.py"
        self.adapter.write_text(
            "import json\nprint(json.dumps("
            + repr({"PATH": f"{self.poison}{os.pathsep}{os.defpath}"}) + "))\n"
        )
        self.target.write_text(json.dumps({
            "name": "runner test target", "cli": "candidate-flatpak",
            "adapter": [sys.executable, str(self.adapter)],
            "environment": {"PATH": f"{self.selected}{os.pathsep}{os.defpath}"},
        }))
        self.write_executable(self.poison / "candidate-flatpak", "raise SystemExit(87)\n")

    @staticmethod
    def write_executable(path: Path, body: str) -> None:
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)

    def execute(self, *, mutate: bool = False,
                extra: tuple[str, ...] = ()) -> subprocess.CompletedProcess[str]:
        self.write_executable(self.selected / "candidate-flatpak", f"""
import sys
from pathlib import Path
command = sys.argv[1]
if command == '--version':
    print('Runner test target 1.0')
elif command == '--default-arch':
    print('x86_64')
elif command == 'install':
    if {mutate!r}:
        path = Path(__file__)
        path.write_text(path.read_text() + '# changed after probe\\n')
    print('error: No remote refs found for ' + sys.argv[-1], file=sys.stderr)
    raise SystemExit(1)
elif command not in ('remote-add', 'list'):
    raise SystemExit(88)
""")
        return subprocess.run([
            sys.executable, str(RUNNER), "--target", str(self.target),
            "--fixtures", str(self.fixtures), "--output", str(self.root / "results"),
            "--driver", "cli", "--scenario", "missing-install",
            "--color", "never", *extra,
        ], text=True, capture_output=True, check=False, timeout=30)

    def test_adapter_path_cannot_replace_the_recorded_executable(self) -> None:
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads((self.root / "results/report.json").read_text())
        expected = str((self.selected / "candidate-flatpak").resolve())
        self.assertEqual(report["target_provenance"]["cli_path"], expected)
        passed = [case for case in report["results"] if case["status"] == "passed"]
        self.assertEqual(len(passed), 1)
        for command in passed[0]["evidence"]:
            if command.get("interface") == "cli":
                self.assertEqual(command["argv"][0], expected)
        self.assertEqual(report["coverage"]["verification"]["status"], "current")
        self.assertIn("[1/1] PASS", result.stdout)
        self.assertIn("Selected cases passed", result.stdout)
        self.assertIn("1 PASS, 0 FAIL, 0 ERROR, 0 UNMET, 0 UNSUPPORTED", result.stdout)
        self.assertNotIn("\x1b", result.stdout)
        self.assertNotIn("duration", passed[0])

    def test_changed_executable_invalidates_otherwise_passing_results(self) -> None:
        result = self.execute(mutate=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        report = json.loads((self.root / "results/report.json").read_text())
        self.assertEqual(report["artifact_integrity"]["status"], "changed")
        self.assertEqual(report["coverage"]["verification"]["status"], "invalid")
        self.assertIsNone(report["coverage"]["metrics"]["behaviors"]["cli"]["passed"])
        self.assertIn("[1/1] PASS", result.stdout)
        self.assertIn("INVALID", result.stdout)
        self.assertIn("Artifact integrity: changed; coverage verification: invalid", result.stdout)
        self.assertNotIn("Selected cases passed", result.stdout)

    def test_target_environment_is_validated_before_any_target_command(self) -> None:
        target = json.loads(self.target.read_text())
        target["environment"] = {"PATH": 7}
        self.target.write_text(json.dumps(target))
        result = self.execute()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        report = json.loads((self.root / "results/report.json").read_text())
        self.assertIn("target.environment.PATH", report["setup_error"])
        self.assertEqual(report["setup_evidence"], [])
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.stdout.count("[1/1] ERROR"), 1)
        self.assertIn("0 PASS, 0 FAIL, 1 ERROR", result.stdout)

    def test_unsupported_selected_cases_appear_once(self) -> None:
        target = json.loads(self.target.read_text())
        target["unsupported_capabilities"] = {"cli": "not implemented"}
        self.target.write_text(json.dumps(target))
        result = self.execute(extra=("--driver", "all"))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("[1/2] UNSUPPORTED"), 1)
        self.assertEqual(result.stdout.count("[2/2] UNSUPPORTED"), 1)
        self.assertIn("2 UNSUPPORTED", result.stdout)
        self.assertNotIn("Selected cases passed", result.stdout)

    def test_target_diagnostic_is_safe_on_console_and_raw_in_json(self) -> None:
        raw = "\x1b]0;injected\x07\x1b[31mbroken\x1b[0m\r\n" + "x" * 1000
        self.adapter.write_text(f"import sys\nsys.stderr.write({raw!r})\nsys.exit(77)\n")
        result = self.execute()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("[1/1] UNMET", result.stdout)
        self.assertNotIn("\x1b", result.stdout + result.stderr)
        self.assertNotIn("injected", result.stdout)
        self.assertNotIn("x" * 241, result.stdout)
        report = json.loads((self.root / "results/report.json").read_text())
        selected = next(case for case in report["results"] if case["status"] != "not-selected")
        self.assertIn("\x1b]0;injected\x07", selected["error"])
        self.assertIn("x" * 1000, selected["evidence"][0]["stderr"])

    def test_unsupported_and_preflight_errors_share_selected_count(self) -> None:
        target = json.loads(self.target.read_text())
        target["unsupported_capabilities"] = {"libflatpak": "not implemented"}
        self.target.write_text(json.dumps(target))
        (self.fixtures / "fixture.json").write_text("{}")
        result = self.execute(extra=("--driver", "all"))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("[1/2] UNSUPPORTED"), 1)
        self.assertEqual(result.stdout.count("[2/2] ERROR"), 1)
        self.assertIn("0 PASS, 0 FAIL, 1 ERROR, 0 UNMET, 1 UNSUPPORTED", result.stdout)

    def test_cleanup_failure_and_monotonic_timings(self) -> None:
        # Prepare the controlled target, then run in-process to inject cleanup and time.
        self.execute()
        stream = StringIO()
        now = 10.0

        def clock() -> float:
            return now

        def cleanup(path: Path) -> None:
            nonlocal now
            now = 12.5
            raise OSError("cleanup denied")

        argv = [str(RUNNER), "--target", str(self.target), "--fixtures", str(self.fixtures),
                "--output", str(self.root / "cleanup-results"), "--driver", "cli",
                "--scenario", "missing-install", "--color", "never"]
        with patch.object(sys, "argv", argv), redirect_stdout(stream), \
                patch.object(shutil, "rmtree", side_effect=cleanup):
            status = run.main(clock=clock)
        report = json.loads((self.root / "cleanup-results/report.json").read_text())
        selected = next(case for case in report["results"] if case["status"] != "not-selected")
        self.addCleanup(shutil.rmtree, selected["state_directory"])
        self.assertEqual(status, 1)
        self.assertEqual(stream.getvalue().count("[1/1] ERROR"), 1)
        self.assertIn("2.50s", stream.getvalue())
        self.assertIn("2.50s wall time", stream.getvalue())
        self.assertIn("cleanup denied", stream.getvalue())

    def test_adapter_cannot_pass_an_untyped_environment_to_the_target(self) -> None:
        self.adapter.write_text('print(\'{"PATH": false}\')\n')
        result = self.execute()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        report = json.loads((self.root / "results/report.json").read_text())
        selected = [case for case in report["results"] if case["status"] != "not-selected"]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["status"], "setup-error")
        self.assertIn("adapter.PATH", selected[0]["error"])
        self.assertFalse(any(record.get("interface") == "cli"
                             for record in selected[0]["evidence"]))

    def test_malformed_fixture_extension_fails_during_preflight(self) -> None:
        path = self.fixtures / "fixture.json"
        fixture = json.loads(path.read_text())
        fixture["sizes"] = {"A": {"some-ref": {"download": True, "installed": 1}}}
        path.write_text(json.dumps(fixture))
        result = self.execute()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        report = json.loads((self.root / "results/report.json").read_text())
        self.assertIn("sizes.A.some-ref.download", report["setup_error"])
        self.assertEqual(report["setup_evidence"], [])
        self.assertNotIn("Traceback", result.stderr)

    def test_namespace_bootstrap_has_no_annotation_import_dependencies(self) -> None:
        bootstrap = self.root / "standalone-bootstrap.py"
        shutil.copyfile(RUNNER.with_name("system_selector_scenarios.py"), bootstrap)
        result = subprocess.run([
            sys.executable, "-I", "-c",
            "import runpy, sys; runpy.run_path(sys.argv[1], run_name='bootstrap_import_check')",
            str(bootstrap),
        ], cwd=self.root, text=True, capture_output=True, check=False, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_malformed_inventory_has_a_cli_diagnostic(self) -> None:
        suite = self.root / "suite"
        shutil.copytree(RUNNER.parent, suite, ignore=shutil.ignore_patterns(
            ".venv", "__pycache__", ".mypy_cache", ".ruff_cache",
        ))
        (suite / "inventory.json").write_text('{"schema": true, "behaviors": []}')
        result = subprocess.run([
            sys.executable, str(suite / "run.py"), "--help",
        ], text=True, capture_output=True, check=False, timeout=15)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("invalid coverage definitions", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
