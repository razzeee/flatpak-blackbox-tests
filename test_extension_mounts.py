# SPDX-License-Identifier: LGPL-2.1-or-later
"""Check that installation alone cannot satisfy the sandbox extension scenarios."""

import subprocess
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import extension_mount_scenarios
from fixture_manifest import FixtureExtensionMounts, FixtureManifest
from run import ContractFailure, Driver, PrerequisiteError, RepositoryServer, require

APP = "app/org.flatpak.ExtensionMount/x86_64/test"
EXTENSION = "runtime/org.flatpak.ExtensionMount.Data/x86_64/test"
RUNTIME = "runtime/org.example.Platform/x86_64/test"
SCENARIOS = ("extension-mount-same-origin", "extension-mount-remote-alias",
             "extension-mount-separate-repos")


class ExtensionMountTests(unittest.TestCase):
    def exercise(self, scenario: str, defect: str = "") -> Mock:
        separate = scenario.endswith("separate-repos")
        origin = "queries" if scenario.endswith("same-origin") else "extensions"
        commit = "separate-commit" if separate else "combined-commit"
        marker = "separate-marker" if separate else "combined-marker"
        mounts: FixtureExtensionMounts = {
            "app": APP, "extension": EXTENSION, "app_repo": "app",
            "combined_repo": "combined", "extension_repo": "extension",
            "app_commit": "app-commit", "runtime_commit": "runtime-commit",
            "combined_commit": "combined-commit", "separate_commit": "separate-commit",
            "combined_marker": "combined-marker", "separate_marker": "separate-marker",
        }
        fixture = cast(FixtureManifest, {
            "directory": "/fixtures", "arch": "x86_64", "branch": "test",
            "runtime": "org.example.Platform", "queries": {"extension_mounts": mounts},
        })
        installed = False
        driver = Mock(spec=Driver)
        driver.check.side_effect = require

        def success(*args: str) -> str:
            nonlocal installed
            operation = args[0]
            if operation == "remote-add":
                return ""
            if operation == "remote-ls":
                refs = ({EXTENSION} if separate and args[-1] == "extensions" else
                        {APP, RUNTIME} if separate else {APP, RUNTIME, EXTENSION})
                if defect == "not-separate" and separate:
                    refs.add(EXTENSION)
                return "\n".join(sorted(refs))
            if operation == "install":
                if args[-1] == EXTENSION or defect == "auto-installed":
                    installed = True
                return ""
            if operation == "uninstall":
                installed = False
                return ""
            if operation == "list":
                refs = {APP, RUNTIME, EXTENSION} if installed else {APP, RUNTIME}
                return "\n".join(ref.split("/", 1)[1] for ref in sorted(refs))
            if operation == "info":
                return "wrong-origin" if defect == "origin" else origin
            if operation == "run":
                if args[-1] == APP:
                    return "broken" if defect == "not-live" else "A"
                if args[-1] == "/app/data/marker":
                    return "wrong-marker" if defect == "contents" else marker
                if args[-1] == "/.flatpak-info":
                    checksum = "wrong-commit" if defect == "commit" else commit
                    extensions = f"{EXTENSION.split('/')[1]}={checksum}" if installed else ""
                    return f"[Instance]\napp-extensions={extensions}\n"
                if args[-1] == "/proc/self/mountinfo":
                    if not installed or defect == "no-mount":
                        return "1 0 0:1 / /app ro - tmpfs tmpfs rw"
                    flags = "rw" if defect == "writable" else "ro,nosuid,nodev"
                    return f"2 1 0:1 /deployment/files /app/data {flags} - tmpfs tmpfs rw"
            self.fail(f"unexpected CLI command: {args}")

        def missing(*args: str) -> subprocess.CompletedProcess[str]:
            self.assertEqual(args, ("run", "--user", APP, "read", "/app/data/marker"))
            self.assertFalse(installed)
            if defect == "host-leak":
                return subprocess.CompletedProcess(list(args), 0, marker, "")
            error = "sandbox startup failed" if defect == "startup" else (
                "read: No such file or directory\n")
            return subprocess.CompletedProcess(list(args), 1, "", error)

        driver.cli_success.side_effect = success
        driver.cli_call.side_effect = missing
        extension_mount_scenarios.run(driver, Mock(spec=RepositoryServer), "", fixture, scenario)
        return driver

    def test_all_topologies_have_live_absent_present_removed_controls(self) -> None:
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                driver = self.exercise(scenario)
                driver.query.assert_any_call(APP, "app-commit")
                driver.query.assert_any_call(RUNTIME, "runtime-commit")
                expected = "separate-commit" if scenario.endswith("separate-repos") else (
                    "combined-commit")
                driver.query.assert_any_call(EXTENSION, expected)
                self.assertEqual(driver.cli_call.call_count, 2)
                origin = "queries" if scenario.endswith("same-origin") else "extensions"
                driver.cli_success.assert_any_call(
                    "install", "--user", "--noninteractive", origin, EXTENSION)
                app_repo = "app" if scenario.endswith("separate-repos") else "combined"
                driver.cli_success.assert_any_call(
                    "remote-add", "--user", "--no-gpg-verify", "queries",
                    (Path("/fixtures") / app_repo).as_uri())
                if origin == "extensions":
                    ext_repo = "extension" if scenario.endswith("separate-repos") else "combined"
                    driver.cli_success.assert_any_call(
                        "remote-add", "--user", "--no-gpg-verify", "extensions",
                        (Path("/fixtures") / ext_repo).as_uri())

    def test_installation_success_cannot_hide_bad_runtime_evidence(self) -> None:
        for defect in ("origin", "contents", "commit", "no-mount", "writable", "not-live",
                       "host-leak", "startup", "auto-installed", "not-separate"):
            with self.subTest(defect=defect), self.assertRaises(ContractFailure):
                self.exercise("extension-mount-separate-repos", defect)

    def test_old_fixtures_are_an_explicit_prerequisite_failure(self) -> None:
        with self.assertRaisesRegex(PrerequisiteError, "extension mount fixtures required"):
            extension_mount_scenarios.run(Mock(spec=Driver), Mock(spec=RepositoryServer), "",
                                          cast(FixtureManifest, {}), SCENARIOS[0])


if __name__ == "__main__":
    unittest.main()
