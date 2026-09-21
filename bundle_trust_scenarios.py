# SPDX-License-Identifier: LGPL-2.1-or-later
"""Bundle trust options checked through signature rejection and update policy."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from install_option_scenarios import _state

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    repository.version = "A"
    inputs = fixture.get("build")
    if inputs is None:
        raise PrerequisiteError("independent signed/unsigned bundle inputs and public key required")
    root = Path(fixture["directory"])
    key = root / inputs["public_key"]
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    base = {runtime: fixture["runtime_commit"]}
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "runtime-source", url)
    driver.cli_success("install", "--user", "--noninteractive", "runtime-source", runtime)

    if name == "bundle-trust-install-key":
        lifecycle = fixture.get("lifecycle_extra")
        if lifecycle is None:
            raise PrerequisiteError("independently signed native bundle required")
        unsigned = root / inputs["bundle"]
        rejected = driver.cli_call("install", "--user", "--noninteractive", f"--gpg-file={key}",
                                   "--bundle", str(unsigned))
        driver.check(rejected.returncode != 0 and any(
            word in rejected.stderr.lower() for word in ("gpg", "signature")),
            "a valid verification key must reject the independently unsigned bundle")
        _state(driver, base)
        driver.cli_success("install", "--user", "--noninteractive", "--bundle", str(unsigned))
        _state(driver, {**base, app: fixture["commits"]["A"]})
        driver.cli_success("uninstall", "--user", "--noninteractive", app)
        signed_result = driver.cli_call(
            "install", "--user", "--noninteractive", f"--gpg-file={key}",
            "--bundle", str(root / lifecycle["signed_bundle"]))
        driver.check(signed_result.returncode == 0,
                     f"signed bundle verification exited {signed_result.returncode}: "
                     f"{signed_result.stderr}")
        _state(driver, {**base, app: fixture["commits"]["B"]})
        return
    if name != "bundle-trust-embedded-key":
        raise ValueError(f"unknown bundle trust scenario: {name}")
    signed = root / inputs["signed_repo"]
    for embedded in (False, True):
        bundle = driver.root / f"bundle-{embedded}.flatpak"
        options = (f"--gpg-keys={key}",) if embedded else ()
        driver.cli_success("build-bundle", *options, f"--repo-url={signed.as_uri()}",
                           str(signed), str(bundle), fixture["app"], fixture["branch"])
        driver.cli_success("install", "--user", "--noninteractive", "--bundle", str(bundle))
        _state(driver, {**base, app: fixture["commits"]["B"]})
        origin = driver.cli_success("info", "--user", "--show-origin", app)
        driver.check(bool(origin) and origin != "runtime-source", "bundle has its own origin")
        driver.cli_success("remote-modify", "--user", f"--url={url}", origin)
        result = driver.cli_call("update", "--user", "--noninteractive",
                                 f"--commit={fixture['commits']['A']}", app)
        if embedded:
            driver.check(result.returncode != 0 and any(
                word in result.stderr.lower() for word in ("gpg", "signature")),
                "embedded key must retain verification and reject an unsigned origin update")
            _state(driver, {**base, app: fixture["commits"]["B"]})
        else:
            driver.check(result.returncode == 0, f"keyless bundle update control: {result.stderr}")
            _state(driver, {**base, app: fixture["commits"]["A"]})
        driver.cli_success("uninstall", "--user", "--noninteractive", app)
        if origin in driver.cli_success("remotes", "--user", "--columns=name").splitlines():
            driver.cli_success("remote-delete", "--user", origin)
        _state(driver, base)
