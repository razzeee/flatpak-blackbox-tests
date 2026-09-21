# SPDX-License-Identifier: LGPL-2.1-or-later
"""USB export selection, partial payloads and diagnostics through public OSTree refs."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from build_scenarios import _ostree
from fixture_manifest import FixtureManifest
from install_option_scenarios import _state
from system_selector_scenarios import FIXTURES, SELECTORS, Namespace

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def _refs(driver: Driver, repo: Path, collection: str, expected: dict[str, str]) -> None:
    output = _ostree(driver, repo, "refs", "--collections", "--revision")
    actual = {}
    for line in output.splitlines():
        match = re.fullmatch(r"\(([^,]+), (.+)\)\t([a-f0-9]{64})", line)
        driver.check(match is not None, f"public USB ref identity is malformed: {line}")
        assert match is not None
        owner, ref, commit = match.groups()
        if ref.startswith(("app/", "runtime/")):
            driver.check(owner == collection, "export must retain independent collection identity")
            driver.check(ref not in actual, "exported refs must not be duplicated")
            actual[ref] = commit
    driver.check(actual == expected, f"exported refs/commits: expected {expected}, got {actual}")


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    del repository, url
    build = fixture.get("build")
    if build is None:
        raise PrerequisiteError("independent signed collection repository required")
    root = Path(fixture["directory"])
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    collection = build["collection_id"]
    if name == "usb-options-selectors":
        inputs = fixture.get("lifecycle_extra")
        if inputs is None or "sideload_update_repo" not in inputs:
            raise PrerequisiteError("independent signed B app source required")
        state = driver.root / "system-selector-state"
        try:
            ns = Namespace(driver, root)
            for scope in SELECTORS:
                source = (inputs["sideload_update_repo"] if scope == "alt" else build["usb_repo"])
                ns.ok("remote-add", f"--gpg-import={FIXTURES}/{build['public_key']}",
                      f"--collection-id={collection}", "fixture", f"file://{FIXTURES}/{source}",
                      scope=scope)
                ns.ok("install", "--noninteractive", "fixture", app, scope=scope)
                ns.ok("install", "--noninteractive", "fixture", runtime, scope=scope)
            for scope in SELECTORS:
                mount = state / "var" / f"usb-{scope}"
                mount.mkdir()
                ns.ok("create-usb", "--destination-repo=payload", f"/var/usb-{scope}", app,
                      scope=scope)
                commit = (inputs["sideload_update_commit"] if scope == "alt" else
                          build["usb_commits"]["app"])
                _refs(driver, mount / "payload", collection,
                      {app: commit, runtime: build["usb_commits"]["runtime"]})
        finally:
            if state.exists():
                shutil.rmtree(state)
        return

    driver.cli_success("remote-add", "--user", f"--gpg-import={root / build['public_key']}",
                       f"--collection-id={collection}", "fixture",
                       (root / build["usb_repo"]).as_uri())
    if name == "usb-options-partial":
        driver.cli_success("install", "--user", "--noninteractive", "--subpath=/bin",
                           "fixture", runtime)
        commit = build["usb_commits"]["runtime"]
        _state(driver, {runtime: commit})
        mount = driver.root / "partial-export"
        mount.mkdir()
        ordinary = driver.cli_call("create-usb", "--user", "--destination-repo=ordinary",
                                   str(mount), runtime)
        allowed = driver.cli_call("create-usb", "--user", "--allow-partial",
                                  "--destination-repo=allowed", str(mount), runtime)
        warning = [line for line in ordinary.stderr.splitlines()
                   if "warning" in line.lower() and "partially installed" in line.lower()]
        driver.check(bool(warning), "ordinary partial export must warn about incomplete content")
        driver.check(not any("partially installed" in line.lower()
                             for line in allowed.stderr.splitlines()),
                     "allow-partial must suppress the partial-content warning")
        driver.check(ordinary.returncode == allowed.returncode,
                     "warning suppression must not change the export outcome")
        remaining = [line for line in ordinary.stderr.splitlines() if line not in warning]
        driver.check(remaining == allowed.stderr.splitlines(),
                     "warning suppression must preserve unrelated diagnostics")
        # This option is documented as warning suppression, not permission to
        # export. Preserve evidence of any independent partial-export failure.
        if allowed.returncode != 0:
            driver.check("not installed" in allowed.stderr and runtime in allowed.stderr,
                         f"unexpected partial export failure: {allowed.stderr}")
            driver.evidence.append({"observation": "partial USB export result", "data": {
                "export_succeeded": False, "warning_suppression_verified": True,
                "error": allowed.stderr,
            }})
            driver.cli_success("uninstall", "--user", "--noninteractive", runtime)
            driver.cli_success("install", "--user", "--noninteractive", "fixture", runtime)
            driver.cli_success("create-usb", "--user", "--destination-repo=full",
                               str(mount), runtime)
            _refs(driver, mount / "full", collection, {runtime: commit})
            return
        repo = mount / "allowed"
        _refs(driver, repo, collection, {runtime: commit})
        checkout = driver.root / "partial-bin"
        _ostree(driver, repo, "checkout", "--user-mode", "--subpath=/files/bin",
                commit, str(checkout))
        original = root / fixture["assets"]["runtime_tree"] / "usr/bin/blackbox-probe"
        driver.check((checkout / "blackbox-probe").read_bytes() ==
                     original.read_bytes(),
                     "partial export must retain independently prepared selected payload bytes")
        omitted = driver.external_call([
            "ostree", f"--repo={repo}", "checkout", "--user-mode", "--subpath=/files/lib",
            commit, str(driver.root / "missing-libs"),
        ], "setup")
        driver.check(omitted.returncode != 0, "partial export must not invent uncached libraries")
        return

    driver.cli_success("install", "--user", "--noninteractive", "fixture", app)
    all_refs = {app: build["usb_commits"]["app"], runtime: build["usb_commits"]["runtime"]}
    if name == "usb-options-kinds":
        for kind in ("app", "runtime"):
            mount = driver.root / f"usb-{kind}"
            mount.mkdir()
            identity = fixture["app"] if kind == "app" else fixture["runtime"]
            other = fixture["runtime"] if kind == "app" else fixture["app"]
            wrong = driver.cli_call("create-usb", "--user", f"--{kind}",
                                    "--destination-repo=wrong-kind", str(mount), other)
            driver.check(wrong.returncode != 0 and "not installed" in wrong.stderr.lower(),
                         "kind selection must reject an installed ref of the opposite kind")
            driver.cli_success("create-usb", "--user", f"--{kind}", "--destination-repo=payload",
                               str(mount), identity)
            expected = all_refs if kind == "app" else {runtime: build["usb_commits"]["runtime"]}
            _refs(driver, mount / "payload", collection, expected)
        return
    if name != "usb-options-diagnostics":
        raise ValueError(f"unknown USB option scenario: {name}")
    mount = driver.root / "diagnostic-export"
    for option in ("--verbose", "--ostree-verbose"):
        results = []
        for flags in ((), (option,), ()):
            if mount.exists():
                shutil.rmtree(mount)
            mount.mkdir()
            result = driver.cli_call("create-usb", "--user", *flags, "--destination-repo=payload",
                                     str(mount), app)
            driver.check(result.returncode == 0, f"USB diagnostic export failed: {result.stderr}")
            _refs(driver, mount / "payload", collection, all_refs)
            results.append(result)
        before, verbose, after = results
        driver.check(before.stdout == verbose.stdout == after.stdout and
                     before.stderr == after.stderr,
                     "USB diagnostics preserve ordinary output and stable quiet controls")
        driver.check(bool(set(verbose.stderr.splitlines()) - set(before.stderr.splitlines())),
                     f"USB {option} must add diagnostic lines")
