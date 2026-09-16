# SPDX-License-Identifier: LGPL-2.1-or-later
"""Real repository/deployment queries, with preparation kept outside execution."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError, RepositoryServer

    queries = fixture.get("queries")
    if not isinstance(queries, dict):
        raise PrerequisiteError("prepare_queries.py query fixtures are required")
    root = Path(fixture["directory"])
    arch = fixture["arch"]
    app = f"app/{queries['app']}/{arch}/test"
    master = f"app/{queries['app']}/{arch}/master"
    second = f"app/{queries['second']}/{arch}/test"
    runtime = f"runtime/{fixture['runtime']}/{arch}/{fixture['branch']}"
    baseline_app = f"app/{fixture['app']}/{arch}/{fixture['branch']}"
    refs_a = queries["versions"]["A"]["refs"]
    values: dict[str, str] = {
        "ref": app, "commit": refs_a[app]["commit"], "master_ref": master,
        "master_commit": refs_a[master]["commit"],
        "appstream": str(root / queries["appstream"]), "partial": ""}
    for size in (64, 128):
        values[f"icon-{size}"] = str(root / queries["icons"][str(size)])

    def select(ref: str = app, version: str = "A") -> None:
        details = queries["versions"][version]["refs"][ref]
        values.update(ref=ref, commit=details["commit"],
                      metadata=str(root / details["metadata"]),
                      installed=str(details["installed"]),
                      download=str(details["download"]))

    def call(group: str, action: str) -> str:
        path = driver.root / "query.ini"
        path.write_text("[query]\n" + "".join(
            f"{key}={value}\n" for key, value in values.items()))
        return driver.success(f"queryx-{group}", str(path), action)

    def remote(version: str = "A", initial: bool = False) -> None:
        uri = (root / queries["versions"][version]["repo"]).as_uri()
        values["url"] = uri
        if initial:
            driver.cli_success("remote-add", "--user", "--no-gpg-verify",
                               "queries", uri)
        else:
            driver.cli_success("remote-modify", "--user", f"--url={uri}", "queries")

    def install(*refs: str) -> None:
        driver.cli_success("install", "--user", "--noninteractive", "--no-related",
                           "queries", *refs)

    select()
    if name == "queryx-related-policy":
        if "policy_repo" not in queries:
            raise PrerequisiteError("prepare_queries.py policy fixture is required")
        extensions = queries["policy_extensions"]
        driver.check(len(extensions) == 2, "policy fixture requires two extensions")
        values.update(ref=queries["policy_ref"], commit=queries["policy_commit"],
                      metadata=str(root / queries["policy_metadata"]))
        for index, extension in enumerate(extensions):
            for key in ("ref", "commit", "no_autodownload", "autodelete",
                        "should_download", "should_delete"):
                item = extension[key]
                values[f"policy_{index}_{key}"] = (
                    str(item).lower() if isinstance(item, bool) else str(item))
        uri = (root / queries["policy_repo"]).as_uri()
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "queries", uri)
        call("policy", "check")
        return
    if name == "queryx-bundle":
        for suffix, bundle, size in (
            ("urls", queries["bundle_urls"], queries["bundle_urls_size"]),
            ("plain", queries["bundle_plain"], queries["bundle_plain_size"]),
        ):
            values.update(bundle=str(root / bundle), installed=str(size))
            values["origin"] = (
                "https://example.invalid/query" if suffix == "urls" else "")
            call("bundle", "check")
        return
    if name == "queryx-ref-file":
        values["url"] = (root / queries["versions"]["A"]["repo"]).as_uri()
        call("ref-file", "check")
        return
    if name == "queryx-remote-cached":
        server = RepositoryServer(root / "query-inputs")
        with server.serving() as server_url:
            values["url"] = server_url
            native = [ref for ref in refs_a if ref.split("/")[2] == arch]
            values["all"] = ";".join([*native, baseline_app, runtime])
            call("remote", "add")
            before = len(server.requests)
            call("remote", "uncached")
            driver.check(len(server.requests) == before,
                         "uncached query attempted network I/O")
            call("remote", "metadata")
            before = len(server.requests)
            server.version = "B"
            call("remote", "cached")
            driver.check(len(server.requests) == before,
                         "cached query attempted network I/O")
            driver.evidence[-1]["query_network_observation"] = {
                "requests": list(server.requests), "cached_query_requests": 0,
                "uncached_query_requests": 0}
        return
    remote(initial=True)
    if name == "queryx-installed-list":
        values.update(all="", apps="", runtimes="")
        call("installed", "list")
        install(runtime)
        values.update(all=runtime, runtimes=runtime)
        call("installed", "list")
        install(app, master, second)
        values.update(all=f"{runtime};{app};{master};{second}",
                      apps=f"{app};{master};{second}")
        call("installed", "list")
    elif name == "queryx-installed-defaults":
        install(runtime)
        select(master)
        call("legacy", "install")
        select(app)
        call("legacy", "install")
        call("installed", "defaults")
    elif name in {"queryx-installed-metadata", "queryx-installed-appdata",
                  "queryx-installed-ownership"}:
        install(app)
        call("installed", name.removeprefix("queryx-installed-"))
    elif name == "queryx-installed-subpaths":
        install(app)
        call("installed", "subpaths")
        select(second)
        call("legacy", "partial")
        values["partial"] = "/bin"
        call("installed", "subpaths")
    elif name in {"queryx-remote-members", "queryx-remote-all-arches"}:
        available = [ref for ref in refs_a if name.endswith("all-arches") or
                     ref.split("/")[2] == arch]
        values["all"] = ";".join([*available, baseline_app, runtime])
        call("remote", name.removeprefix("queryx-remote-"))
    elif name == "queryx-remote-metadata":
        call("remote", "metadata")
    elif name == "queryx-remote-current":
        install(app)
        remote("B")
        select(version="B")
        values["old_commit"] = refs_a[app]["commit"]
        call("remote", "current")
    elif name == "queryx-legacy-lifecycle":
        install(runtime)
        call("legacy", "install")
        remote("B")
        select(version="B")
        call("legacy", "update")
        call("legacy", "uninstall")
    elif name == "queryx-legacy-noop":
        install(app)
        call("legacy", "noop")
        select(second)
        call("legacy", "absent")
    elif name == "queryx-legacy-pull":
        install(runtime)
        call("legacy", "pull")
        call("legacy", "deploy")
    elif name in {"queryx-related-members", "queryx-related-version"}:
        related = f"runtime/{queries['extension']}/{arch}/test"
        values.update(related=related, related_commit=refs_a[related]["commit"],
                      should_download="false")
        install(app)
        call("related", "remote")
        values["related"] = ""
        call("related", "installed")
        if name.endswith("members"):
            values["related_origin"] = "extensions"
            driver.cli_success("remote-add", "--user", "--no-gpg-verify",
                               "extensions", values["url"])
            driver.cli_success("install", "--user", "--noninteractive",
                               "extensions", related)
        else:
            values["related_origin"] = "queries"
            install(related)
        values["related"] = related
        values["should_download"] = "true"
        call("related", "installed")
        if name.endswith("version"):
            remote("B")
            newer = f"runtime/{queries['extension']}/{arch}/next"
            values.update(related=newer,
                          should_download="true",
                          related_commit=queries["versions"]["B"]["refs"][newer]["commit"])
            call("related", "remote")
            values.update(related=related,
                          should_download="true",
                          related_commit=queries["versions"]["B"]["refs"][related]["commit"])
            call("related", "for-installed")
    elif name == "queryx-updates":
        install(app)
        values["updates"] = ""
        call("updates", "check")
        remote("B")
        values["updates"] = app
        call("updates", "check")
        driver.cli_success("update", "--user", "--noninteractive", "--no-related",
                           "--no-deploy", app)
        call("updates", "check")
        driver.cli_success("update", "--user", "--noninteractive", "--no-related",
                           "--no-pull", app)
        values["updates"] = ""
        call("updates", "check")
    elif name == "queryx-appstream":
        values["cache_appstream"] = str(
            root / queries["versions"]["A"]["appstream"])
        call("appstream", "check")
    elif name == "queryx-unused":
        install(app)
        values.update(runtime=runtime, runtime_commit=fixture["runtime_commit"])
        call("unused", "check")
    elif name in {"queryx-launch", "queryx-launch-full", "queryx-instance-processes"}:
        install(app)
        values.update(runtime=runtime,
                      runtime_commit=fixture["runtime_commit"],
                      probe_dir=str(Path(driver.env["HOME"]) / ".var/app"
                                    / queries["app"] / "data"))
        action = {"queryx-launch": "basic", "queryx-launch-full": "full",
                  "queryx-instance-processes": "processes"}[name]
        output = call("launch", action)
        driver.check(output.splitlines().count("query-probe-A") == 2,
                     "both launched fixture processes must report version A")
    else:
        raise AssertionError(f"unhandled query scenario: {name}")
