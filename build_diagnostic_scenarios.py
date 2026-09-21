# SPDX-License-Identifier: LGPL-2.1-or-later
"""Build diagnostics with recreated inputs and independently inspected outputs."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from build_scenarios import _key_home, _metadata, _ostree, _ref, _verify_signature
from fixture_manifest import FixtureManifest
from json_validation import json_value

if TYPE_CHECKING:
    import subprocess

    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    del repository
    sync = name.startswith("build-sync-")
    command = name.removeprefix("build-sync-" if sync else "build-diagnostics-")
    supported = {"build-init", "build-finish", "build-export", "build-bundle",
                 "build-import-bundle", "build-commit-from", "build-sign", "build-update-repo"}
    if command not in supported:
        raise ValueError(f"unknown build diagnostic scenario: {name}")
    if "build" not in fixture:
        raise PrerequisiteError("independent distribution inputs and signing key required")
    root = Path(fixture["directory"])
    work = driver.root / "diagnostic-work"
    home = _key_home(driver, fixture) if command == "build-sign" else None
    if sync and shutil.which("strace") is None:
        raise PrerequisiteError("strace is required to observe filesystem synchronization")
    sync_counts: list[int] = []
    ref = _ref(fixture)
    if command == "build-init":
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture", url)
        driver.cli_success("install", "--user", "--noninteractive", "fixture", _ref(fixture, True))

    def invoke(option: str | None) -> subprocess.CompletedProcess[str]:
        if work.exists():
            shutil.rmtree(work)
        work.mkdir()
        tree, repo = work / "tree", work / "repo"
        args: tuple[str, ...]
        if command in {"build-finish", "build-export"}:
            shutil.copytree(root / fixture["assets"]["app_tree"], tree, symlinks=True)
            if command == "build-finish":
                shutil.rmtree(tree / "export")
                args = (str(tree),)
            else:
                args = ("--disable-sandbox", "--timestamp=2020-01-02T03:04:05Z",
                        str(repo), str(tree), fixture["branch"])
        elif command == "build-init":
            args = (str(tree), fixture["app"], fixture["runtime"], fixture["runtime"],
                    fixture["branch"])
        elif command == "build-bundle":
            args = (str(root / "A"), str(work / "app.flatpak"), fixture["app"], fixture["branch"])
        elif command == "build-import-bundle":
            _ostree(driver, repo, "init", "--mode=archive")
            args = (str(repo), str(root / fixture["build"]["bundle"]))
        elif command == "build-commit-from":
            _ostree(driver, repo, "init", "--mode=archive")
            args = (f"--src-repo={root / 'A'}", "--timestamp=2020-01-02T03:04:05Z",
                    str(repo), ref)
        else:
            shutil.copytree(root / "A", repo, symlinks=True)
            args = (str(repo),)
            if command == "build-sign":
                args = (f"--gpg-homedir={home}", f"--gpg-sign={fixture['build']['key_id']}",
                        str(repo), fixture["app"], fixture["branch"])
        flags = () if option is None else (option,)
        if sync:
            trace = work / "sync.trace"
            result = driver.external_call([
                "strace", "-f", "-qq", "-e", "trace=fsync,fdatasync", "-o", str(trace),
                driver.cli, command, *flags, *args,
            ], "cli")
            text = trace.read_text()
            completed = (r"(?:\b(?:fsync|fdatasync)\([^\n)]*\)|"
                         r"<\.\.\. (?:fsync|fdatasync) resumed>[^\n=]*)\s+=\s+0\b")
            count = len(re.findall(completed, text))
            sync_counts.append(count)
            driver.evidence.append({"observation": "filesystem synchronization calls", "data": {
                "command": command, "option": option, "successful_calls": count, "trace": text,
            }})
        else:
            result = driver.cli_call(command, *flags, *args)
        driver.check(result.returncode == 0, f"{command} {option}: {result.stderr}")
        if command in {"build-init", "build-finish"}:
            driver.check(_metadata(tree).get("Application", "name") == fixture["app"],
                         "build metadata must retain the independent app identity")
            if command == "build-finish":
                driver.check((tree / "export").is_dir(), "finish must create the public export dir")
        elif command == "build-bundle":
            _ostree(driver, repo, "init", "--mode=archive")
            _ostree(driver, repo, "static-delta", "apply-offline", str(work / "app.flatpak"))
            _ostree(driver, repo, "show", fixture["commits"]["A"])
        else:
            if command in {"build-import-bundle", "build-sign", "build-update-repo"}:
                driver.check(_ostree(driver, repo, "rev-parse", ref) == fixture["commits"]["A"],
                             "diagnostics must preserve the independent app commit")
            else:
                metadata = root / fixture["assets"]["app_tree"] / "metadata"
                driver.check(_ostree(driver, repo, "cat", ref, "/metadata") ==
                             metadata.read_text().strip(),
                             "export/promotion must retain independent app metadata")
                checkout = work / "checkout"
                _ostree(driver, repo, "checkout", "--user-mode", ref, str(checkout))
                driver.check((checkout / "files/bin/blackbox-probe").read_bytes() ==
                             (root / fixture["assets"]["app_tree"] /
                              "files/bin/blackbox-probe").read_bytes(),
                             "export/promotion must retain the independent executable bytes")
            if command == "build-sign":
                _verify_signature(driver, fixture, repo, ref)
            _ostree(driver, repo, "fsck")
        return result

    try:
        if sync:
            before, disabled, after = invoke(None), invoke("--disable-fsync"), invoke(None)
            driver.check(before.stdout == disabled.stdout == after.stdout,
                         "disabling synchronization must preserve ordinary build output")
            first, reduced, last = sync_counts
            driver.check(first == last and first > reduced,
                         f"disable-fsync must reduce sync calls between controls: {sync_counts}")
            return
        options: tuple[str, ...] = ("--verbose", "--ostree-verbose")
        if command in {"build-init", "build-bundle", "build-sign"}:
            options = ("--ostree-verbose",)
        elif command == "build-finish":
            options = ("--verbose",)
        for option in options:
            before, verbose, after = invoke(None), invoke(option), invoke(None)
            extra = set(verbose.stderr.splitlines()) - set(before.stderr.splitlines())
            driver.check(before.stdout == verbose.stdout == after.stdout,
                         f"{command} diagnostics must preserve ordinary stdout")
            driver.check(before.stderr == after.stderr,
                         f"{command} quiet diagnostic controls must match")
            driver.check(any(line.strip() for line in extra),
                         f"{command} {option} must add diagnostics beyond quiet controls")
            driver.evidence.append({"observation": "build diagnostic lines", "data": json_value({
                "command": command, "option": option, "additional_lines": sorted(extra),
            })})
    finally:
        if home is not None:
            result = driver.external_call(
                ["gpgconf", "--homedir", str(home), "--kill", "gpg-agent"], "setup")
            driver.check(result.returncode == 0, f"signing agent cleanup failed: {result.stderr}")
