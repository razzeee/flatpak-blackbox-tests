# SPDX-License-Identifier: LGPL-2.1-or-later
"""Observe extension data inside the app, independently of related-ref enumeration."""

from __future__ import annotations

import configparser
from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    queries = fixture.get("queries")
    if queries is None or "extension_mounts" not in queries:
        raise PrerequisiteError("independent extension mount fixtures required")
    mounts = queries["extension_mounts"]
    app, extension = mounts["app"], mounts["extension"]
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    if name not in {"extension-mount-same-origin", "extension-mount-remote-alias",
                    "extension-mount-separate-repos"}:
        raise ValueError(f"unknown extension mount scenario: {name}")
    separate = name == "extension-mount-separate-repos"
    origin = "queries" if name == "extension-mount-same-origin" else "extensions"
    root = Path(fixture["directory"])
    app_repo = root / mounts["app_repo" if separate else "combined_repo"]
    extension_repo = root / mounts["extension_repo"] if separate else app_repo
    commit = mounts["separate_commit" if separate else "combined_commit"]
    marker = mounts["separate_marker" if separate else "combined_marker"]
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "queries", app_repo.as_uri())
    if origin != "queries":
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", origin,
                           extension_repo.as_uri())

    # Verify the independently prepared inventories, not just remote labels.
    def available(remote: str, expected: set[str]) -> None:
        refs = driver.cli_success("remote-ls", "--user", "--columns=ref", remote).splitlines()
        driver.check(len(refs) == len(expected) and set(refs) == expected,
                     f"{remote} available refs: expected {sorted(expected)}, got {refs}")

    available("queries", {app, runtime} if separate else {app, runtime, extension})
    if origin != "queries":
        available(origin, {extension} if separate else {app, runtime, extension})
    driver.cli_success("install", "--user", "--noninteractive", "queries", app)

    def state(installed: bool) -> None:
        expected = {app, runtime, extension} if installed else {app, runtime}
        refs = driver.cli_success("list", "--user", "--all", "--columns=ref").splitlines()
        short = {ref.split("/", 1)[1] for ref in expected}
        driver.check(len(refs) == len(short) and set(refs) == short,
                     f"exact installed refs: expected {sorted(short)}, got {refs}")
        driver.query(app, mounts["app_commit"])
        driver.query(runtime, mounts["runtime_commit"])
        # A live default command prevents failed sandbox startup from satisfying absence.
        output = driver.cli_success("run", "--user", app)
        driver.check(output == "A", f"default app command: expected A, got {output!r}")
        if installed:
            driver.query(extension, commit)
            actual_origin = driver.cli_success("info", "--user", "--show-origin", extension)
            driver.check(actual_origin == origin,
                         f"extension origin: expected {origin}, got {actual_origin}")
            content = driver.cli_success("run", "--user", app, "read", "/app/data/marker")
            driver.check(content == marker,
                         f"extension contents: expected {marker!r}, got {content!r}")
        else:
            missing = driver.cli_call("run", "--user", app, "read", "/app/data/marker")
            driver.check(missing.returncode == 1 and
                         "read: No such file or directory" in missing.stderr,
                         f"extension marker must be absent: {missing}")
        info = configparser.ConfigParser(interpolation=None)
        info.read_string(driver.cli_success("run", "--user", app, "read", "/.flatpak-info"))
        extensions = info.get("Instance", "app-extensions", fallback="").split(";")
        driver.check((f"{extension.split('/')[1]}={commit}" in extensions) == installed,
                     f"sandbox extension commit: installed={installed}, got {extensions}")
        mountinfo = driver.cli_success("run", "--user", app, "read", "/proc/self/mountinfo")
        bindings = [line.split() for line in mountinfo.splitlines()
                    if len(line.split()) > 5 and line.split()[4] == "/app/data"]
        driver.check(bool(bindings) == installed,
                     f"sandbox extension mount: installed={installed}, got {bindings}")
        if installed:
            driver.check(len(bindings) == 1 and "ro" in bindings[0][5].split(","),
                         f"extension mount must be read-only: {bindings}")

    state(False)
    driver.cli_success("install", "--user", "--noninteractive", origin, extension)
    state(True)
    driver.cli_success("uninstall", "--user", "--noninteractive", "--no-related", extension)
    state(False)
