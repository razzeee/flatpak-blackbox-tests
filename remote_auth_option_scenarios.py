# SPDX-License-Identifier: LGPL-2.1-or-later
"""Remote authentication settings observed through wire requests and deployments."""

from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

from auth_scenarios import protected_server
from fixture_manifest import FixtureManifest
from install_option_scenarios import _state
from sandbox_scenarios import _external_service

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    del repository, url
    extra = fixture.get("extras", {}).get("auth")
    if extra is None:
        raise PrerequisiteError("independent protected authentication inputs required")
    adding = name.endswith("-add")
    automatic = "autoinstall" in name
    if name not in {"remote-auth-options-add", "remote-auth-options-modify",
                    "remote-auth-autoinstall-add", "remote-auth-autoinstall-modify"}:
        raise ValueError(f"unknown remote authentication scenario: {name}")
    directory = Path(fixture["directory"]) / extra["directory"] / "repo"
    with protected_server(driver, directory, extra["payloads"]) as (source, requests):
        def configure(*options: str) -> None:
            if adding:
                driver.cli_success("remote-add", "--user", "--no-gpg-verify", *options,
                                   "fixture", source)
            else:
                driver.cli_success("remote-add", "--user", "--no-gpg-verify",
                                   "--authenticator-name=org.blackbox.Absent",
                                   "--authenticator-option=blackbox=wrong", "fixture", source)
                driver.cli_success("remote-modify", "--user", *options, "fixture")

        if automatic:
            if "authenticator_runtime_ref" not in extra:
                raise PrerequisiteError("independent installable authenticator/runtime required")
            candidate = extra["authenticator_ref"]
            for enabled in (False, True):
                flags: tuple[str, ...] = ("--authenticator-install", "--no-authenticator-install")
                if enabled:
                    flags = tuple(reversed(flags))
                configure(f"--authenticator-name={candidate.split('/')[1]}", *flags)
                before = len(requests)
                result = driver.cli_call("install", "--user", "--noninteractive", "fixture",
                                         extra["ref"])
                driver.check(result.returncode != 0,
                             "without a registered activation service authentication must fail")
                expected = ({candidate: extra["authenticator_commit"],
                             extra["authenticator_runtime_ref"]:
                                 extra["authenticator_runtime_commit"]} if enabled else {})
                _state(driver, expected)
                driver.check(not any(request["protected"] for request in requests[before:]),
                             "failed authentication must not download the protected payload")
                if enabled:
                    driver.cli_success("uninstall", "--user", "--noninteractive", "--all")
                    _state(driver, {})
                driver.cli_success("remote-delete", "--user", "fixture")
            return

        # Missing service/name is an ordinary failure, not an authentication
        # success inferred from command acceptance or persisted configuration.
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture", source)
        rejected = driver.cli_call("install", "--user", "--noninteractive", "fixture", extra["ref"])
        driver.check(rejected.returncode != 0, "unconfigured authentication rejects protected refs")
        _state(driver, {})
        driver.cli_success("remote-delete", "--user", "fixture")
        configure("--authenticator-name=org.flatpak.BlackboxAuthenticator",
                  "--authenticator-option=blackbox=obsolete",
                  "--authenticator-option=blackbox=selected=value")
        binary = driver.root / "option-authenticator"
        compiler_flags = shlex.split(subprocess.check_output(
            ["pkg-config", "--cflags", "--libs", "gio-2.0"], text=True))
        compiled = driver.external_call([
            "cc", "-Wall", "-Wextra", "-Werror", "-O2",
            str(Path(__file__).with_name("fixture-auth-service.c")), "-o", str(binary),
            *compiler_flags,
        ], "setup")
        driver.check(compiled.returncode == 0, f"authenticator compile failed: {compiled.stderr}")
        with _external_service(driver, str(binary), "options", extra["ref"], extra["commit"], "",
                               source, "selected=value") as service:
            record = driver.evidence[-1]
            deadline = time.monotonic() + 10
            while True:
                owner = driver.external_call([
                    "gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                    "--object-path", "/org/freedesktop/DBus", "--method",
                    "org.freedesktop.DBus.NameHasOwner", "org.flatpak.BlackboxAuthenticator",
                ], "setup")
                if owner.returncode == 0 and owner.stdout.strip() == "(true,)":
                    break
                driver.check(service.poll() is None and time.monotonic() < deadline,
                             "independent authenticator must acquire its private bus name")
                time.sleep(0.02)
            before = len(requests)
            driver.cli_success("install", "--user", "--noninteractive", "fixture", extra["ref"])
            _state(driver, {extra["ref"]: extra["commit"]})
            transfers = [request for request in requests[before:] if request["protected"]]
            driver.check(bool(transfers) and all(request["authorized"] for request in transfers),
                         "the independently issued token must authorize the protected payload")
        driver.check("auth-option blackbox selected=value\n" in record["stdout"] and
                     "response 0\n" in record["stdout"],
                     "the selected authenticator must receive the final exact option value")
