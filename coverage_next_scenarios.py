# SPDX-License-Identifier: LGPL-2.1-or-later
"""Search, bundle, runtime selection and locale configuration observations."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from cli_management_scenarios import _commit, _equal, _refs
from fixture_manifest import FixtureManifest
from json_validation import json_value

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


@contextmanager
def _observed_search_server(driver: Driver, server: RepositoryServer) -> Iterator[str]:
    try:
        with server.serving() as uri:
            yield uri
    finally:
        driver.evidence.append({"observation": "appstream-http",
                                "data": json_value(server.requests)})


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError, RepositoryServer
    from transaction_scenarios import TransferServer

    queries = fixture.get("queries")
    if queries is None:
        raise PrerequisiteError("prepared query fixtures are required")
    root = Path(fixture["directory"])
    arch = fixture["arch"]
    app = f"app/{queries['app']}/{arch}/test"
    runtime = f"runtime/{fixture['runtime']}/{arch}/{fixture['branch']}"

    if name == "coverage-progress-context":
        server = TransferServer(root / queries["versions"]["A"]["repo"])
        server.cancel_marker = driver.root / "appstream-in-flight"
        server.slow = True
        with server.serving(driver) as uri:
            driver.cli_success("remote-add", "--user", "--no-gpg-verify", "queries", uri)
            data = driver.root / "progress.ini"
            data.write_text(f"[query]\nref={app}\ncache_appstream="
                            f"{root / queries['versions']['A']['appstream']}\n")
            driver.success("queryx-progress", str(data), "check")
            driver.check(server.cancel_marker.exists(),
                         "refresh must consume a deliberately delayed AppStream payload")
        return

    if name in {"coverage-search", "coverage-appstream-update"}:
        server_search = RepositoryServer(root / "query-inputs")
        with _observed_search_server(driver, server_search) as uri:
            driver.cli_success("remote-add", "--user", "--no-gpg-verify", "queries", uri)

            def search(term: str, present: bool) -> None:
                output = driver.cli_success("search", "--user",
                                            "--columns=application,branch", term)
                if present:
                    _equal(driver, sorted(output.splitlines()),
                           [f"{queries['app']}\tmaster", f"{queries['app']}\ttest"],
                           f"search {term} returns only the described app's two branches")
                else:
                    driver.check(queries["app"] not in output and
                                 (not output or output == "No matches found"),
                                 f"search {term} unexpectedly matched: {output!r}")

            driver.cli_success("update", "--user", "--appstream", "queries")
            search("amberquartz", True)
            search("violetcobalt", False)
            search("nonexistentsearchneedle", False)
            if name == "coverage-appstream-update":
                server_search.version = "B"
                # A fresh cache must remain A until the explicit refresh.
                search("amberquartz", True)
                search("violetcobalt", False)
                driver.cli_success("update", "--user", "--appstream", "queries")
                search("violetcobalt", True)
                search("amberquartz", False)
            _equal(driver, _refs(driver), set(), "AppStream work deploys no refs")
        return

    if name == "coverage-bundle":
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "dependency", url)
        driver.cli_success("install", "--user", "--noninteractive", "dependency", runtime)
        _equal(driver, _refs(driver, "--app"), set(), "bundle app initially absent")
        bundle = driver.root / "bundle-input"
        shutil.copyfile(root / queries["bundle_plain"], bundle)
        rejected = driver.cli_call("install", "--user", "--noninteractive", str(bundle))
        driver.check(rejected.returncode != 0,
                     "extensionless bundle requires explicit --bundle selection")
        _equal(driver, _refs(driver), {runtime.removeprefix("runtime/")},
               "without --bundle the input deploys no app and preserves the runtime")
        _commit(driver, runtime, fixture["runtime_commit"])
        driver.cli_success("install", "--user", "--noninteractive", "--bundle",
                           str(bundle))
        _commit(driver, app, queries["versions"]["A"]["refs"][app]["commit"])
        _commit(driver, runtime, fixture["runtime_commit"])
        _equal(driver, _refs(driver, "--app"), {app.removeprefix("app/")},
               "only bundled app is deployed")
        driver.check(driver.cli_call("info", "--user", queries["second"]).returncode != 0,
                     "unbundled companion is absent")
        return

    if "selection_repo" not in queries:
        raise PrerequisiteError("regenerate query fixtures with selection repository")
    uri = (root / queries["selection_repo"]).as_uri()
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "selection", uri)
    selected = f"app/org.flatpak.Selection/{arch}/test"
    other = f"app/org.flatpak.SelectionOther/{arch}/test"
    locale = f"runtime/org.flatpak.Selection.Locale/{arch}/test"

    def install(ref: str) -> None:
        driver.cli_success("install", "--user", "--noninteractive", "selection", ref)
        _commit(driver, ref, queries["selection_commits"][ref])

    if name == "coverage-runtime-filter":
        install(selected)
        install(other)
        _equal(driver, _refs(driver, "--app"),
               {selected.removeprefix("app/"), other.removeprefix("app/")},
               "both competing applications are installed")
        for used_runtime, expected in (
            (runtime.removeprefix("runtime/"), {selected.removeprefix("app/")}),
            (f"org.flatpak.SelectionPlatform/{arch}/test", {other.removeprefix("app/")}),
            (f"org.flatpak.AbsentPlatform/{arch}/test", set()),
        ):
            _equal(driver, _refs(driver, f"--app-runtime={used_runtime}"), expected,
                   "runtime selector excludes every nonmatching application")
        return

    if name != "coverage-config-unset":
        raise ValueError(f"unknown coverage scenario: {name}")
    driver.env.update(LC_ALL="C.UTF-8", LANGUAGE="fr")
    driver.cli_success("config", "--user", "--set", "extra-languages", "de")
    driver.cli_success("config", "--user", "--set", "languages", "ja")

    def locales(expected: set[str]) -> None:
        install(selected)
        location = Path(driver.cli_success("info", "--user", "--show-location", locale))
        actual = {lang for lang in ("de", "fr", "ja", "es")
                  if (location / "files" / lang / "marker").exists()}
        driver.evidence.append({"observation": "deployed-locale-markers",
                                "data": json_value({"location": str(location),
                                                    "expected": sorted(expected),
                                                    "actual": sorted(actual)})})
        _equal(driver, actual, expected, "locale extension deployed language payloads")
        for lang in expected:
            _equal(driver, (location / "files" / lang / "marker").read_text(),
                   lang + "\n", "locale marker contents")
        driver.cli_success("uninstall", "--user", "--noninteractive", "--all")
        _equal(driver, _refs(driver), set(), "next locale test starts without deployments")

    _equal(driver, driver.cli_success("config", "--user", "--get", "languages"),
           "ja", "explicit languages persists")
    locales({"ja"})
    driver.cli_success("config", "--user", "--unset", "languages")
    _equal(driver, driver.cli_success("config", "--user", "--get", "extra-languages"),
           "de", "unset preserves extra-languages")
    locales({"de", "fr"})
