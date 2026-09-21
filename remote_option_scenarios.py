# SPDX-License-Identifier: LGPL-2.1-or-later
"""CLI remote options observed through selection, visibility and verified installs."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from install_option_scenarios import _clear, _state

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    root = Path(fixture["directory"])
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    repository.version = "A"

    def install(remote: str, ref: str = app) -> None:
        driver.cli_success("install", "--user", "--noninteractive", remote, ref)

    def reject(remote: str) -> None:
        result = driver.cli_call("install", "--user", "--noninteractive", remote, app)
        _state(driver, {})
        driver.check(result.returncode > 0 and any(
            text in result.stderr.casefold() for text in ("gpg", "signature", "public key")),
                     f"untrusted source must reject installation: {result.stderr}")

    if name == "remote-options-default-branch":
        queries = fixture.get("queries")
        if queries is None:
            raise PrerequisiteError("independent test/master query branches required")
        source = (root / queries["versions"]["A"]["repo"]).as_uri()
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "--default-branch=test",
                           "selection", source)
        for branch in ("test", "master"):
            if branch == "master":
                driver.cli_success("remote-modify", "--user", "--default-branch=master",
                                   "selection")
            install("selection", queries["app"])
            selected = f"app/{queries['app']}/{fixture['arch']}/{branch}"
            _state(driver, {selected: queries["versions"]["A"]["refs"][selected]["commit"],
                            runtime: fixture["runtime_commit"]})
            _clear(driver)
        return

    if name == "remote-options-add-disabled":
        driver.cli_success("remote-add", "--user", "--disable", "--no-gpg-verify", "selection", url)
        driver.check(driver.cli_success("remotes", "--user", "--columns=name") == "",
                     "disabled remote must be absent from ordinary enumeration")
        driver.check(driver.cli_success("remotes", "--user", "--show-disabled", "--columns=name") ==
                     "selection", "disabled remote must remain configured")
        options = driver.cli_success("remotes", "--user", "--show-disabled", "--columns=options")
        driver.check("disabled" in options.split(","), "added remote must persist disabled state")
        driver.cli_success("remote-modify", "--user", "--enable", "selection")
        install("selection")
        _state(driver, {app: fixture["commits"]["A"], runtime: fixture["runtime_commit"]})
        return

    if name == "remote-options-add-filter":
        path = driver.root / "selection.filter"
        path.write_text(f"deny *\nallow {runtime}\n", encoding="utf-8")
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", f"--filter={path}",
                           "selection", url)
        rows = driver.cli_success("remote-ls", "--user", "--columns=ref", "selection").splitlines()
        driver.check(rows == [runtime], f"filter must expose only the runtime: {rows}")
        result = driver.cli_call("install", "--user", "--noninteractive", "selection", app)
        _state(driver, {})
        driver.check(result.returncode > 0 and fixture["app"] in result.stderr and any(
            text in result.stderr.casefold()
            for text in ("no remote refs found", "nothing matches", "filtered")),
            f"filtered app must be rejected during ref resolution: {result.stderr}")
        install("selection", runtime)
        _state(driver, {runtime: fixture["runtime_commit"]})
        driver.cli_success("remote-modify", "--user", "--no-filter", "selection")
        install("selection")
        _state(driver, {app: fixture["commits"]["A"], runtime: fixture["runtime_commit"]})
        return

    if name == "remote-options-add-no-gpg-verify":
        strict = driver.cli_call("remote-add", "--user", "strict", url)
        if strict.returncode == 0:
            reject("strict")
        else:
            driver.check(strict.returncode > 0 and "gpg" in strict.stderr.lower(),
                         f"strict addition must fail for signature verification: {strict.stderr}")
            _state(driver, {})
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "selection", url)
        install("selection")
        _state(driver, {app: fixture["commits"]["A"], runtime: fixture["runtime_commit"]})
        return

    if name in {"remote-options-add-gpg-import", "remote-options-modify-gpg-import"}:
        build = fixture.get("build")
        if build is None:
            raise PrerequisiteError("independently signed repository and public key required")
        source = (root / build["usb_repo"]).as_uri()
        key = root / build["public_key"]
        # Seed a keyless remote without relying on whether failed remote-add
        # leaves configuration behind after rejecting the signed summary.
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "untrusted", source)
        driver.cli_success("remote-modify", "--user", "--gpg-verify", "untrusted")
        reject("untrusted")
        if name == "remote-options-add-gpg-import":
            driver.cli_success("remote-add", "--user", f"--gpg-import={key}", "selection", source)
            selected_remote = "selection"
        else:
            driver.cli_success("remote-modify", "--user", f"--gpg-import={key}", "untrusted")
            selected_remote = "untrusted"
        install(selected_remote)
        _state(driver, {app: build["usb_commits"]["app"], runtime: build["usb_commits"]["runtime"]})
        # Import must not silently turn verification off. Repoint the trusted
        # remote to an unsigned repo after clearing deployments and require rejection.
        _clear(driver)
        driver.cli_success("remote-modify", "--user", f"--url={url}", selected_remote)
        reject(selected_remote)
        return

    raise ValueError(f"unknown remote option scenario: {name}")
