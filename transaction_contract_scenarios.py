# SPDX-License-Identifier: LGPL-2.1-or-later
"""Seven transaction contracts using prepared payloads and public installations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from json_validation import json_value

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    queries = fixture.get("queries")
    if queries is None:
        raise PrerequisiteError("prepared query fixtures required")
    root = Path(fixture["directory"])
    arch = fixture["arch"]
    runtime = f"runtime/{fixture['runtime']}/{arch}/{fixture['branch']}"
    app = f"app/{queries['app']}/{arch}/test"
    partial = f"runtime/{queries['extension']}/{arch}/test"
    selected = f"app/org.flatpak.Selection/{arch}/test"
    locale = f"runtime/org.flatpak.Selection.Locale/{arch}/test"

    def call(path: Path, *args: str) -> str:
        return driver.success("tx-contract", str(path), *args)

    def setup(label: str, uri: str) -> Path:
        path = driver.root / label
        call(path, "remote", uri)
        call(path, "languages", "fr")
        return path

    def tx(path: Path, action: str, ref: str, subpaths: str = "null", *,
           disabled: bool = False, dependency: Path | None = None,
           remote: str = "fixture", bundle: Path | None = None) -> list[list[str]]:
        output = call(path, action, remote, ref, subpaths, "1" if disabled else "0",
                      str(dependency) if dependency else "-", str(bundle) if bundle else "-")
        rows = [line.split("\t") for line in output.splitlines()]
        operations = [row[1:] for row in rows if row[0] == "op"]
        driver.check([row[1:] for row in rows if row[0] == "new"] ==
                     [[op[0]] for op in operations], "resolved operations execute in order")
        driver.check([row[1:] for row in rows if row[0] == "completed"] ==
                     [[str(len(operations))]], "client completes every execution assertion")
        return operations

    def state(path: Path) -> dict[str, list[str]]:
        return {fields[1]: fields[2:] for line in call(path, "state").splitlines()
                if (fields := line.split("\t"))[0] == "state"}

    def deployed(path: Path, ref: str, commit: str) -> Path:
        refs = state(path)
        driver.check(ref in refs and refs[ref][0] == commit, f"exact deployed commit for {ref}")
        return Path(refs[ref][2])

    def payloads(path: Path, ref: str, commit: str, expected: set[str],
                 candidates: dict[str, str]) -> None:
        location = deployed(path, ref, commit)
        actual = {key for key, file in candidates.items() if (location / "files" / file).is_file()}
        driver.evidence.append({"observation": "transaction-deployed-subset",
                                "data": json_value({"ref": ref, "location": str(location),
                                                    "files": candidates,
                                                    "actual": sorted(actual),
                                                    "expected": sorted(expected)})})
        driver.check(actual == expected, f"deployed subset {actual!r}, expected {expected!r}")
        if "extra" in expected:
            driver.check((location / "files" / candidates["extra"]).read_text() ==
                         "Independent full-install payload\n", "full-install marker contents")
        for language in expected & {"de", "fr", "ja", "es"}:
            driver.check((location / "files" / candidates[language]).read_text() == language + "\n",
                         "independent locale marker contents")

    query_uri = (root / queries["versions"]["A"]["repo"]).as_uri()
    if name in {"tx-install-subpaths", "tx-update-subpaths-all"}:
        commit = queries["versions"]["A"]["refs"][partial]["commit"]
        candidates = {"bin": "bin/probe", "extra": "subset-control/payload"}
        variants = ("/bin", "null", "empty") if name == "tx-install-subpaths" else (
            "empty", "empty-string")
        for index, variant in enumerate(variants):
            path = setup(f"subset-{index}", query_uri)
            tx(path, "install", partial, variant if name == "tx-install-subpaths" else "/bin")
            expected = {"bin"} if variant == "/bin" or name == "tx-update-subpaths-all" else {
                "bin", "extra"}
            payloads(path, partial, commit, expected, candidates)
            if name == "tx-update-subpaths-all":
                tx(path, "update", partial, variant)
                payloads(path, partial, commit, {"bin", "extra"}, candidates)
        return
    if name == "tx-update-subpaths-default":
        if "selection_repo" not in queries or "selection_commits" not in queries:
            raise PrerequisiteError("prepared selection locale fixtures required")
        selection_uri = (root / queries["selection_repo"]).as_uri()
        path = setup("languages", selection_uri)
        candidates = {lang: f"{lang}/marker" for lang in ("de", "fr", "ja", "es")}
        commit = queries["selection_commits"][locale]
        tx(path, "install", locale, "/ja")
        payloads(path, locale, commit, {"ja"}, candidates)
        tx(path, "update", locale)
        payloads(path, locale, commit, {"ja", "fr"}, candidates)
        call(path, "languages", "de")
        tx(path, "update", locale)
        payloads(path, locale, commit, {"ja", "fr", "de"}, candidates)
        return
    if name == "tx-disable-related":
        if "selection_repo" not in queries or "selection_commits" not in queries:
            raise PrerequisiteError("prepared selection app and locale fixtures required")
        selection_uri = (root / queries["selection_repo"]).as_uri()
        for disabled in (True, False):
            path = setup(f"related-{disabled}", selection_uri)
            ops = tx(path, "install", selected, disabled=disabled)
            expected = {selected, runtime} | (set() if disabled else {locale})
            driver.check({op[0] for op in ops} == expected,
                         "related flag controls locale operation")
            driver.check(set(state(path)) == expected, "related flag controls deployed locale")
            deployed(path, selected, queries["selection_commits"][selected])
            deployed(path, runtime, fixture["runtime_commit"])
            if not disabled:
                deployed(path, locale, queries["selection_commits"][locale])
        return
    if name == "tx-extra-dependency-source":
        source = setup("dependency", url)
        tx(source, "install", runtime)
        for enabled in (True, False):
            target = setup(f"dependent-{enabled}", url)
            ref = f"app/{fixture['app']}/{arch}/{fixture['branch']}"
            ops = tx(target, "install", ref, dependency=source if enabled else None)
            expected = {ref} | (set() if enabled else {runtime})
            driver.check({op[0] for op in ops} == expected,
                         "extra source controls runtime operation")
            driver.check(set(state(target)) == expected, "extra source avoids duplicate runtime")
            deployed(target, ref, fixture["commits"]["A"])
            if not enabled:
                deployed(target, runtime, fixture["runtime_commit"])
            driver.check(set(state(source)) == {runtime}, "dependency source remains runtime-only")
            deployed(source, runtime, fixture["runtime_commit"])
        return
    if name == "tx-file-uri-origin":
        path = driver.root / "file-origin"
        driver.check(state(path) == {}, "URI target initially empty")
        tx(path, "install", partial, remote=query_uri)
        deployed(path, partial, queries["versions"]["A"]["refs"][partial]["commit"])
        origin = state(path)[partial][1]
        driver.check(bool(origin), "installed ref names origin")
        driver.check(call(path, "origin", origin) == query_uri, "origin remote points at input URI")
        return
    if name != "tx-operation-identity":
        raise ValueError(name)
    path = setup("identity", query_uri)

    def identity(action: str, operation_type: str, *, bundle: Path | None = None) -> None:
        previous_origin = state(path).get(app, ["", "fixture"])[1]
        ops = tx(path, action, app, bundle=bundle)
        matches = [op for op in ops if op[0] == app]
        driver.check(len(matches) == 1, "requested operation occurs exactly once")
        op = matches[0]
        driver.check(op[1] == operation_type, "operation type matches requested action")
        # The bundle getter explicitly permits NULL. A returned GFile must identify
        # the supplied bundle; ordinary operations have no bundle input.
        driver.check(op[3] == "-" or (bundle is not None and op[3] == bundle.as_uri()),
                     f"applicable bundle URI or documented NULL, got {op[3]!r}")
        expected_origin = (state(path)[app][1] if action == "bundle" else previous_origin)
        driver.check(op[2] == expected_origin, "operation remote matches applicable origin")

    identity("install", "install")
    deployed(path, app, queries["versions"]["A"]["refs"][app]["commit"])
    call(path, "remote", (root / queries["versions"]["B"]["repo"]).as_uri())
    identity("update", "update")
    deployed(path, app, queries["versions"]["B"]["refs"][app]["commit"])
    identity("uninstall", "uninstall")
    driver.check(app not in state(path), "uninstall removes app")
    identity("bundle", "install-bundle", bundle=root / queries["bundle_plain"])
    deployed(path, app, queries["versions"]["A"]["refs"][app]["commit"])
    deployed(path, runtime, fixture["runtime_commit"])
    driver.check(set(state(path)) == {app, runtime}, "identity sequence preserves only app/runtime")
