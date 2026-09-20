# SPDX-License-Identifier: LGPL-2.1-or-later
"""CLI query options observed through exact fixture data and recorded transfers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from cli_management_scenarios import _commit, _equal
from coverage_next_scenarios import _observed_search_server
from fixture_manifest import FixtureManifest, FixtureQueries

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def _rows(driver: Driver, output: str, expected: set[tuple[str, ...]], reason: str) -> None:
    rows = [tuple(line.split("\t")) for line in output.splitlines()]
    driver.check(len(rows) == len(expected) and set(rows) == expected,
                 f"{reason}: expected {expected!r}, got {rows!r}")


def _commits(driver: Driver, output: str, expected: dict[str, str]) -> None:
    rows = [line.split("\t") for line in output.splitlines()]
    driver.check(all(len(row) == 2 for row in rows), f"expected ref/commit columns: {rows}")
    driver.check(len(rows) == len(expected) and {row[0] for row in rows} == set(expected),
                 f"exact remote ref set: {rows}")
    for ref, commit in rows:
        driver.check(len(commit) >= 8 and expected[ref].startswith(commit),
                     f"{ref}: commit {commit!r} must identify independent {expected[ref]}")


def _cached(driver: Driver, fixture: FixtureManifest, queries: FixtureQueries,
            command: str) -> None:
    from run import RepositoryServer

    source = Path(fixture["directory"]) / queries["versions"]["A"]["repo"]
    server = RepositoryServer(source.parent)
    arch = fixture["arch"]
    app = f"app/{queries['app']}/{arch}/test"
    driver.check(queries["versions"]["A"]["refs"][app]["commit"] !=
                 queries["versions"]["B"]["refs"][app]["commit"],
                 "cached query needs different A/B commits")
    with _observed_search_server(driver, server) as uri:
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "queries", uri)

        def query(version: str, cached: bool) -> None:
            options = ("--cached",) if cached else ()
            if command == "remote-info":
                actual = driver.cli_success(command, "--user", *options, "--show-commit",
                                            "queries", app)
                _equal(driver, actual, queries["versions"][version]["refs"][app]["commit"],
                       f"{command} returns {version}")
            else:
                output = driver.cli_success(command, "--user", *options, "--app",
                                            f"--arch={arch}", "--columns=ref,commit", "queries")
                expected = {ref: data["commit"]
                            for ref, data in queries["versions"][version]["refs"].items()
                            if ref.startswith("app/") and ref.split("/")[2] == arch}
                baseline = f"app/{fixture['app']}/{arch}/{fixture['branch']}"
                expected[baseline] = fixture["commits"]["A"]
                _commits(driver, output, expected)

        # Repeat in both directions. A cache preference must retain the warmed
        # view and avoid all network requests, while an ordinary query sees the
        # changed repository and refreshes the next cached view.
        query("A", False)
        for previous, current in (("A", "B"), ("B", "A")):
            server.version = current
            before = len(server.requests)
            query(previous, True)
            _equal(driver, len(server.requests), before, "cached query makes no HTTP requests")
            query(current, False)
            driver.check(len(server.requests) > before, "ordinary query refreshes from server")
            before = len(server.requests)
            query(current, True)
            _equal(driver, len(server.requests), before, "refreshed cache is queryable offline")


def _details(driver: Driver, command: str, options: tuple[str, ...],
             trailing: tuple[str, ...], expected: dict[str, str]) -> None:
    plain = driver.cli_success(command, "--user", *options, *trailing)
    detailed = driver.cli_success(command, "--user", *options, "--show-details", *trailing)
    explicit = driver.cli_success(command, "--user", *options, "--columns=all", *trailing)
    _equal(driver, detailed, explicit, "show-details is equivalent to all columns")
    driver.check(detailed != plain, "show-details adds information to ordinary output")
    rows = [line.split("\t") for line in detailed.splitlines()]
    driver.check(len(rows) == len(expected), f"detailed rows retain exact membership: {rows}")
    for ref, commit in expected.items():
        short = ref.split("/", 1)[1]
        identity, arch, branch = short.split("/")
        matching = [row for row in rows if ref in row or short in row or
                    all(value in row for value in (identity, arch, branch))]
        driver.check(len(matching) == 1, f"detailed row identifies {ref}: {rows}")
        driver.check(any(len(field) >= 8 and commit.startswith(field) for field in matching[0]),
                     f"detailed row includes independent commit for {ref}: {matching[0]}")


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    del repository, url
    queries = fixture.get("queries")
    if queries is None:
        raise PrerequisiteError("independent query fixtures required")
    root = Path(fixture["directory"])
    arch, branch = fixture["arch"], fixture["branch"]
    app = f"app/{queries['app']}/{arch}/test"
    master = f"app/{queries['app']}/{arch}/master"
    runtime = f"runtime/{fixture['runtime']}/{arch}/{branch}"
    if name in {"query-options-remote-info-cached", "query-options-remote-ls-cached"}:
        command = name.removeprefix("query-options-").removesuffix("-cached")
        _cached(driver, fixture, queries, command)
        return

    selection = name in {"query-options-list-all", "query-options-remote-ls-all",
                         "query-options-app-runtime"}
    if selection and "selection_repo" not in queries:
        raise PrerequisiteError("independent selection and locale fixtures required")
    source = root / (queries["selection_repo"] if selection else queries["versions"]["A"]["repo"])
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "queries", source.as_uri())

    def install(ref: str) -> None:
        driver.cli_success("install", "--user", "--noninteractive", "--no-related", "queries", ref)

    if name == "query-options-list-all":
        selected = f"app/org.flatpak.Selection/{arch}/test"
        locale = f"runtime/org.flatpak.Selection.Locale/{arch}/test"
        install(selected)
        install(locale)
        _commit(driver, locale, queries["selection_commits"][locale])
        expected = {ref.split("/", 1)[1] for ref in (selected, runtime, locale)}
        for options, refs in (((), expected - {locale.split("/", 1)[1]}),
                              (("--all",), expected),
                              ((), expected - {locale.split("/", 1)[1]})):
            output = driver.cli_success("list", "--user", "--columns=ref", *options)
            _rows(driver, output, {(ref,) for ref in refs}, "all controls extension visibility")
    elif name == "query-options-remote-ls-all":
        locale = f"runtime/org.flatpak.Selection.Locale/{arch}/test"
        expected = set(queries["selection_commits"]) | {
            f"app/{fixture['app']}/{arch}/{branch}", runtime}
        for options, refs in (((), expected - {locale}), (("--all",), expected),
                              ((), expected - {locale})):
            output = driver.cli_success("remote-ls", "--user", "--columns=ref",
                                        f"--arch={arch}", *options, "queries")
            _rows(driver, output, {(ref,) for ref in refs}, "remote all includes hidden locale")
    elif name == "query-options-app-runtime":
        selected = f"app/org.flatpak.Selection/{arch}/test"
        other = f"app/org.flatpak.SelectionOther/{arch}/test"
        baseline = f"app/{fixture['app']}/{arch}/{branch}"
        runtime_options = ("remote-ls", "--user", "--app", "--columns=ref", f"--arch={arch}")
        _rows(driver, driver.cli_success(*runtime_options, "queries"),
              {(ref,) for ref in (baseline, selected, other)}, "unfiltered app controls")
        for used_runtime, refs in ((runtime.split("/", 1)[1], {baseline, selected}),
                                   (f"org.flatpak.SelectionPlatform/{arch}/test", {other}),
                                   (f"org.flatpak.AbsentPlatform/{arch}/test", set())):
            output = driver.cli_success(*runtime_options, f"--app-runtime={used_runtime}",
                                        "queries")
            _rows(driver, output, {(ref,) for ref in refs}, "remote app-runtime filters consumers")
    elif name in {"query-options-list-details", "query-options-remote-ls-details"}:
        if name == "query-options-list-details":
            install(app)
            install(master)
            expected_commits = {ref: queries["versions"]["A"]["refs"][ref]["commit"]
                                for ref in (app, master)}
            _details(driver, "list", ("--app",), (), expected_commits)
        else:
            expected_commits = {ref: data["commit"]
                        for ref, data in queries["versions"]["A"]["refs"].items()
                        if ref.startswith("app/") and ref.split("/")[2] == arch}
            expected_commits[f"app/{fixture['app']}/{arch}/{branch}"] = fixture["commits"]["A"]
            _details(driver, "remote-ls", ("--app", f"--arch={arch}"), ("queries",),
                     expected_commits)
    elif name == "query-options-remotes-details":
        second_uri = (root / queries["versions"]["B"]["repo"]).as_uri()
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "--title=Second query source",
                           "second", second_uri)
        for title in ("First query source", "Updated query source"):
            driver.cli_success("remote-modify", "--user", f"--title={title}", "queries")
            plain = driver.cli_success("remotes", "--user")
            detailed = driver.cli_success("remotes", "--user", "--show-details")
            _equal(driver, detailed, driver.cli_success("remotes", "--user", "--columns=all"),
                   "remote details are equivalent to all columns")
            driver.check(detailed != plain, "remote details add information")
            rows = [line.split("\t") for line in detailed.splitlines()]
            driver.check(len(rows) == 2, "exactly two detailed remotes")
            for remote, expected_title, uri in (("queries", title, source.as_uri()),
                                                 ("second", "Second query source", second_uri)):
                matching = [row for row in rows if remote in row]
                driver.check(len(matching) == 1 and expected_title in matching[0]
                             and uri in matching[0],
                             f"details identify independent remote name, title and URL: {rows}")
    elif name == "query-options-search-columns":
        driver.cli_success("update", "--user", "--appstream", "queries")
        for columns in (("application", "branch"), ("branch", "application", "version", "remotes")):
            expected_rows: set[tuple[str, ...]] = set()
            for selected_branch in ("master", "test"):
                values = {"application": queries["app"], "branch": selected_branch,
                          "version": "1.2.3", "remotes": "queries"}
                expected_rows.add(tuple(values[field] for field in columns))
            for flags in (("--columns=" + ",".join(columns),),
                          tuple("--columns=" + field for field in columns)):
                output = driver.cli_success("search", "--user", *flags, "amberquartz")
                _rows(driver, output, expected_rows, "search honors column selection and order")
        _equal(driver, driver.cli_success("list", "--user", "--columns=ref"), "",
               "search and cache refresh deploy no refs")
    elif name == "query-options-info-size":
        size_refs = (app, f"app/{queries['second']}/{arch}/test")
        driver.check(len({queries["versions"]["A"]["refs"][ref]["installed"]
                          for ref in size_refs}) == 2,
                     "size controls must have distinct byte counts")
        for ref in size_refs:
            install(ref)
            expected_size = queries["versions"]["A"]["refs"][ref]["installed"]
            output = driver.cli_success("info", "--user", "--show-size", ref)
            _equal(driver, output, str(expected_size), "installed size equals independent fixture")
    elif name == "query-options-info-extensions":
        extension = f"runtime/{queries['extension']}/{arch}/test"
        unrelated = f"runtime/{queries['extension']}/{arch}/next"
        install(app)
        install(extension)
        install(unrelated)
        plain = driver.cli_success("info", "--user", app)
        output = driver.cli_success("info", "--user", "--show-extensions", app)
        driver.check(output != plain, "extension query adds extension information")
        driver.check(extension.split("/", 1)[1] in output
                     and unrelated.split("/", 1)[1] not in output,
                     f"only matching extension branch appears: {output}")
        expected_commit = queries["versions"]["A"]["refs"][extension]["commit"]
        driver.check(any(len(token) >= 8 and expected_commit.startswith(token)
                         for token in output.split()), "extension query includes its exact commit")
        driver.cli_success("uninstall", "--user", "--noninteractive", extension)
        after = driver.cli_success("info", "--user", "--show-extensions", app)
        driver.check(not any(len(token) >= 8 and expected_commit.startswith(token)
                             for token in after.split()),
                     "removed extension commit is no longer reported")
        _commit(driver, unrelated, queries["versions"]["A"]["refs"][unrelated]["commit"])
    else:
        raise ValueError(f"unknown query option scenario: {name}")
