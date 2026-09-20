# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exercise the CI namespace probe with real bubblewrap."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CompatibilityProbeTests(unittest.TestCase):
    def test_system_helper_provisioning_rejects_an_unprovisioned_host(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ci-system-guard-") as temporary:
            root = Path(temporary)
            (root / "logs").mkdir()
            suite = Path(__file__).resolve().parent
            env = {key: value for key, value in os.environ.items()
                   if key not in ("GITHUB_ACTIONS", "RUNNER_ENVIRONMENT")}
            for phase in ("start", "probe", "stop", "case"):
                result = subprocess.run(
                    [sys.executable, str(suite / "ci/system_helper.py"), phase, str(root)],
                    env=env, text=True, capture_output=True, timeout=10, check=False)
                self.assertEqual(result.returncode, 2)
                self.assertIn("requires root in a disposable", result.stderr)
                self.assertEqual(list(root.iterdir()), [root / "logs"])

    def test_logged_runner_failure_remains_fatal_and_gets_fallback(self) -> None:
        if os.getuid() == 0:
            self.skipTest("CI helper requires an ordinary user")
        with tempfile.TemporaryDirectory(prefix="ci-failure-") as temporary:
            root = Path(temporary)
            (root / "logs").mkdir()
            uv = root / "uv"
            uv.write_text("#!/bin/sh\nprintf 'controlled runner failure\\n'\nexit 23\n")
            uv.chmod(0o755)
            suite = Path(__file__).resolve().parent
            summary = root / "summary.md"
            env = {**os.environ, "BB_CI_ROOT": str(root), "TMPDIR": str(root),
                   "FLATPAK_REFERENCE_COMMIT": "0" * 40,
                   "PATH": f"{root}{os.pathsep}{os.defpath}",
                   "GITHUB_STEP_SUMMARY": str(summary)}
            command = ["bash", str(suite / "ci/compatibility.sh")]
            result = subprocess.run([*command, "run"], cwd=suite, env=env, capture_output=True,
                                    text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 23)
            self.assertIn("controlled runner failure", (root / "logs/run.log").read_text())
            result = subprocess.run([*command, "summary"], cwd=suite, env=env, capture_output=True,
                                    text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Coverage and timings are unverified", summary.read_text())

    def test_fallback_summary_without_run_and_without_duplicate_delivery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ci-summary-") as temporary:
            root = Path(temporary)
            summary = root / "summary.md"
            summary.write_text("earlier step")
            suite = Path(__file__).resolve().parent
            env = {**os.environ, "BB_CI_ROOT": str(root / "not-initialized"),
                   "GITHUB_STEP_SUMMARY": str(summary)}
            command = ["bash", str(suite / "ci/compatibility.sh"), "summary"]
            result = subprocess.run(command, cwd=suite, env=env, capture_output=True,
                                    text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(summary.read_text().startswith("earlier step\n\n## Flatpak"))
            self.assertIn("No completed report summary", summary.read_text())
            self.assertNotIn("0%", summary.read_text())
            self.assertNotIn("\x1b", summary.read_text())
            delivered = root / "not-initialized/results/job-summary.md"
            delivered.parent.mkdir(parents=True)
            # A report alone does not prove delivery to Actions succeeded.
            delivered.with_name("report.json").write_text('{"complete": true}')
            summary.write_text("")
            result = subprocess.run(command, cwd=suite, env=env, capture_output=True,
                                    text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("No completed report summary", summary.read_text())
            delivered.write_text("## Flatpak compatibility\n\nUNSUCCESSFUL\n")
            # GITHUB_STEP_SUMMARY changes between steps. Only the marker is shared.
            env["GITHUB_STEP_SUMMARY"] = str(root / "new-step-summary.md")
            result = subprocess.run(command, cwd=suite, env=env, capture_output=True,
                                    text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(Path(env["GITHUB_STEP_SUMMARY"]).exists())

    def test_nested_root_namespace_probe(self) -> None:
        bwrap = shutil.which("bwrap")
        if bwrap is None or os.getuid() == 0:
            self.skipTest("requires bubblewrap and an ordinary user")
        outer = subprocess.run([
            bwrap, "--unshare-all", "--ro-bind", "/", "/", "--proc", "/proc",
            "--dev", "/dev", "--uid", "0", "--gid", "0", "/usr/bin/true",
        ], capture_output=True, text=True, timeout=15, check=False)
        if outer.returncode:
            self.skipTest(f"unprivileged namespaces unavailable: {outer.stderr.strip()}")

        with tempfile.TemporaryDirectory(prefix="ci-probe-") as temporary:
            root = Path(temporary)
            (root / "logs").mkdir()
            helper = root / "build/subprojects/bubblewrap/flatpak-bwrap"
            helper.parent.mkdir(parents=True)
            helper.symlink_to(bwrap)
            suite = Path(__file__).resolve().parent
            result = subprocess.run([
                "bash", str(suite / "ci/compatibility.sh"), "probe",
            ], cwd=suite, env={
                **os.environ, "BB_CI_ROOT": str(root), "TMPDIR": str(root),
                "FLATPAK_REFERENCE_COMMIT": "0" * 40,
            }, capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
