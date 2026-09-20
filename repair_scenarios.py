# SPDX-License-Identifier: LGPL-2.1-or-later
"""Repair outcomes through public queries, offline redeployment and app execution."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    commit = fixture["commits"]["A"]

    def setup(operation: str) -> str:
        helper = driver.env.get("BLACKBOX_REPAIR_FIXTURE")
        if not helper:
            raise PrerequisiteError("adapter does not provide BLACKBOX_REPAIR_FIXTURE")
        result = driver.external_call(
            [sys.executable, helper, str(driver.root), operation, commit], "setup")
        driver.check(result.returncode == 0, f"repair fixture {operation}: {result.stderr}")
        return result.stdout

    def dry_run() -> str:
        result = driver.cli_call("repair", "--user", "--dry-run")
        driver.check(result.returncode == 0, f"dry-run repair failed: {result.stderr}")
        return result.stdout + result.stderr

    driver.success("remote", url)
    driver.success("install", app)
    driver.query(app, commit)
    driver.check(driver.success("run", app) == "A", "healthy app runs version A")
    if name == "repair-reinstall-all":
        location = Path(driver.cli_success("info", "--user", "--show-location", app))
        executable = location / "files/bin/blackbox-probe"
        driver.check(executable.resolve().is_relative_to(driver.root),
                     "fault injection is confined to the public isolated deployment")
        expected = (Path(fixture["directory"]) / fixture["assets"]["app_tree"] /
                    "files/bin/blackbox-probe").read_bytes()
        driver.check(executable.read_bytes() == expected, "healthy deployment matches fixture A")
        # Unlink only the deployment entry, leaving repository hardlinks intact.
        executable.unlink()
        driver.evidence.append({"observation": "removed-deployed-executable",
                                "data": str(executable)})
        # The runtime also contains blackbox-probe. An absolute command prevents
        # PATH lookup from hiding a missing executable in /app by running /usr's.
        command = "--command=/app/bin/blackbox-probe"
        driver.check(driver.call("run", command, app).returncode != 0,
                     "damaged deployment cannot run its app executable")
        driver.cli_success("repair", "--user")
        driver.check(driver.call("run", command, app).returncode != 0,
                     "ordinary repair does not redeploy healthy repository objects")
        driver.cli_success("repair", "--user", "--reinstall-all")
        driver.query(app, commit)
        driver.query(runtime, fixture["runtime_commit"])
        repaired = Path(driver.cli_success("info", "--user", "--show-location", app))
        restored = repaired / "files/bin/blackbox-probe"
        driver.check(restored.is_file() and restored.read_bytes() == expected,
                     "forced repair redeploys the independent executable bytes")
        driver.check(driver.success("run", command, app) == "A",
                     "forced redeployment restores app A")
        return
    # Warm dry-run bookkeeping before taking the damaged-state snapshot.
    healthy = dry_run()
    setup("remove-payload")

    if name == "repair-user-dry-run":
        before = setup("snapshot")
        damaged = dry_run()
        driver.check(setup("snapshot") == before,
                     "dry-run preserves all persistent installation paths, contents and modes")
        new_lines = set(damaged.splitlines()) - set(healthy.splitlines())
        driver.check(any(fixture["app"] in line for line in new_lines),
                     "dry-run distinguishes damaged installation and identifies affected app")
    elif name != "repair-user-restore":
        raise ValueError(f"unknown repair scenario: {name}")

    driver.cli_success("repair", "--user")
    driver.query(app, commit)
    driver.query(runtime, fixture["runtime_commit"])
    # Existing deployments can still run after repository damage. Force a fresh
    # deployment offline so a no-op repair cannot pass on those surviving files.
    driver.cli_success("remote-modify", "--user", "--url=file:///nonexistent-repair-origin",
                       "fixture")
    driver.cli_success("install", "--user", "--noninteractive", "--reinstall", "--no-pull",
                       "fixture", app, runtime)
    driver.query(app, commit)
    driver.query(runtime, fixture["runtime_commit"])
    driver.check(driver.success("run", app) == "A", "repaired content redeploys offline and runs A")
