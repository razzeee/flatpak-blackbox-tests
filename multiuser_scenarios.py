# SPDX-License-Identifier: LGPL-2.1-or-later
"""Run library contracts through the explicitly provisioned two-user environment."""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    root = driver.env.get("BLACKBOX_SYSTEM_TEST_ROOT")
    if not root:
        raise PrerequisiteError("BLACKBOX_SYSTEM_TEST_ROOT must name a provisioned disposable VM")
    if Path(driver.cli).resolve() != (Path(root) / "build/app/flatpak").resolve():
        raise PrerequisiteError("provisioned helper must belong to the selected target build")
    assert driver.client is not None
    expected_library = (Path(root) / "build/common").resolve()
    libraries = driver.env.get("LD_LIBRARY_PATH", "").split(os.pathsep)
    if [Path(p).resolve() for p in libraries] != [expected_library]:
        raise PrerequisiteError("provisioned library directory differs from the selected target")
    if shutil.which("sudo", path=driver.env.get("PATH")) is None:
        raise PrerequisiteError("provisioned-system cases require sudo for user switching")
    privilege = driver.external_call(["sudo", "-n", "true"], "setup")
    if privilege.returncode:
        raise PrerequisiteError("provisioned-system cases require noninteractive sudo")
    flags = driver.external_call(["pkg-config", "--cflags", "--libs", "polkit-agent-1"], "setup")
    if flags.returncode:
        raise PrerequisiteError("recording agent requires polkit-agent-1 development files")
    agent = driver.root / "polkit-agent"
    built = driver.external_call(
        ["cc", "-O2", "-Wall", "-Wextra", "-Werror",
         str(Path(__file__).with_name("fixture-polkit-agent.c")), "-o", str(agent),
         *shlex.split(flags.stdout)], "setup")
    if built.returncode:
        raise ValueError(f"recording agent build failed: {built.stderr}")
    argv = ["sudo", "-n", "env", f"GITHUB_ACTIONS={os.environ.get('GITHUB_ACTIONS', '')}",
            f"RUNNER_ENVIRONMENT={os.environ.get('RUNNER_ENVIRONMENT', '')}",
            "/usr/bin/python3", str(Path(__file__).parent / "ci/system_helper.py"),
            "case", root, "--client", str(driver.client), "--fixtures", fixture["directory"],
            "--scenario", name, "--agent", str(agent)]
    if driver.env.get("BLACKBOX_SYSTEM_TEST_CONTAINER") == "1":
        argv.append("--disposable-container")
    if driver.env.get("LD_PRELOAD"):
        argv.extend(("--client-preload", driver.env["LD_PRELOAD"]))
    result = driver.external_call(argv, "library")
    if result.returncode == 77:
        raise PrerequisiteError(result.stderr)
    driver.check(result.returncode == 0, f"provisioned library case failed: {result.stderr}")
    driver.check(result.stdout.splitlines()[-1] == f"PASS {name}",
                 "all cross-user assertions completed")
