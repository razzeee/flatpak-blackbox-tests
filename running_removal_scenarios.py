# SPDX-License-Identifier: LGPL-2.1-or-later
"""Observe forced removal through the public mount of a still-running sandbox."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from install_option_scenarios import _clear, _state
from parent_process_scenarios import _instance

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    command = name.removeprefix("running-removal-")
    if command not in {"update", "uninstall"}:
        raise ValueError(f"unknown running removal scenario: {name}")
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture", url)
    for forced in (False, True):
        repository.version = "A"
        driver.cli_success("install", "--user", "--noninteractive", "fixture", app)
        _state(driver, {app: fixture["commits"]["A"], runtime: fixture["runtime_commit"]})
        with _instance(driver, fixture["app"], f"retained-{forced}") as (instance, _):
            before = driver.cli_success("enter", instance, "/usr/bin/blackbox-probe", "exists",
                                        "/app/bin/blackbox-probe")
            driver.check(before == "exists", "the running sandbox initially exposes its payload")
            if command == "update":
                repository.version = "B"
            options = ("--force-remove",) if forced else ()
            driver.cli_success(command, "--user", "--noninteractive", *options, app)
            expected = {runtime: fixture["runtime_commit"]}
            if command == "update":
                expected[app] = fixture["commits"]["B"]
            _state(driver, expected)
            result = driver.cli_call("enter", instance, "/usr/bin/blackbox-probe", "exists",
                                     "/app/bin/blackbox-probe")
            if forced:
                # enter may report its own successful launch status rather than
                # the payload status. Require the independent probe's actual
                # missing-file diagnostic and no success output.
                driver.check(result.returncode in (0, 1) and not result.stdout and
                             result.stderr.startswith("exists:"),
                             "forced removal must delete the old running sandbox's payload entry")
            else:
                driver.check(result.returncode == 0 and result.stdout == "exists\n",
                             "ordinary removal must retain files used by the running sandbox")
            if command == "update":
                driver.check(driver.cli_success("run", "--user", app) == "B",
                             "the new active deployment remains independently runnable")
        _clear(driver)
