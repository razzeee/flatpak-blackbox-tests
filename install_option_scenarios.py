# SPDX-License-Identifier: LGPL-2.1-or-later
"""CLI dependency and payload selection using independently exported fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from fixture_manifest import FixtureContracts, FixtureManifest, FixtureQueries
from json_validation import json_value

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def _state(driver: Driver, expected: dict[str, str]) -> None:
    rows = driver.cli_success("list", "--user", "--all", "--columns=ref").splitlines()
    short = {ref.split("/", 1)[1] for ref in expected}
    driver.check(len(rows) == len(short) and set(rows) == short,
                 f"exact installed refs: expected {sorted(short)}, got {rows}")
    for ref, commit in sorted(expected.items()):
        driver.query(ref, commit)


def _clear(driver: Driver) -> None:
    driver.cli_success("uninstall", "--user", "--noninteractive", "--all")
    _state(driver, {})


def _includes(driver: Driver, root: Path, contracts: FixtureContracts, *,
              mode: Literal["fresh", "current", "update"]) -> None:
    refs, commits = contracts["refs"], contracts["commits"]["A"]
    alias = "one" if mode == "fresh" else "two"
    app = refs[alias]
    base = {app, refs["platform"], refs["extension"], refs["shared"]}
    driver.check(refs["sdk"] != refs["platform"], "SDK must differ from runtime")
    if mode == "update":
        driver.check(commits[app] != contracts["commits"]["APP"][app],
                     "existing-app inclusion requires an independently updated app commit")
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "selection",
                       (root / contracts["repos"]["A"]).as_uri())
    for sdk, debug in ((False, False), (True, False), (False, True), (True, True)):
        _state(driver, {})
        driver.evidence.append({"observation": "SDK/debug selection variant", "data": {
            "mode": mode, "sdk": sdk, "debug": debug,
        }})
        if mode != "fresh":
            driver.cli_success("remote-modify", "--user",
                               f"--url={(root / contracts['repos']['A']).as_uri()}", "selection")
            driver.cli_success("install", "--user", "--noninteractive", "selection", app)
            _state(driver, {ref: commits[ref] for ref in base})
            if mode == "update":
                driver.cli_success("remote-modify", "--user",
                                   f"--url={(root / contracts['repos']['APP']).as_uri()}",
                                   "selection")
        options = []
        expected = base.copy()
        if sdk:
            options.append("--include-sdk")
            expected.add(refs["sdk"])
        if debug:
            options.append("--include-debug")
            expected.update({refs[f"{alias}_debug"], refs["platform_debug"]})
            if sdk:
                expected.add(refs["sdk_debug"])
        driver.cli_success("install", "--user", "--noninteractive", *options, "selection", app)
        # Inclusion options imply --or-update; an ordinary repeated install
        # instead leaves the already-installed app at A.
        selected = contracts["commits"]["APP"] if mode == "update" and options else commits
        _state(driver, {ref: selected[ref] for ref in expected})
        _clear(driver)


def _subpaths(driver: Driver, root: Path, queries: FixtureQueries, arch: str,
              *, update: bool) -> None:
    ref = f"runtime/{queries['extension']}/{arch}/test"
    versions = queries["versions"]
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "selection",
                       (root / versions["A"]["repo"]).as_uri())

    def switch(version: str) -> None:
        driver.cli_success("remote-modify", "--user",
                           f"--url={(root / versions[version]['repo']).as_uri()}", "selection")

    def payloads(version: str, expected: set[str]) -> None:
        _state(driver, {ref: versions[version]["refs"][ref]["commit"]})
        location = Path(driver.cli_success("info", "--user", "--show-location", ref))
        driver.check(location.is_absolute() and location.resolve().is_relative_to(driver.root),
                     "public deployment location must be inside isolated state")
        candidates = {"bin": location / "files/bin/probe",
                      "subset-control": location / "files/subset-control/payload"}
        actual = {name for name, path in candidates.items() if path.is_file()}
        driver.evidence.append({"observation": "CLI deployed subpaths", "data": json_value({
            "ref": ref, "version": version, "location": str(location),
            "expected": sorted(expected), "actual": sorted(actual),
        })})
        driver.check(actual == expected,
                     "deployed payload selection: "
                     f"expected {sorted(expected)}, got {sorted(actual)}")
        if "subset-control" in expected:
            driver.check(candidates["subset-control"].read_text() ==
                         "Independent full-install payload\n", "independent marker bytes")

    if not update:
        for options, expected in (
            (("--subpath=/bin",), {"bin"}),
            (("--subpath=/subset-control",), {"subset-control"}),
            (("--subpath=/bin", "--subpath=/subset-control"), {"bin", "subset-control"}),
            ((), {"bin", "subset-control"}),
        ):
            _state(driver, {})
            driver.cli_success("install", "--user", "--noninteractive", *options, "selection", ref)
            payloads("A", expected)
            _clear(driver)
        return

    driver.check(versions["A"]["refs"][ref]["commit"] != versions["B"]["refs"][ref]["commit"],
                 "subpath update requires distinct independently prepared A/B commits")
    for options, expected in (
        ((), {"bin"}),
        (("--subpath=/subset-control",), {"subset-control"}),
        (("--subpath=/bin", "--subpath=/subset-control"), {"bin", "subset-control"}),
    ):
        _state(driver, {})
        switch("A")
        driver.cli_success("install", "--user", "--noninteractive", "--subpath=/bin",
                           "selection", ref)
        payloads("A", {"bin"})
        switch("B")
        driver.cli_success("update", "--user", "--noninteractive", *options, ref)
        payloads("B", expected)
        # Force another deployment without --subpath. A same-commit no-op
        # would not establish that the subset survives a subsequent update.
        driver.cli_success("update", "--user", "--noninteractive",
                           f"--commit={versions['A']['refs'][ref]['commit']}", ref)
        payloads("A", expected)
        _clear(driver)


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    del repository, url
    root = Path(fixture["directory"])
    if name in {"install-options-sdk-debug", "install-options-sdk-debug-current",
                "install-options-sdk-debug-existing"}:
        contracts = fixture.get("contracts")
        if contracts is None:
            raise PrerequisiteError("independent SDK and debug contract fixtures required")
        mode: Literal["fresh", "current", "update"] = "fresh"
        if name.endswith("-current"):
            mode = "current"
        elif name.endswith("-existing"):
            mode = "update"
        _includes(driver, root, contracts, mode=mode)
    elif name in {"install-options-subpath", "update-options-subpath"}:
        queries = fixture.get("queries")
        if queries is None:
            raise PrerequisiteError("independent query fixtures with subset-control required")
        _subpaths(driver, root, queries, fixture["arch"], update=name == "update-options-subpath")
    else:
        raise ValueError(f"unknown install option scenario: {name}")
