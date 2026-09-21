# SPDX-License-Identifier: LGPL-2.1-or-later
"""Accessibility bus grants against an independent private address provider."""

from __future__ import annotations

import shlex
import subprocess
import sysconfig
import time
from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from sandbox_scenarios import _external_service

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    if name != "accessibility-options":
        raise ValueError(f"unknown accessibility scenario: {name}")
    if not Path("/usr/bin/dbus-send").is_file():
        raise PrerequisiteError("independent D-Bus client required")
    repository.version = "A"
    app = fixture["app"]
    driver.env.pop("AT_SPI_BUS_ADDRESS", None)
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture", url)
    driver.cli_success("install", "--user", "--noninteractive", "fixture", app)
    binary = driver.root / "a11y-provider"
    flags = shlex.split(subprocess.check_output(
        ["pkg-config", "--cflags", "--libs", "gio-2.0"], text=True))
    result = driver.external_call([
        "cc", "-Wall", "-Wextra", "-Werror", "-O2",
        str(Path(__file__).with_name("fixture-a11y-service.c")), "-o", str(binary), *flags,
    ], "setup")
    driver.check(result.returncode == 0, f"independent address provider build: {result.stderr}")
    with _external_service(driver, str(binary), driver.env["DBUS_SESSION_BUS_ADDRESS"]) as service:
        deadline = time.monotonic() + 10
        while True:
            owner = driver.external_call([
                "gdbus", "call", "--session", "--dest", "org.freedesktop.DBus", "--object-path",
                "/org/freedesktop/DBus", "--method", "org.freedesktop.DBus.NameHasOwner",
                "org.a11y.Bus",
            ], "setup")
            if owner.returncode == 0 and owner.stdout.strip() == "(true,)":
                break
            driver.check(service.poll() is None and time.monotonic() < deadline,
                         "private accessibility address provider must become available")
            time.sleep(0.02)
        enabled = ("--no-a11y-bus", "--a11y-bus")
        address = driver.cli_success("run", "--user", *enabled, app, "env", "AT_SPI_BUS_ADDRESS")
        driver.check(address.startswith("unix:path="), "enabled a11y bus has a socket address")
        socket = address.removeprefix("unix:path=")
        exposed = driver.cli_success("run", "--user", *enabled, app, "exists", socket)
        driver.check(exposed == "exists",
                     "explicit re-enablement exposes a real bus socket")
        denied = driver.cli_call("run", "--user", "--a11y-bus", "--no-a11y-bus", app,
                                 "exists", socket)
        driver.check(denied.returncode == 1 and denied.stderr.startswith("exists:"),
                     "disabling accessibility must remove the actual sandbox socket")
        libraries = ["/run/host/usr/lib64", "/run/host/usr/lib"]
        multiarch = sysconfig.get_config_var("MULTIARCH")
        if isinstance(multiarch, str) and (Path("/usr/lib") / multiarch).is_dir():
            libraries.insert(0, f"/run/host/usr/lib/{multiarch}")
        owner_name = "org.blackbox.Accessibility"

        def own(*options: str) -> subprocess.CompletedProcess[str]:
            return driver.cli_call(
                "run", "--user", *enabled, "--filesystem=host-os:ro",
                f"--env=LD_LIBRARY_PATH={':'.join(libraries)}", *options,
                "--command=/run/host/usr/bin/dbus-send", app, f"--bus={address}", "--print-reply",
                "--reply-timeout=2000", "--dest=org.freedesktop.DBus", "/org/freedesktop/DBus",
                "org.freedesktop.DBus.RequestName", f"string:{owner_name}", "uint32:4")

        variants = (((), False), ((f"--a11y-own-name={owner_name}",), True), ((), False))
        for options, allowed in variants:
            response = own(*options)
            if allowed:
                acquired = any(line.strip() == "uint32 1" for line in response.stdout.splitlines())
                driver.check(response.returncode == 0 and acquired,
                             f"a11y grant must acquire the requested name: {response.stderr}")
            else:
                driver.check(response.returncode != 0 and any(
                    error in response.stderr for error in ("AccessDenied", "ServiceUnknown")),
                             f"ungranted accessibility ownership must be denied: {response.stderr}")
