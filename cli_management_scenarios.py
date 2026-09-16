# SPDX-License-Identifier: LGPL-2.1-or-later
"""CLI management contracts using public queries and isolated user state."""

from __future__ import annotations

import configparser
from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def _equal(driver: Driver, actual: object, expected: object, context: str) -> None:
    driver.check(actual == expected,
                 f"{context}: expected {expected!r}, got {actual!r}")


def _commit(driver: Driver, ref: str, commit: str) -> None:
    output = driver.cli_success("info", "--user", "--show-ref", "--show-commit", ref)
    _equal(driver, output.split(), [ref, commit], "installed ref and commit")


def _refs(driver: Driver, *options: str) -> set[str]:
    output = driver.cli_success("list", "--user", "--columns=ref", *options)
    return set(output.splitlines())


def _install(driver: Driver, ref: str, *options: str) -> None:
    driver.cli_success("install", "--user", "--noninteractive", *options,
                       "fixture", ref)


def _update(driver: Driver, *options: str) -> None:
    driver.cli_success("update", "--user", "--noninteractive", *options)


def _uninstall(driver: Driver, *options: str) -> None:
    driver.cli_success("uninstall", "--user", "--noninteractive", *options)


def _remote_refs(driver: Driver, *options: str) -> set[str]:
    return set(driver.cli_success("remote-ls", "--user", "--columns=ref",
                                  *options, "fixture").splitlines())


def _rich(driver: Driver, fixture: FixtureManifest, name: str) -> None:
    """Use independently reference-exported query refs, including competing arches."""
    queries = fixture["queries"]
    root = Path(fixture["directory"])
    versions = queries["versions"]
    url = (root / versions["A"]["repo"]).as_uri()
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture", url)
    arch, foreign = fixture["arch"], queries["foreign_arch"]
    second = queries["second"]
    native_ref = f"app/{second}/{arch}/test"
    foreign_ref = f"app/{second}/{foreign}/test"
    app = f"app/{queries['app']}/{arch}/test"
    runtime = f"runtime/{fixture['runtime']}/{arch}/{fixture['branch']}"

    if name == "management-update-all":
        extension = f"runtime/{queries['extension']}/{arch}/next"
        # The next branch remains related after Query advances to B. The test
        # branch would instead be eligible for related-ref cleanup at that point.
        refs = (app, native_ref, extension)
        for ref in refs:
            driver.check(versions["A"]["refs"][ref]["commit"]
                         != versions["B"]["refs"][ref]["commit"],
                         f"update-all fixture must have distinct A/B commits for {ref}")
            _install(driver, ref)
        for ref in refs:
            _commit(driver, ref, versions["A"]["refs"][ref]["commit"])
        _commit(driver, runtime, fixture["runtime_commit"])
        driver.cli_success("remote-modify", "--user",
                           f"--url={(root / versions['B']['repo']).as_uri()}", "fixture")
        _update(driver)
        for ref in refs:
            _commit(driver, ref, versions["B"]["refs"][ref]["commit"])
        _commit(driver, runtime, fixture["runtime_commit"])
        return

    if name == "management-install-arch":
        _install(driver, second, "--no-deps", f"--arch={foreign}")
        _equal(driver, _refs(driver), {foreign_ref.removeprefix("app/")},
               "foreign architecture selected over available native app")
        _commit(driver, foreign_ref, versions["A"]["refs"][foreign_ref]["commit"])
        return

    if name == "management-query-fields":
        _install(driver, app)
        permissions = driver.cli_success("info", "--user", "--show-permissions", app)
        _equal(driver, permissions, "[Context]\nshared=network;", "declared permissions")
        metadata = root / versions["A"]["refs"][app]["metadata"]
        _equal(driver, driver.cli_success("remote-info", "--user", "--show-metadata",
                                         "fixture", app), metadata.read_text().strip(),
               "remote metadata equals independent reference-exported bytes")
        driver.cli_success("remote-modify", "--user",
                           f"--url={(root / versions['B']['repo']).as_uri()}", "fixture")
        _equal(driver, driver.cli_success("remote-info", "--user", "--show-parent",
                                         "fixture", app),
               versions["A"]["refs"][app]["commit"], "B parent is reference A commit")
        return

    if name == "management-remote-info-arch":
        output = driver.cli_success("remote-info", "--user", f"--arch={foreign}",
                                    "--show-ref", "--show-commit", "fixture", second)
        _equal(driver, output.split(), [foreign_ref,
                                       versions["A"]["refs"][foreign_ref]["commit"]],
               "foreign remote ref selected rather than native alternative")
        return

    for ref in (native_ref, foreign_ref):
        _install(driver, ref, "--no-deps")
        _commit(driver, ref, versions["A"]["refs"][ref]["commit"])
    if name == "management-installed-arch":
        _equal(driver, _refs(driver, f"--arch={foreign}"),
               {foreign_ref.removeprefix("app/")}, "foreign list excludes native")
        _equal(driver, _refs(driver, f"--arch={arch}"),
               {native_ref.removeprefix("app/")}, "native list excludes foreign")
        output = driver.cli_success("info", "--user", f"--arch={foreign}",
                                    "--show-ref", "--show-commit", second)
        _equal(driver, output.split(), [foreign_ref,
                                       versions["A"]["refs"][foreign_ref]["commit"]],
               "info chooses foreign copy over native default")
    elif name == "management-uninstall-arch":
        _uninstall(driver, f"--arch={foreign}", second)
        _equal(driver, _refs(driver), {native_ref.removeprefix("app/")},
               "architecture-limited uninstall retains native copy")
        _commit(driver, native_ref, versions["A"]["refs"][native_ref]["commit"])
    elif name == "management-update-arch":
        driver.cli_success("remote-modify", "--user",
                           f"--url={(root / versions['B']['repo']).as_uri()}", "fixture")
        _update(driver, "--no-deps", f"--arch={foreign}", second)
        _commit(driver, foreign_ref, versions["B"]["refs"][foreign_ref]["commit"])
        _commit(driver, native_ref, versions["A"]["refs"][native_ref]["commit"])
    elif name == "management-update-kinds":
        # Both a runtime and an app have genuine A-to-B updates.
        extension = f"runtime/{queries['extension']}/{arch}/test"
        _install(driver, extension)
        driver.cli_success("remote-modify", "--user",
                           f"--url={(root / versions['B']['repo']).as_uri()}", "fixture")
        _update(driver, "--runtime", "--no-deps")
        _commit(driver, extension, versions["B"]["refs"][extension]["commit"])
        _commit(driver, native_ref, versions["A"]["refs"][native_ref]["commit"])
        _update(driver, f"--commit={versions['A']['refs'][extension]['commit']}", extension)
        _update(driver, "--app", "--no-deps")
        _commit(driver, native_ref, versions["B"]["refs"][native_ref]["commit"])
        _commit(driver, extension, versions["A"]["refs"][extension]["commit"])
    elif name == "management-update-no-deps":
        driver.cli_success("remote-modify", "--user",
                           f"--url={(root / versions['B']['repo']).as_uri()}", "fixture")
        _update(driver, "--no-deps", native_ref)
        _commit(driver, native_ref, versions["B"]["refs"][native_ref]["commit"])
        driver.check(driver.cli_call("info", "--user", runtime).returncode != 0,
                     "update no-deps leaves required available runtime absent")
    else:
        raise ValueError(f"unknown rich management case: {name}")


def _remote_options(driver: Driver, url: str, name: str) -> None:
    """Read remote properties through a later public remotes process."""
    fields = ("comment", "description", "homepage", "icon")
    first = ("First comment", "First description", "https://first.invalid/home",
             "https://first.invalid/icon.png")
    second = ("Revised comment", "Revised description", "https://second.invalid/home",
              "https://second.invalid/icon.png")
    if name == "management-remote-properties":
        remote_options = [f"--{field}={value}" for field, value in zip(fields, first, strict=True)]
        driver.cli_success("remote-add", "--user", "--no-gpg-verify",
                           *remote_options, "fixture", url)
        columns = "--columns=" + ",".join(fields)
        _equal(driver, driver.cli_success("remotes", "--user", columns).split("\t"),
               list(first), "remote-add rich properties persist")
        for field, value in zip(fields, second, strict=True):
            driver.cli_success("remote-modify", "--user", f"--{field}={value}", "fixture")
        _equal(driver, driver.cli_success("remotes", "--user", columns).split("\t"),
               list(second), "remote-modify rich properties persist")
        return
    flag, marker = "--no-enumerate", "no-enumerate"
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", flag, "fixture", url)
    options = driver.cli_success("remotes", "--user", "--columns=options")
    driver.check(marker in options.split(","), f"added {flag} absent from options {options!r}")
    positive = "--enumerate"
    driver.cli_success("remote-modify", "--user", positive, "fixture")
    options = driver.cli_success("remotes", "--user", "--columns=options")
    driver.check(marker not in options.split(","), f"{positive} did not clear {options!r}")
    driver.cli_success("remote-modify", "--user", flag, "fixture")
    options = driver.cli_success("remotes", "--user", "--columns=options")
    driver.check(marker in options.split(","), f"modified {flag} absent from {options!r}")


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    """Run one independently isolated management contract group."""
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    a, b = fixture["commits"]["A"], fixture["commits"]["B"]
    repository.version = "A"

    if name in ("management-install-arch", "management-query-fields",
                "management-remote-info-arch", "management-installed-arch",
                "management-uninstall-arch", "management-update-arch",
                "management-update-kinds", "management-update-no-deps",
                "management-update-all"):
        _rich(driver, fixture, name)
        return
    if name in ("management-remote-properties", "management-remote-enumerate"):
        _remote_options(driver, url, name)
        return

    if name == "management-remote-dependencies":
        path = driver.root / "app-only.filter"
        path.write_text(f"deny *\nallow {app}\n", encoding="utf-8")
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", f"--filter={path}",
                           "fixture", url)
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "--no-use-for-deps",
                           "dependency", url)
        for phase in ("add", "modify"):
            failure = driver.cli_call("install", "--user", "--noninteractive", "fixture", app)
            driver.check(failure.returncode != 0 and fixture["runtime"] in failure.stderr,
                         f"{phase}: excluded dependency remote must not resolve runtime")
            _equal(driver, _refs(driver), set(), "dependency resolution failure is atomic")
            driver.cli_success("remote-modify", "--user", "--use-for-deps", "dependency")
            _install(driver, app)
            _commit(driver, app, a)
            _commit(driver, runtime, fixture["runtime_commit"])
            _uninstall(driver, "--all")
            driver.cli_success("remote-modify", "--user", "--no-use-for-deps", "dependency")
        return

    if name == "management-config":
        for value in ("de;fr", "ja;en"):
            driver.cli_success("config", "--user", "--set", "languages", value)
            _equal(driver, driver.cli_success("config", "--user", "--get", "languages"),
                   value, "languages persists across processes")
        return

    driver.cli_success("remote-add", "--user", "--no-gpg-verify",
                       "--title=Original title", "--prio=17", "fixture", url)

    if name in ("management-install-kinds", "management-remote-info-kinds"):
        command = "install" if name == "management-install-kinds" else "remote-info"
        for option, excluded in (("--app", fixture["runtime"]), ("--runtime", fixture["app"])):
            flags = ("--noninteractive",) if command == "install" else ("--show-ref",)
            result = driver.cli_call(command, "--user", *flags, option, "fixture", excluded)
            driver.check(result.returncode != 0 and excluded in result.stderr,
                         f"{command} {option} must exclude {excluded}: {result.stderr}")
            _equal(driver, _refs(driver), set(), "excluded kind cannot install refs")
        return

    if name == "management-remote-gpg":
        driver.cli_success("remote-modify", "--user", "--gpg-verify", "fixture")
        failure = driver.cli_call("install", "--user", "--noninteractive", "fixture", app)
        driver.check(failure.returncode != 0 and "signature" in failure.stderr.lower(),
                     f"unsigned source must fail verification: {failure.stderr}")
        _equal(driver, _refs(driver), set(), "verification failure leaves no deployment")
        driver.cli_success("remote-modify", "--user", "--no-gpg-verify", "fixture")
        _install(driver, app)
        _commit(driver, app, a)
        return

    if name == "management-duplicate-remote":
        driver.cli_success("remote-add", "--user", "--if-not-exists", "--no-gpg-verify",
                           "--title=Replacement title", "--prio=99", "fixture",
                           f"{url}/wrong")
        _equal(driver, driver.cli_success("remotes", "--user",
                                         "--columns=name,url,title,priority").split("\t"),
               ["fixture", url, "Original title", "17"],
               "duplicate preserves properties")
        return

    if name == "management-flatpakrepo":
        path = driver.root / "management.flatpakrepo"
        path.write_text(f"[Flatpak Repo]\nTitle=Description title\nUrl={url}/\n",
                        encoding="utf-8")
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "--from",
                           "description", str(path))
        output = driver.cli_success("remotes", "--user", "--columns=name,url,title")
        rows = output.splitlines()
        driver.check(f"description\t{url}/\tDescription title" in rows,
                     f"description properties missing: {rows!r}")
        return

    if name in ("management-filter", "management-filter-replacement"):
        path = driver.root / "management.filter"
        path.write_text(f"deny *\nallow {runtime}\n", encoding="utf-8")
        driver.cli_success("remote-modify", "--user", f"--filter={path}", "fixture")
        _equal(driver, _remote_refs(driver), {runtime},
               "allow overrides deny while app stays hidden")
        denied = driver.cli_call("install", "--user", "--noninteractive",
                                 "fixture", app)
        driver.check(denied.returncode != 0 and fixture["app"] in denied.stderr,
                     "filtered application must not be installable")
        _equal(driver, _refs(driver), set(), "denied install leaves no deployments")
        _install(driver, runtime)
        _commit(driver, runtime, fixture["runtime_commit"])
        if name == "management-filter-replacement":
            replacement = driver.root / "replacement.filter"
            replacement.write_text(f"deny *\nallow {app}\n", encoding="utf-8")
            description = driver.root / "replacement.flatpakrepo"
            description.write_text(f"[Flatpak Repo]\nUrl={url}\nFilter={replacement}\n",
                                   encoding="utf-8")
            driver.cli_success("remote-add", "--user", "--if-not-exists",
                               "--no-gpg-verify", "--from", "fixture", str(description))
            _equal(driver, _remote_refs(driver), {app},
                   "description replaces previous filter")
            description.write_text(f"[Flatpak Repo]\nUrl={url}\n", encoding="utf-8")
            driver.cli_success("remote-add", "--user", "--if-not-exists",
                               "--no-gpg-verify", "--from", "fixture", str(description))
        else:
            driver.cli_success("remote-modify", "--user", "--no-filter", "fixture")
        _equal(driver, _remote_refs(driver),
               {app, runtime},
               "clearing filter restores both refs")
        return

    if name == "management-remote-available":
        _equal(driver, _refs(driver), set(), "remote queries start without deployments")
        app_row, runtime_row = app, runtime
        _equal(driver, _remote_refs(driver), {app_row, runtime_row},
               "all available refs")
        _equal(driver, _remote_refs(driver, "--app"), {app_row}, "remote app filter")
        _equal(driver, _remote_refs(driver, "--runtime"), {runtime_row},
               "remote runtime filter")
        _equal(driver, _remote_refs(driver, f"--arch={fixture['arch']}"),
               {app_row, runtime_row}, "matching architecture")
        _equal(driver, _remote_refs(driver, "--arch=nonexistent"), set(),
               "absent architecture")
        return

    if name == "management-flatpakref":
        path = driver.root / "management.flatpakref"
        path.write_text(f"[Flatpak Ref]\nName={fixture['app']}\n"
                        f"Branch={fixture['branch']}\n"
                        f"Url={url}\nIsRuntime=false\n", encoding="utf-8")
        driver.cli_success("install", "--user", "--noninteractive", "--from", str(path))
        _commit(driver, app, a)
        _commit(driver, runtime, fixture["runtime_commit"])
        return

    if name == "management-install-local":
        _install(driver, app, "--no-deploy")
        _equal(driver, _refs(driver), set(),
               "download does not deploy app or dependency")
        driver.check(driver.cli_call("info", "--user", app).returncode != 0,
                     "downloaded application is not installed")
        repository.version = "B"
        _install(driver, app, "--no-pull")
        _commit(driver, app, a)
        _commit(driver, runtime, fixture["runtime_commit"])
        return

    if name == "management-install-no-deps":
        _install(driver, app, "--no-deps")
        _commit(driver, app, a)
        _equal(driver, _refs(driver), {app.removeprefix("app/")},
               "no-deps deploys app without runtime")
        return

    _install(driver, app)
    _commit(driver, app, a)
    _commit(driver, runtime, fixture["runtime_commit"])

    if name == "management-keep-ref":
        _uninstall(driver, "--keep-ref", app)
        driver.check(driver.cli_call("info", "--user", app).returncode != 0,
                     "keep-ref still removes deployment")
        # A successful local reinstall is the public oracle for the retained ref.
        repository.version = "B"
        _install(driver, app, "--no-pull")
        _commit(driver, app, a)
        _uninstall(driver, app)
        absent = driver.cli_call("install", "--user", "--noninteractive", "--no-pull",
                                 "fixture", app)
        driver.check(absent.returncode != 0,
                     "ordinary uninstall removes the ref needed for local reinstall")
        return

    if name in ("management-uninstall-apps", "management-uninstall-runtimes"):
        option = "--app" if name.endswith("apps") else "--runtime"
        excluded = fixture["runtime"] if name.endswith("apps") else fixture["app"]
        failure = driver.cli_call("uninstall", "--user", "--noninteractive", option, excluded)
        driver.check(failure.returncode != 0 and excluded in failure.stderr
                     and "no installed refs found" in failure.stderr.lower(),
                     f"{option} must refuse to uninstall opposite kind")
        _commit(driver, app, a)
        _commit(driver, runtime, fixture["runtime_commit"])
        if name.endswith("apps"):
            _uninstall(driver, "--app", fixture["app"])
            _equal(driver, _refs(driver), {runtime.removeprefix("runtime/")},
                   "app-only uninstall preserves runtime")
            _commit(driver, runtime, fixture["runtime_commit"])
        else:
            _uninstall(driver, fixture["app"])
            _uninstall(driver, "--runtime", fixture["runtime"])
            _equal(driver, _refs(driver), set(),
                   "runtime-only uninstall accepts now-unused runtime")
        return

    if name == "management-installed-queries":
        _equal(driver, _refs(driver, "--app"), {app.removeprefix("app/")}, "apps only")
        _equal(driver, _refs(driver, "--runtime"), {runtime.removeprefix("runtime/")},
               "runtimes only")
        _equal(driver, driver.cli_success("info", "--user", "--show-origin", app),
               "fixture", "installed origin")
        _equal(driver, driver.cli_success("info", "--user", "--show-runtime", app),
               runtime.removeprefix("runtime/"), "declared runtime")
        _equal(driver, driver.cli_success("info", "--user", "--show-sdk", app),
               runtime.removeprefix("runtime/"), "declared SDK")
        metadata = configparser.ConfigParser(interpolation=None)
        output = driver.cli_success("info", "--user", "--show-metadata", app)
        metadata.read_string(output)
        _equal(driver, metadata.sections(), ["Application"], "application sections")
        _equal(driver, dict(metadata["Application"]),
               {"name": fixture["app"], "runtime": runtime.removeprefix("runtime/"),
                "sdk": runtime.removeprefix("runtime/"), "command": "blackbox-probe"},
               "application metadata fields")
        metadata = configparser.ConfigParser(interpolation=None)
        metadata.read_string(driver.cli_success("info", "--user", "--show-metadata",
                                               runtime))
        _equal(driver, metadata.sections(), ["Runtime"], "runtime metadata sections")
        _equal(driver, dict(metadata["Runtime"]), {"name": fixture["runtime"]},
               "runtime metadata fields")
        return

    if name == "management-file-access":
        (driver.root / "access-probe").write_text("access probe\n", encoding="utf-8")
        access_path = str(driver.root / "access-probe")
        output = driver.cli_success("info", "--user", f"--file-access={access_path}",
                                    app)
        _equal(driver, output, "hidden", "ungranted host path")
        driver.cli_success("override", "--user", f"--filesystem={access_path}:ro",
                           fixture["app"])
        output = driver.cli_success("info", "--user", f"--file-access={access_path}",
                                    app)
        _equal(driver, output, "read-only", "read-only grant")
        driver.cli_success("override", "--user", f"--filesystem={access_path}",
                           fixture["app"])
        output = driver.cli_success("info", "--user", f"--file-access={access_path}",
                                    app)
        _equal(driver, output, "read-write", "writable grant")
        return

    if name == "management-force-delete":
        refused = driver.cli_call("remote-delete", "--user", "--noninteractive",
                                  "fixture")
        driver.check(refused.returncode != 0,
                     "normal remote deletion rejects installed users")
        driver.cli_success("remote-delete", "--user", "--force", "fixture")
        _equal(driver, driver.cli_success("remotes", "--user", "--show-disabled",
                                         "--columns=name"), "", "force removes origin")
        _commit(driver, app, a)
        _commit(driver, runtime, fixture["runtime_commit"])
        return

    if name in ("management-unused", "management-pin"):
        _equal(driver, driver.cli_success("pin", "--user"), "",
               "dependency is initially unpinned")
        if name == "management-pin":
            driver.cli_success("pin", "--user", runtime)
            _equal(driver, driver.cli_success("pin", "--user"), runtime, "pin persists")
        _uninstall(driver, app)
        _equal(driver, _refs(driver, "--app"), set(), "app removal retains no apps")
        _commit(driver, runtime, fixture["runtime_commit"])
        _uninstall(driver, "--unused")
        if name == "management-pin":
            _commit(driver, runtime, fixture["runtime_commit"])
            driver.cli_success("pin", "--user", "--remove", runtime)
            _equal(driver, driver.cli_success("pin", "--user"), "", "pin removed")
            _uninstall(driver, "--unused")
        _equal(driver, _refs(driver), set(), "unused unpinned dependency removed")
        return

    if name == "management-uninstall-all":
        _uninstall(driver, "--all")
        _equal(driver, _refs(driver), set(), "all removes both app and runtime")
        return

    repository.version = "B"
    if name == "management-or-update":
        _install(driver, app, "--or-update")
        _commit(driver, app, b)
    elif name == "management-reinstall":
        _install(driver, app, "--reinstall")
        _commit(driver, app, b)
    elif name == "management-update-local":
        _update(driver, "--no-pull", app)
        _commit(driver, app, a)
        _update(driver, "--no-deploy", app)
        _commit(driver, app, a)
        repository.fail_payloads = True
        _update(driver, "--no-pull", app)
        _commit(driver, app, b)
    elif name == "management-commit":
        _update(driver, app)
        _commit(driver, app, b)
        _update(driver, f"--commit={a}", app)
        _commit(driver, app, a)
        _equal(driver, driver.cli_success("remote-info", "--user", "--show-commit",
                                         "fixture", app), b, "remote tip remains B")
    elif name == "management-disabled":
        driver.cli_success("remote-modify", "--user", "--disable", "fixture")
        _equal(driver, driver.cli_success("remotes", "--user", "--columns=name"), "",
               "disabled remote omitted")
        _equal(driver, driver.cli_success("remotes", "--user", "--show-disabled",
                                         "--columns=name"), "fixture",
               "disabled remote included")
        _update(driver)
        _commit(driver, app, a)
        driver.cli_success("remote-modify", "--user", "--enable", "fixture")
        _update(driver)
        _commit(driver, app, b)
    elif name == "management-mask":
        driver.cli_success("mask", "--user", app)
        _equal(driver, driver.cli_success("mask", "--user"), app, "mask persists")
        _update(driver)
        _commit(driver, app, a)
        driver.cli_success("mask", "--user", "--remove", app)
        _equal(driver, driver.cli_success("mask", "--user"), "", "mask removed")
        _update(driver)
        _commit(driver, app, b)
    elif name == "management-remote-updates":
        _equal(driver, _remote_refs(driver, "--updates"), {app},
               "update query excludes unchanged runtime")
        _update(driver)
        _equal(driver, _remote_refs(driver, "--updates"), set(),
               "no updates after deployment")
    elif name == "management-remote-info":
        output = driver.cli_success("remote-info", "--user", "--show-ref",
                                    "--show-commit", "fixture", app)
        _equal(driver, output.split(), [app, b], "remote B over local A")
        output = driver.cli_success("remote-info", "--user", f"--commit={a}",
                                    "--show-commit", "fixture", app)
        _equal(driver, output, a, "explicit remote-info commit selects older A")
        _commit(driver, app, a)
    elif name == "management-remote-log":
        output = driver.cli_success("remote-info", "--user", "--log", "fixture", app)
        driver.check(a in output and b in output,
                     f"history must include both commits: {output}")
    else:
        raise ValueError(f"unknown management scenario: {name}")
