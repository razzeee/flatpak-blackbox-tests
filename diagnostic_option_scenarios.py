# SPDX-License-Identifier: LGPL-2.1-or-later
"""Observable verbosity changes, with quiet controls and unchanged public state."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from install_option_scenarios import _state
from json_validation import json_value

if TYPE_CHECKING:
    import subprocess

    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    command = name.removeprefix("diagnostic-options-")
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    expected = {app: fixture["commits"]["A"], runtime: fixture["runtime_commit"]}
    repository.version = "A"
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "--title=Diagnostic remote",
                       "fixture", url)
    driver.cli_success("install", "--user", "--noninteractive", "fixture", app)
    driver.cli_success("config", "--user", "--set", "languages", "fr")

    arguments: dict[str, tuple[str, ...]] = {
        "info": ("--user", "--show-commit", app),
        "list": ("--user", "--columns=ref"),
        "remotes": ("--user", "--columns=name,url,title"),
        "remote-info": ("--user", "--show-commit", "fixture", app),
        "remote-ls": ("--user", "--columns=ref", "fixture"),
        "config": ("--user", "--get", "languages"),
        "override": ("--user", "--show", fixture["app"]),
        "mask": ("--user",),
        "pin": ("--user",),
        "update": ("--user", "--noninteractive", app),
        "install": ("--user", "--noninteractive", "--or-update", "fixture", app),
        "uninstall": ("--user", "--noninteractive", app),
        "remote-add": ("--user", "--if-not-exists", "--no-gpg-verify", "fixture", url),
        "remote-modify": ("--user", "--title=Diagnostic remote", "fixture"),
        "remote-delete": ("--user", "temporary"),
        "make-current": ("--user", fixture["app"], fixture["branch"]),
        "repair": ("--user", "--dry-run"),
        "repo": ("--info", str(Path(fixture["directory"]) / "A")),
    }
    if command not in arguments:
        raise ValueError(f"unknown diagnostic scenario: {name}")
    options: tuple[str, ...] = ("--verbose", "--ostree-verbose")
    if command in {"mask", "pin"}:
        options = ("--verbose",)
    elif command in {"info", "repo"}:
        options = ("--ostree-verbose",)

    def invoke(option: str | None) -> subprocess.CompletedProcess[str]:
        if command == "uninstall":
            driver.cli_success("install", "--user", "--noninteractive", "fixture", app)
        elif command == "remote-delete":
            driver.cli_success("remote-add", "--user", "--no-gpg-verify", "temporary", url)
        _state(driver, expected)
        flags = (option,) if option is not None else ()
        result = driver.cli_call(command, *flags, *arguments[command])
        driver.check(result.returncode == 0,
                     f"{command} {option or 'quiet'} failed: {result.stderr}")
        after = {runtime: fixture["runtime_commit"]} if command == "uninstall" else expected
        _state(driver, after)
        remotes = driver.cli_success("remotes", "--user", "--columns=name,url,title")
        driver.check(remotes == f"fixture\t{url}\tDiagnostic remote",
                     f"diagnostic command must preserve the fixture remote: {remotes!r}")
        return result

    for option in options:
        before = invoke(None)
        diagnostic = invoke(option)
        after = invoke(None)
        driver.check(before.stdout == diagnostic.stdout == after.stdout,
                     f"{command} {option} must preserve ordinary stdout")
        driver.check(before.stderr == after.stderr,
                     f"{command} quiet stderr must be stable around the diagnostic invocation")
        extra = set(diagnostic.stderr.splitlines()) - set(before.stderr.splitlines())
        driver.evidence.append({"observation": "additional diagnostic lines", "data": json_value({
            "command": command, "option": option, "lines": sorted(extra),
        })})
        driver.check(any(line.strip() for line in extra),
                     f"{command} {option} must add diagnostics beyond the quiet controls")
