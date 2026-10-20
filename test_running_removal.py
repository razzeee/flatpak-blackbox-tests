# SPDX-License-Identifier: LGPL-2.1-or-later
"""Keep forced removal exclusive to uninstall without weakening live update checks."""

import subprocess
import unittest
from contextlib import nullcontext
from typing import cast
from unittest.mock import Mock, call, patch

import running_removal_scenarios as scenarios
from fixture_manifest import FixtureManifest


class RunningRemovalTests(unittest.TestCase):
    def test_command_selection_and_deployment_checks(self) -> None:
        fixture = cast(FixtureManifest, {
            "app": "org.example.App", "runtime": "org.example.Runtime",
            "arch": "x86_64", "branch": "test",
            "commits": {"A": "a" * 64, "B": "b" * 64}, "runtime_commit": "c" * 64,
        })
        app = "app/org.example.App/x86_64/test"
        runtime = "runtime/org.example.Runtime/x86_64/test"
        for command, forced_modes in (("update", (False,)), ("uninstall", (False, True))):
            with self.subTest(command=command):
                driver = Mock()
                repository = Mock()
                def cli_success(*args: str) -> str:
                    if args[0] == "update":
                        self.assertNotIn("--force-remove", args, "Unknown option --force-remove")
                    return "exists" if args[0] == "enter" else "B" if args[0] == "run" else ""

                driver.cli_success.side_effect = cli_success
                driver.cli_call.side_effect = [
                    subprocess.CompletedProcess([], 0, "", "exists: missing\n") if forced else
                    subprocess.CompletedProcess([], 0, "exists\n", "")
                    for forced in forced_modes
                ]

                def check(condition: bool, message: str) -> None:
                    self.assertTrue(condition, message)

                driver.check.side_effect = check
                with (
                    patch.object(scenarios, "_instance",
                                 side_effect=lambda *args: nullcontext(("instance", None))) as live,
                    patch.object(scenarios, "_state") as state,
                    patch.object(scenarios, "_clear") as clear,
                ):
                    scenarios.run(driver, repository, "http://fixture", fixture,
                                  f"running-removal-{command}")
                invocations = [c.args for c in driver.cli_success.call_args_list
                               if c.args[0] in {"update", "uninstall"}]
                self.assertEqual(invocations, [
                    (command, "--user", "--noninteractive",
                     *(("--force-remove",) if forced else ()), app)
                    for forced in forced_modes
                ])
                expected = {runtime: "c" * 64}
                if command == "update":
                    expected[app] = "b" * 64
                self.assertEqual(state.call_args_list, [entry for _ in forced_modes for entry in (
                    call(driver, {app: "a" * 64, runtime: "c" * 64}), call(driver, expected))])
                self.assertEqual(live.call_count, len(forced_modes))
                self.assertEqual(clear.call_count, len(forced_modes))
                self.assertEqual(driver.cli_call.call_args_list, [
                    call("enter", "instance", "/usr/bin/blackbox-probe", "exists",
                         "/app/bin/blackbox-probe") for _ in forced_modes])
                launches = [c.args for c in driver.cli_success.call_args_list if c.args[0] == "run"]
                self.assertEqual(launches, [("run", "--user", app)] if command == "update" else [])
                self.assertEqual(repository.version, "B" if command == "update" else "A")


if __name__ == "__main__":
    unittest.main()
