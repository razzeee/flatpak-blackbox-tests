# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exercise runner attribution through its CLI with controlled executables."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Callable, Iterator
from contextlib import contextmanager, redirect_stdout
from http.server import ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import run
from fixture_manifest import FixtureManifest
from report_schema import EvidenceRecord

RUNNER = Path(__file__).with_name("run.py")


class CommandInputTests(unittest.TestCase):
    def test_target_commands_cannot_inherit_confirmation_from_runner_stdin(self) -> None:
        script = (
            "import os,sys; from pathlib import Path; import run; "
            "result=run.execute([sys.executable,'-c',"
            "'import sys; print(repr(sys.stdin.read()))'],"
            "dict(os.environ),Path.cwd(),[],5); "
            "print(result.stdout,end=''); raise SystemExit(result.returncode)"
        )
        result = subprocess.run([sys.executable, "-c", script], cwd=RUNNER.parent,
                                input="yes\n", text=True, capture_output=True, timeout=10,
                                check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "''\n")

    @unittest.skipUnless(Path("/proc/self/stat").is_file(), "requires Linux procfs")
    def test_execute_does_not_wait_for_descendant_inherited_output_pipes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="runner-descendant-") as directory:
            child_pid_path = Path(directory) / "child.pid"
            script = (
                "import subprocess,sys; "
                "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(10)']); "
                f"open({str(child_pid_path)!r},'w').write(str(child.pid)); "
                "print('leader finished')"
            )
            evidence: list[EvidenceRecord] = []
            result = run.execute([sys.executable, "-c", script], dict(os.environ),
                                 Path.cwd(), evidence, 2)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "leader finished\n")
            self.assertEqual(evidence[0]["exit_status"], 0)
            child_pid = int(child_pid_path.read_text())
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                try:
                    state = Path(f"/proc/{child_pid}/stat").read_text().split()[2]
                except FileNotFoundError:
                    break
                if state == "Z":
                    break
                time.sleep(0.01)
            else:
                self.fail(f"command descendant {child_pid} was not terminated")

    def test_execute_preserves_output_when_command_times_out(self) -> None:
        evidence: list[EvidenceRecord] = []
        with self.assertRaisesRegex(run.ContractFailure, "timed out after 0.1s"):
            run.execute([sys.executable, "-c",
                         "import time; print('started', flush=True); time.sleep(10)"],
                        dict(os.environ), Path.cwd(), evidence, 0.1)
        self.assertEqual(evidence[0]["stdout"], "started\n")
        self.assertTrue(evidence[0]["timed_out"])
        self.assertNotEqual(evidence[0]["exit_status"], 0)

    def test_execute_preserves_evidence_for_incomplete_output(self) -> None:
        for fd, field in ((1, "stdout"), (2, "stderr")):
            for timed_out in (False, True):
                with self.subTest(stream=field, timed_out=timed_out):
                    evidence: list[EvidenceRecord] = []
                    script = (
                        f"import os,time; os.write({fd}, b'partial: \\xe2\\x82'); "
                        + ("time.sleep(10)" if timed_out else "raise SystemExit(7)")
                    )
                    argv = [sys.executable, "-c", script]
                    if timed_out:
                        with self.assertRaisesRegex(run.ContractFailure, "timed out"):
                            run.execute(argv, dict(os.environ), Path.cwd(), evidence, 1)
                        self.assertTrue(evidence[0]["timed_out"])
                        self.assertLess(evidence[0]["exit_status"], 0)
                    else:
                        result = run.execute(argv, dict(os.environ), Path.cwd(), evidence, 1)
                        self.assertEqual(result.returncode, 7)
                        self.assertEqual(evidence[0]["exit_status"], 7)
                        self.assertNotIn("timed_out", evidence[0])
                    captured = evidence[0]["stdout"] if fd == 1 else evidence[0]["stderr"]
                    self.assertTrue(captured.startswith("partial: "))
                    self.assertIn("\ufffd", captured)


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
        self.assertGreater(passed[0]["duration_seconds"], 0)
        self.assertAlmostEqual(passed[0]["duration_seconds"], sum(passed[0]["timings"].values()))
        self.assertGreaterEqual(report["duration_seconds"], passed[0]["duration_seconds"])

    def test_changed_executable_invalidates_otherwise_passing_results(self) -> None:
        summary = self.root / "summary.md"
        with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}):
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
        self.assertIn("**INVALID**", summary.read_text())
        self.assertIn("unverified", summary.read_text())
        self.assertNotIn("0.0%", summary.read_text())

    def test_target_environment_is_validated_before_any_target_command(self) -> None:
        target = json.loads(self.target.read_text())
        target["environment"] = {"PATH": 7}
        self.target.write_text(json.dumps(target))
        summary = self.root / "summary.md"
        with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}):
            result = self.execute()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        report = json.loads((self.root / "results/report.json").read_text())
        self.assertIn("target.environment.PATH", report["setup_error"])
        self.assertEqual(report["setup_evidence"], [])
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.stdout.count("[1/1] ERROR"), 1)
        self.assertIn("0 PASS, 0 FAIL, 1 ERROR", result.stdout)
        self.assertTrue(all("duration_seconds" not in case for case in report["results"]))
        self.assertIn("No executed case timings available", summary.read_text())
        self.assertIn("1 ERROR", summary.read_text())

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
        self.assertEqual(selected["timings"], {"setup_seconds": 0.0, "execution_seconds": 0.0,
                                              "cleanup_seconds": 2.5})
        self.assertEqual(selected["duration_seconds"], 2.5)

    def test_failed_handler_accounts_for_context_startup_and_shutdown(self) -> None:
        self.execute()
        now = 0.0

        @contextmanager
        def bus(env: dict[str, str], root: Path, *,
                on_cleanup: Callable[[], None] | None = None) -> Iterator[None]:
            nonlocal now
            self.assertNotIn("GITHUB_STEP_SUMMARY", env)
            now += 2
            try:
                yield
            finally:
                if on_cleanup is not None:
                    on_cleanup()
                now += 5

        def scenario(*args: object) -> None:
            nonlocal now
            now += 3
            raise run.ContractFailure("controlled failure")

        argv = [str(RUNNER), "--target", str(self.target), "--fixtures", str(self.fixtures),
                "--output", str(self.root / "timed-results"), "--driver", "cli",
                "--scenario", "missing-install", "--color", "always"]
        summary = self.root / "summary.md"
        with patch.object(sys, "argv", argv), redirect_stdout(StringIO()), \
                patch.object(run, "session_bus", bus), patch.object(run, "scenario", scenario), \
                patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}):
            self.assertEqual(run.main(clock=lambda: now), 1)
        report = json.loads((self.root / "timed-results/report.json").read_text())
        selected = next(case for case in report["results"] if case["status"] != "not-selected")
        self.assertEqual(selected["status"], "failed")
        self.assertEqual(selected["timings"], {"setup_seconds": 2.0, "execution_seconds": 3.0,
                                              "cleanup_seconds": 5.0})
        self.assertEqual(selected["duration_seconds"], 10.0)
        self.assertEqual(report["duration_seconds"], 10.0)
        self.assertTrue(selected["cleanup_complete"])
        self.assertFalse(Path(selected["state_directory"]).exists())
        self.assertIn("**FAIL** | 10.00s | 2.00s | 3.00s | 5.00s", summary.read_text())
        self.assertNotIn("\x1b", summary.read_text())

    def test_summary_write_failure_preserves_final_report(self) -> None:
        with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(self.root / "missing/summary")}):
            result = self.execute()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Cannot write GitHub job summary", result.stdout)
        report = json.loads((self.root / "results/report.json").read_text())
        self.assertTrue(report["complete"])
        self.assertIn("coverage", report)
        self.assertTrue((self.root / "results/coverage.md").exists())
        self.assertFalse((self.root / "results/job-summary.md").exists())

    def test_summary_append_separates_existing_text_and_saves_delivery_marker(self) -> None:
        summary = self.root / "summary.md"
        summary.write_text("existing")
        with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}):
            result = self.execute()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(summary.read_text().startswith("existing\n\n## Flatpak compatibility"))
        self.assertEqual(summary.read_text()[len("existing\n\n"):],
                         (self.root / "results/job-summary.md").read_text())

    def test_failed_bus_startup_attributes_internal_rollback_to_cleanup(self) -> None:
        self.execute()
        now = 0.0
        terminate = run.terminate

        def timeout(timeout: float) -> list[object]:
            nonlocal now
            now += 2
            return []

        def stop(process: subprocess.Popen[str] | subprocess.Popen[bytes]) -> None:
            nonlocal now
            if isinstance(process.args, list) and process.args[0] == "dbus-daemon":
                now += 5
            terminate(process)

        argv = [str(RUNNER), "--target", str(self.target), "--fixtures", str(self.fixtures),
                "--output", str(self.root / "startup-results"), "--driver", "cli",
                "--scenario", "missing-install"]
        with patch.object(sys, "argv", argv), redirect_stdout(StringIO()), \
                patch("run.selectors.DefaultSelector") as selector, \
                patch.object(run, "terminate", stop):
            selector.return_value.__enter__.return_value.select.side_effect = timeout
            self.assertEqual(run.main(clock=lambda: now), 1)
        report = json.loads((self.root / "startup-results/report.json").read_text())
        selected = next(case for case in report["results"] if case["status"] != "not-selected")
        self.assertEqual(selected["status"], "unmet-prerequisite")
        self.assertEqual(selected["timings"], {"setup_seconds": 2.0, "execution_seconds": 0.0,
                                              "cleanup_seconds": 5.0})
        self.assertEqual(selected["duration_seconds"], 7.0)
        self.assertFalse(Path(selected["state_directory"]).exists())

    def test_context_exit_failure_still_closes_bus_and_deletes_state(self) -> None:
        self.execute()
        now = 0.0
        events = []
        shutdown = ThreadingHTTPServer.shutdown
        close = ThreadingHTTPServer.server_close
        terminate = run.terminate
        rmtree = shutil.rmtree
        original_scenario = run.scenario

        def stop_server(server: ThreadingHTTPServer) -> None:
            nonlocal now
            shutdown(server)
            events.append("shutdown")
            now += 3
            raise OSError("shutdown failure")

        def close_server(server: ThreadingHTTPServer) -> None:
            events.append("close")
            close(server)

        def stop_bus(process: subprocess.Popen[str] | subprocess.Popen[bytes]) -> None:
            nonlocal now
            if isinstance(process.args, list) and process.args[0] == "dbus-daemon":
                events.append("bus")
                now += 5
            terminate(process)

        def remove_state(path: Path) -> None:
            nonlocal now
            events.append("state")
            now += 7
            rmtree(path)

        def scenario(driver: run.Driver, repository: run.RepositoryServer, url: str,
                     fixture: FixtureManifest, name: str) -> None:
            nonlocal now
            original_scenario(driver, repository, url, fixture, name)
            now += 4

        argv = [str(RUNNER), "--target", str(self.target), "--fixtures", str(self.fixtures),
                "--output", str(self.root / "exit-results"), "--driver", "cli",
                "--scenario", "missing-install"]
        with patch.object(sys, "argv", argv), redirect_stdout(StringIO()), \
                patch.object(ThreadingHTTPServer, "shutdown", stop_server), \
                patch.object(ThreadingHTTPServer, "server_close", close_server), \
                patch.object(run, "terminate", stop_bus), \
                patch.object(shutil, "rmtree", remove_state), \
                patch.object(run, "scenario", scenario):
            self.assertEqual(run.main(clock=lambda: now), 1)
        report = json.loads((self.root / "exit-results/report.json").read_text())
        selected = next(case for case in report["results"] if case["status"] != "not-selected")
        self.assertEqual(events, ["shutdown", "close", "bus", "state"])
        self.assertEqual(selected["status"], "setup-error")
        self.assertIn("shutdown failure", selected["cleanup_error"])
        self.assertNotIn("cleanup_complete", selected)
        self.assertFalse(Path(selected["state_directory"]).exists())
        self.assertEqual(selected["timings"], {"setup_seconds": 0.0, "execution_seconds": 4.0,
                                              "cleanup_seconds": 15.0})
        self.assertEqual(selected["duration_seconds"], 19.0)
        self.assertTrue(any(record.get("interface") == "cli" for record in selected["evidence"]))
        self.assertEqual(report["coverage"]["metrics"]["behaviors"]["cli"]["passed"], 0)

    def test_failed_repository_startup_times_socket_rollback_as_cleanup(self) -> None:
        self.execute()
        now = 0.0
        close = ThreadingHTTPServer.server_close

        def start() -> None:
            nonlocal now
            now += 2
            raise OSError("thread startup failed")

        def close_server(server: ThreadingHTTPServer) -> None:
            nonlocal now
            now += 5
            close(server)

        argv = [str(RUNNER), "--target", str(self.target), "--fixtures", str(self.fixtures),
                "--output", str(self.root / "repository-startup-results"), "--driver", "cli",
                "--scenario", "missing-install"]
        with patch.object(sys, "argv", argv), redirect_stdout(StringIO()), \
                patch("run.threading.Thread.start", side_effect=start), \
                patch.object(ThreadingHTTPServer, "server_close", close_server):
            self.assertEqual(run.main(clock=lambda: now), 1)
        report = json.loads((self.root / "repository-startup-results/report.json").read_text())
        selected = next(case for case in report["results"] if case["status"] != "not-selected")
        self.assertEqual(selected["status"], "setup-error")
        self.assertEqual(selected["timings"], {"setup_seconds": 2.0, "execution_seconds": 0.0,
                                              "cleanup_seconds": 5.0})
        self.assertEqual(selected["duration_seconds"], 7.0)
        self.assertFalse(Path(selected["state_directory"]).exists())

    def test_shared_library_build_time_is_counted_once_only_in_run_duration(self) -> None:
        self.execute()
        target = json.loads(self.target.read_text())
        target["library"] = {"runtime_library_dirs": [str(self.root)]}
        self.target.write_text(json.dumps(target))
        now = 0.0

        def clock() -> float:
            return now

        for fail in (False, True):
            now = 0.0

            def build(*args: object, fail: bool = fail) -> Path:
                nonlocal now
                now += 11
                if fail:
                    raise run.PrerequisiteError("build unavailable")
                return self.root / "client"

            def scenario(*args: object) -> None:
                nonlocal now
                now += 2

            output = self.root / f"build-results-{fail}"
            argv = [str(RUNNER), "--target", str(self.target), "--fixtures", str(self.fixtures),
                    "--output", str(output), "--driver", "library" if fail else "all",
                    "--scenario", "all" if fail else "missing-install"]
            with self.subTest(fail=fail), patch.object(sys, "argv", argv), \
                    redirect_stdout(StringIO()), \
                    patch.object(run, "build_client", side_effect=build) as build_mock, \
                    patch.object(run, "scenario", scenario), \
                    patch.object(tempfile, "mkdtemp", wraps=tempfile.mkdtemp) as allocation:
                run.main(clock=clock)
                self.assertEqual(build_mock.call_count, 1)
                self.assertEqual(allocation.call_count, 0 if fail else 2)
            report = json.loads((output / "report.json").read_text())
            selected = [case for case in report["results"] if case["status"] != "not-selected"]
            self.assertEqual(report["duration_seconds"], 11.0 if fail else 15.0)
            if fail:
                self.assertGreater(len(selected), 1)
                self.assertTrue(all("duration_seconds" not in case and "timings" not in case
                                    and "state_directory" not in case for case in selected))
            else:
                self.assertEqual([case["duration_seconds"] for case in selected], [2.0, 2.0])

    def test_library_build_failures_are_setup_errors_without_case_execution(self) -> None:
        self.execute()
        for index, error in enumerate((ValueError("public library client did not compile: broken"),
                                       run.ContractFailure("compiler timed out"))):
            output = self.root / f"compile-error-{index}"
            argv = [str(RUNNER), "--target", str(self.target), "--fixtures", str(self.fixtures),
                    "--output", str(output), "--driver", "library"]
            with self.subTest(error=error), patch.object(sys, "argv", argv), \
                    redirect_stdout(StringIO()), \
                    patch.object(run, "build_client", side_effect=error), \
                    patch.object(tempfile, "mkdtemp") as allocation:
                self.assertEqual(run.main(), 1)
                allocation.assert_not_called()
            report = json.loads((output / "report.json").read_text())
            selected = [case for case in report["results"] if case["status"] != "not-selected"]
            self.assertGreater(len(selected), 1)
            self.assertTrue(all(case["status"] == "setup-error" and case["error"] == str(error)
                                and not case["evidence"] for case in selected))

    def test_missing_api_only_blocks_its_dependent_scenario(self) -> None:
        self.execute()
        target = json.loads(self.target.read_text())
        target["library"] = {"runtime_library_dirs": [str(self.root)]}
        self.target.write_text(json.dumps(target))
        for name in ("tx-rate", "tx-progress"):
            output = self.root / name
            argv = [str(RUNNER), "--target", str(self.target), "--fixtures", str(self.fixtures),
                    "--output", str(output), "--driver", "library", "--scenario", name]
            with patch.object(sys, "argv", argv), redirect_stdout(StringIO()), \
                    patch.object(run, "build_client", return_value=self.root / "client"), \
                    patch("transaction_scenarios.run") as handler:
                run.main()
                self.assertEqual(handler.call_count, 0 if name == "tx-rate" else 1)
            report = json.loads((output / "report.json").read_text())
            selected = next(case for case in report["results"] if case["status"] != "not-selected")
            self.assertEqual(selected["status"], "unsupported" if name == "tx-rate" else "passed")
            if name == "tx-rate":
                self.assertIn("flatpak_transaction_progress_get_bytes_per_second",
                              selected["error"])
                self.assertEqual(selected["evidence"], [])
                self.assertEqual(
                    report["coverage"]["metrics"]["surfaces"]["library-function"]["passed"], 0,
                )

    def test_failed_state_allocation_still_finalizes_case_timing(self) -> None:
        self.execute()
        now = 10.0

        def allocation(*, prefix: str) -> str:
            nonlocal now
            now += 2
            raise OSError("state allocation failed")

        argv = [str(RUNNER), "--target", str(self.target), "--fixtures", str(self.fixtures),
                "--output", str(self.root / "allocation-results"), "--driver", "cli",
                "--scenario", "missing-install"]
        with patch.object(sys, "argv", argv), redirect_stdout(StringIO()), \
                patch.object(tempfile, "mkdtemp", allocation):
            self.assertEqual(run.main(clock=lambda: now), 1)
        report = json.loads((self.root / "allocation-results/report.json").read_text())
        selected = next(case for case in report["results"] if case["status"] != "not-selected")
        self.assertEqual(selected["timings"], {"setup_seconds": 2.0, "execution_seconds": 0.0,
                                              "cleanup_seconds": 0.0})
        self.assertEqual(selected["duration_seconds"], 2.0)
        self.assertNotIn("state_directory", selected)
        self.assertTrue(selected["cleanup_complete"])

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
            ".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache",
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
