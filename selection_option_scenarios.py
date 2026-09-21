# SPDX-License-Identifier: LGPL-2.1-or-later
"""Remaining installation selectors, with competing isolated stores."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from build_scenarios import _parse
from fixture_manifest import FixtureManifest
from system_selector_scenarios import FIXTURES, SELECTORS, Namespace

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    del repository, url
    state = driver.root / "system-selector-state"
    driver.check(not state.exists(), "selector state must be fresh")
    try:
        ns = Namespace(driver, Path(fixture["directory"]))
        if name == "selection-options-repair":
            for scope in SELECTORS:
                ns.remote(scope, name=f"{scope}-only")
            for scope in SELECTORS:
                output = ns.ok("repair", "--dry-run", scope=scope)
                words = {word.strip("'\".,:") for word in output.split()}
                driver.check(ns.paths[scope] in words,
                             "repair must identify the independently configured selected root")
                for other in SELECTORS:
                    if other != scope:
                        driver.check(ns.paths[other] not in words,
                                     "selected repair must not traverse a competing installation")
                    ns.equal(ns.refs(other), set(), "repair does not deploy refs")
                    ns.equal(ns.ok("remotes", "--columns=name", scope=other), f"{other}-only",
                             "repair preserves every competing remote")
            rejected = ns.call("repair", "--dry-run", "--installation=absent-selector")
            driver.check(rejected.returncode != 0, "unknown repair installation cannot fall back")
        elif name == "selection-options-make-current":
            queries = fixture.get("queries")
            if queries is None:
                ns.block("independent test/master branch fixtures required")
            source = f"file://{FIXTURES}/{queries['versions']['A']['repo']}"
            app = queries["app"]
            branch_inputs = queries["versions"]["A"]["refs"]
            for scope in SELECTORS:
                ns.ok("remote-add", "--no-gpg-verify", "fixture", source, scope=scope)
                for branch in ("test", "master"):
                    ns.ok("install", "--noninteractive", "fixture",
                          f"app/{app}/{fixture['arch']}/{branch}", scope=scope)
                ns.ok("make-current", app, "master", scope=scope)

            def selected(scope: str, branch: str) -> None:
                info = ns.ok("run", "--command=/usr/bin/blackbox-probe", app, "read",
                             "/.flatpak-info", scope=scope, session=True)
                metadata = _parse(info)
                ref = f"app/{app}/{fixture['arch']}/{branch}"
                ns.equal(metadata.get("Instance", "app-commit"),
                         branch_inputs[ref]["commit"],
                         "branchless launch selects the independent current-branch commit")

            for scope in SELECTORS:
                selected(scope, "master")
            for scope in SELECTORS:
                ns.ok("make-current", app, "test", scope=scope)
                for other in SELECTORS:
                    selected(other, "test" if other == scope else "master")
                ns.ok("make-current", app, "master", scope=scope)
                selected(scope, "master")
        elif name == "selection-options-search":
            queries = fixture.get("queries")
            if queries is None:
                ns.block("independent A/B AppStream search fixtures required")
            for scope in SELECTORS:
                version = "B" if scope == "alt" else "A"
                source = f"file://{FIXTURES}/{queries['versions'][version]['repo']}"
                ns.ok("remote-add", "--no-gpg-verify", f"{scope}-only", source, scope=scope)
                ns.ok("update", "--appstream", scope=scope)
            for scope in SELECTORS:
                for term in ("amberquartz", "violetcobalt"):
                    matches = (term == "violetcobalt") == (scope == "alt")
                    output = ns.ok("search", "--columns=application,branch,remotes", term,
                                   scope=scope)
                    rows = set(output.splitlines())
                    wanted = ({f"{queries['app']}\t{branch}\t{scope}-only"
                               for branch in ("test", "master")} if matches else
                              {"No matches found"})
                    ns.equal(rows, wanted, "search returns only the selected catalogue")
                ns.equal(ns.refs(scope), set(), "search does not install catalogue apps")
        else:
            raise ValueError(f"unknown installation selector scenario: {name}")
    finally:
        if state.exists():
            shutil.rmtree(state)
