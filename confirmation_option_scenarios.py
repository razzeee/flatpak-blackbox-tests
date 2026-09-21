# SPDX-License-Identifier: LGPL-2.1-or-later
"""Transaction confirmation with closed stdin and independently known commits."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from install_option_scenarios import _state

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    command = name.removeprefix("confirmation-options-")
    if command not in {"install", "update", "uninstall"}:
        raise ValueError(f"unknown confirmation scenario: {name}")
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture", url)
    for option in ("--assumeyes", "--noninteractive"):
        repository.version = "A"
        if command != "install":
            driver.cli_success("install", "--user", "--noninteractive", "fixture", app)
        before = {} if command == "install" else {
            app: fixture["commits"]["A"], runtime: fixture["runtime_commit"]}
        if command == "update":
            repository.version = "B"
        args = ("fixture", app) if command == "install" else (app,)
        # execute() closes stdin. Ordinary confirmation must not perform a
        # pending transaction without consent, even when no terminal is attached.
        _state(driver, before)
        control = driver.cli_call(command, "--user", *args)
        _state(driver, before)
        driver.check(control.returncode != 0, "closed stdin must not approve the transaction")
        result = driver.cli_call(command, "--user", option, *args)
        driver.check(result.returncode == 0,
                     f"{command} {option} must proceed without input: {result.stderr}")
        after = {runtime: fixture["runtime_commit"]}
        if command != "uninstall":
            after[app] = fixture["commits"]["B" if command == "update" else "A"]
        _state(driver, after)
        driver.check("[Y/n]" not in result.stdout and "[y/n]" not in result.stdout,
                     "automatic confirmation must not print an unanswered confirmation prompt")
        driver.cli_success("uninstall", "--user", "-y", "--all")
        _state(driver, {})
