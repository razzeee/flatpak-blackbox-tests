# SPDX-License-Identifier: LGPL-2.1-or-later
"""Test SDK, operation-cause, migration, update, and remote-trust behavior."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from json_validation import json_value

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import Driver, PrerequisiteError

    root = Path(fixture["directory"])
    failures: list[str] = []

    def observe(condition: bool, label: str, actual: object) -> None:
        driver.evidence.append({"observation": label, "data": json_value(actual)})
        if not condition:
            failures.append(f"{label}: {actual!r}")

    def call(path: Path, *args: str) -> str:
        return driver.success("tx-contract", str(path), *args)

    def state(path: Path) -> dict[str, str]:
        return {row[1]: row[2] for line in call(path, "state").splitlines()
                if (row := line.split("\t"))[0] == "state"}

    def exercise(path: Path, action: str, refs: list[str], *, sdk: bool = False,
                 debug: bool = False, nodeps: bool = False, unrelated: bool = False,
                 previous: list[str] | None = None) -> list[list[str]]:
        output = call(path, "exercise", action, ";".join(refs), str(int(sdk)), str(int(debug)),
                      str(int(nodeps)), str(int(unrelated)), ";".join(previous or ["-"]))
        rows = [line.split("\t") for line in output.splitlines()]
        if action != "reject-install":
            started = [row[1] for row in rows if row[0] == "new"]
            driver.check([row[1] for row in rows if row[0] == "completed"] ==
                         [str(len(started))], "client completes all execution callback assertions")
        return rows

    def operation_refs(rows: list[list[str]]) -> set[str]:
        return {row[1] for row in rows if row[0] == "op"}

    if name in {"remote-branch-collection", "remote-trusted-key"}:
        build = fixture.get("build")
        if build is None:
            raise PrerequisiteError("prepared signed collection repository required")
        app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
        runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
        signed = (root / build["usb_repo"]).as_uri()
        key = str(root / build["public_key"])
        collection = build["collection_id"]
        if name == "remote-branch-collection":
            path = driver.root / "signed-properties"
            call(path, "signed-remote", signed, key, fixture["branch"], collection)
            # Every call opens a new installation in a new client process.
            driver.check(call(path, "properties") ==
                         f"properties\t1\t{fixture['branch']}\t{collection}",
                         "signed branch and collection survive reopening")
            exercise(path, "install", [app])
            signed_state = {app: build["usb_commits"]["app"],
                            runtime: build["usb_commits"]["runtime"]}
            driver.check(state(path) == signed_state, "signed collection fixture is installable")
            for action, branch, cid in (("branch-clear", "-", collection),
                                        ("collection-clear", fixture["branch"], "-"),
                                        ("settings", "-", "-")):
                call(path, "settings", fixture["branch"], collection)
                driver.check(call(path, "properties") ==
                             f"properties\t1\t{fixture['branch']}\t{collection}",
                             "both properties populated before each clearing variant")
                if action == "settings":
                    call(path, action, "-", "-")
                else:
                    call(path, action)
                actual = call(path, "properties")
                observe(actual == f"properties\t1\t{branch}\t{cid}",
                        f"{action} survives reopen without changing untouched property", actual)
                driver.check(state(path) == signed_state, "property edits preserve deployments")
        else:
            for variant in ("trusted", "missing-key", "unsigned"):
                path = driver.root / variant
                uri = (root / "A").as_uri() if variant == "unsigned" else signed
                call(path, "signed-remote", uri, "-" if variant == "missing-key" else key,
                     "-", "-")
                driver.check(call(path, "properties") == "properties\t1\t-\t-",
                             "verification persists before transaction")
                driver.check(state(path) == {}, "trust fixture initially empty")
                action = "install" if variant == "trusted" else "reject-install"
                rows = exercise(path, action, [app])
                if variant == "trusted":
                    driver.check(state(path) == {app: build["usb_commits"]["app"],
                                                runtime: build["usb_commits"]["runtime"]},
                                 "committed trusted key permits exact signed deployments")
                else:
                    driver.check(any(row[0] == "rejected" for row in rows),
                                 "untrusted transaction fails with a GError")
                    driver.check(state(path) == {}, "unverified content is never deployed")
        driver.check(not failures, "\n".join(failures))
        return

    prepared = fixture.get("contracts")
    if prepared is None:
        raise PrerequisiteError("prepared contracts repos, refs and commits required")
    contracts = prepared
    refs = contracts["refs"]
    one, two, platform, sdk_ref, extension = (refs[key] for key in
                                             ("one", "two", "platform", "sdk", "extension"))
    apps = {one, two}
    shared = refs["shared"]
    dependencies = {platform, extension, shared}
    base = {one} | dependencies

    def setup(label: str) -> Path:
        path = driver.root / label
        call(path, "remote", (root / contracts["repos"]["A"]).as_uri())
        return path

    def deployed(path: Path, expected: set[str], version: str = "A") -> None:
        actual = state(path)
        observe(actual == {ref: contracts["commits"][version][ref] for ref in expected},
                "exact contract deployments", actual)

    def switch(path: Path, version: str) -> None:
        driver.check(contracts["commits"][version] != contracts["commits"]["A"],
                     "prepared update really changes a dependency")
        call(path, "remote", (root / contracts["repos"][version]).as_uri())

    if name == "tx-auto-sdk-debug":
        for sdk_enabled, debug in ((False, False), (True, False), (False, True), (True, True)):
            path = setup(f"auto-{sdk_enabled}-{debug}")
            rows = exercise(path, "install", [one], sdk=sdk_enabled, debug=debug)
            expected = base | ({sdk_ref} if sdk_enabled else set())
            if debug:
                expected |= {refs["one_debug"], refs["platform_debug"]}
                if sdk_enabled:
                    expected.add(refs["sdk_debug"])
            observe(operation_refs(rows) == expected, "automatic install operation set", rows)
            deployed(path, expected)
        path = setup("auto-update")
        exercise(path, "install", [one])
        deployed(path, base)
        exercise(path, "update", [one], sdk=True, debug=True)
        deployed(path, base | {sdk_ref, refs["one_debug"], refs["platform_debug"],
                               refs["sdk_debug"]})
        path = setup("auto-uninstall")
        exercise(path, "install", [one])
        deployed(path, base)
        rows = exercise(path, "uninstall", [one], sdk=True, debug=True)
        observe(all(row[2] == "uninstall" for row in rows if row[0] == "op"),
                "uninstall-only has no added install operations", rows)
        # Neither extension is marked autodelete, so both remain after app removal.
        deployed(path, dependencies)
    elif name == "tx-operation-causes":
        path = setup("causes")
        rows = exercise(path, "install", [one, two])

        def causes(rows: list[list[str]], ref: str) -> set[tuple[str, str]]:
            return {(row[2], row[3]) for row in rows if row[0] == "cause" and row[1] == ref}

        observe(causes(rows, platform) == {(app, "0") for app in apps},
                "shared runtime reports both requesting apps", rows)
        observe(causes(rows, extension) == {(platform, "0")},
                "related extension reports its main runtime", rows)
        observe(causes(rows, shared) == {(app, "0") for app in apps},
                "shared related extension reports both main apps", rows)
        observe({row[1] for row in rows if row[0] == "cause-free"} == apps,
                "explicit app requests have no causes", rows)
        observe(all(row[2] == "0" for row in rows if row[0] == "skip"),
                "fresh install operations are not skipped", rows)
        deployed(path, apps | dependencies)
        switch(path, "RUNTIME")
        rows = exercise(path, "update", [one, two])
        observe(causes(rows, platform) == {(app, "1") for app in apps},
                "runtime update exposes both skipped unchanged app causes", rows)
        observe(apps.isdisjoint(operation_refs(rows)),
                "skipped apps absent from operation list", rows)
        observe(apps.isdisjoint({row[1] for row in rows if row[0] == "new"}),
                "skipped app causes have no execution callbacks", rows)
        deployed(path, apps | dependencies, "RUNTIME")
    elif name == "query-missing-dependencies":
        for variant in ("runtime-missing", "related-missing", "RUNTIME", "EXTENSION"):
            path = setup(variant)
            exercise(path, "install", [one, two], nodeps=variant == "runtime-missing",
                     unrelated=variant in {"runtime-missing", "related-missing"})
            expected = apps | (set() if variant == "runtime-missing" else {platform})
            if variant not in {"runtime-missing", "related-missing"}:
                expected |= {extension, shared}
            deployed(path, expected)
            if variant in {"RUNTIME", "EXTENSION"}:
                driver.check(call(path, "updates") == "", "complete current apps need no update")
                switch(path, variant)
            updates = {row[1] for line in call(path, "updates").splitlines()
                       if (row := line.split("\t"))[0] == "update"}
            observe(apps <= updates, f"all affected apps listed for {variant}", sorted(updates))
            # Resolve the missing/updated dependency and require the negative control.
            exercise(path, "update", [one, two])
            deployed(path, apps | dependencies,
                     variant if variant in {"RUNTIME", "EXTENSION"} else "A")
            observe(call(path, "updates") == "", f"repaired {variant} has no updates",
                    call(path, "updates"))
    elif name == "tx-rebase-migration":
        for variant in ("install", "update", "changed-update", "ordinary-control"):
            path = setup(f"migration-{variant}")
            home = driver.root / f"home-{variant}"
            home.mkdir()
            launch = Driver(driver.kind, driver.cli, driver.client,
                            {**driver.env, "HOME": str(home), "FLATPAK_USER_DIR": str(path)},
                            driver.root, driver.evidence, driver.timeout)
            exercise(path, "install", [one])
            old_data = launch.success("run", one, "env", "XDG_DATA_HOME")
            marker = "migration-marker"
            payload = f"actual application data for {variant}"
            launch.success("run", one, "write", f"{old_data}/{marker}", payload)
            driver.check(launch.success("run", one, "read", f"{old_data}/{marker}") == payload,
                         "old application really wrote persistent data")
            if variant in {"update", "changed-update"}:
                exercise(path, "install", [two])
                # Do not launch the new app before migration: it must have no existing data.
            if variant == "changed-update":
                switch(path, "APP")
            if variant == "ordinary-control":
                exercise(path, "install", [two])
            else:
                exercise(path, "rebase", [two], previous=[one.split("/")[1]])
            deployed(path, apps | dependencies, "APP" if variant == "changed-update" else "A")
            new_data = launch.success("run", two, "env", "XDG_DATA_HOME")
            driver.check(new_data != old_data, "new application has its own public data path")
            result = launch.call("run", two, "read", f"{new_data}/{marker}")
            if variant == "ordinary-control":
                observe(result.returncode != 0, "ordinary install does not migrate data",
                        result.stdout)
            else:
                observe(result.returncode == 0 and result.stdout.strip() == payload,
                        f"{variant} rebase migrates actual application data", result.stdout)
    else:
        raise ValueError(name)
    driver.check(not failures, "\n".join(failures))
