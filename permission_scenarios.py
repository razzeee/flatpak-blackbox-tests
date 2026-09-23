# SPDX-License-Identifier: LGPL-2.1-or-later
"""Permission CLI contracts against a private, real xdg-permission-store."""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from report_schema import EvidenceRecord

if TYPE_CHECKING:
    from run import Driver, RepositoryServer

BUS = "org.freedesktop.impl.portal.PermissionStore"
OBJECT = "/org/freedesktop/impl/portal/PermissionStore"
APP = "org.test.PermissionSubject"
OTHER = "org.test.PermissionControl"
ENTRIES = (("devices", "camera"), ("devices", "microphone"), ("location", "camera"))


def _bus(driver: Driver, method: str, *args: str) -> str:
    result = driver.external_call(
        ["gdbus", "call", "--session", "--dest", BUS, "--object-path", OBJECT,
         "--method", f"{BUS}.{method}", *args], "setup")
    driver.check(result.returncode == 0, f"PermissionStore.{method}: {result.stderr}")
    return result.stdout.strip()


@contextmanager
def _service(driver: Driver) -> Iterator[None]:
    from run import PrerequisiteError, terminate

    executable = shutil.which("xdg-permission-store")
    if executable is None:
        executable = next((str(p) for p in (Path("/usr/libexec/xdg-permission-store"),
                                           Path("/usr/lib/xdg-permission-store"))
                           if p.is_file() and os.access(p, os.X_OK)), None)
    if executable is None or shutil.which("gdbus") is None:
        raise PrerequisiteError("real xdg-permission-store and gdbus are required")
    # Use the runner's isolated XDG_DATA_HOME. Flatpak discovers table names there.
    record: EvidenceRecord = {"argv": [executable], "role": "permission-store-fixture",
                              "xdg_data_home": driver.env["XDG_DATA_HOME"]}
    driver.evidence.append(record)
    process = subprocess.Popen([executable], env=driver.env, cwd=driver.root,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        deadline = time.monotonic() + 10
        while True:
            result = driver.external_call(
                ["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                 "--object-path", "/org/freedesktop/DBus", "--method",
                 "org.freedesktop.DBus.NameHasOwner", BUS], "setup")
            if result.returncode == 0 and result.stdout.strip() == "(true,)":
                break
            if process.poll() is not None or time.monotonic() >= deadline:
                raise PrerequisiteError("real permission store did not acquire its bus name")
            time.sleep(0.05)
        yield
    finally:
        terminate(process)
        stdout, stderr = process.communicate()
        record.update({"stdout": stdout, "stderr": stderr, "exit_status": process.wait(),
                       "cleanup_confirmed": process.poll() is not None})


def _lookup(driver: Driver, table: str, entry: str,
            permissions: dict[str, list[str]], data: str = "'fixture'") -> None:
    output = _bus(driver, "Lookup", table, entry)
    permission_text, separator, data_text = output.removeprefix("(").partition(", <")
    driver.check(bool(separator), f"Lookup lacks variant data: {output}")
    actual = ast.literal_eval(permission_text.replace("@as ", "").replace("@a{sas} ", ""))
    driver.check(actual == permissions, f"{table}/{entry}: {actual!r} != {permissions!r}")
    driver.check(data_text == data + ">)", f"{table}/{entry} data: {data_text!r}")


def _seed(driver: Driver) -> None:
    for table, entry in ENTRIES:
        _bus(driver, "Set", table, "true", entry,
             repr({APP: ["read", "write"], OTHER: ["deny"]}), "<'fixture'>")
        _lookup(driver, table, entry, {APP: ["read", "write"], OTHER: ["deny"]})


def _rows(driver: Driver, args: tuple[str, ...],
          expected: set[tuple[str, ...]]) -> None:
    output = driver.cli_success(*args)
    rows = [tuple(line.split()) for line in output.splitlines()]
    driver.check(len(rows) == len(expected) and set(rows) == expected,
                 f"{args}: expected rows {expected!r}, got {rows!r}")


def _expected(entries: tuple[tuple[str, str], ...],
              apps: tuple[str, ...] = (APP, OTHER)) -> set[tuple[str, ...]]:
    return {(table, entry, app, "read,write" if app == APP else "deny", "'fixture'")
            for table, entry in entries for app in apps}


def _delete_data(driver: Driver, url: str, fixture: FixtureManifest) -> None:
    app = str(fixture["app"])
    app_ref = f"app/{app}/{fixture['arch']}/{fixture['branch']}"
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture", url)
    driver.cli_success("install", "--user", "--noninteractive", "fixture", app_ref)
    home = Path(driver.env["HOME"])
    markers = [home / ".var/app" / app / directory / "marker"
               for directory in ("cache", "config", "data")]
    control = home / ".var/app" / OTHER / "data/marker"
    for marker in [*markers, control]:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("retained app data\n")
    for table, entry in ENTRIES:
        _bus(driver, "SetPermission", table, "false", entry, app, "['yes']")
    # The control uninstall must preserve data and dynamic permissions.
    driver.cli_success("uninstall", "--user", "--noninteractive", app_ref)
    for marker in [*markers, control]:
        driver.check(marker.read_text() == "retained app data\n", "plain uninstall data")
    for table, entry in ENTRIES:
        _lookup(driver, table, entry,
                {APP: ["read", "write"], OTHER: ["deny"], app: ["yes"]})
    driver.evidence.append({"observation": "plain-uninstall-data",
                            "data": {str(p): p.read_text() for p in [*markers, control]}})
    driver.cli_success("install", "--user", "--noninteractive", "fixture", app_ref)
    driver.cli_success("uninstall", "--user", "--noninteractive", "--delete-data", app_ref)
    data_exists = (home / ".var/app" / app).exists()
    driver.evidence.append({"observation": "delete-data-uninstall",
                            "data": {"app_directory_exists": data_exists,
                                     "control_data": control.read_text()}})
    driver.check(not data_exists, "--delete-data must remove the app data directory")
    driver.check(control.read_text() == "retained app data\n", "control app data survives")
    for table, entry in ENTRIES:
        _lookup(driver, table, entry, {APP: ["read", "write"], OTHER: ["deny"]})
    _rows(driver, ("permission-show", app), set())
    driver.check(app not in driver.cli_success("list", "--user", "--app",
                                               "--columns=application").splitlines(),
                 "deleted-data app must also be uninstalled")


def _library_delete_data(driver: Driver) -> None:
    home = Path(driver.env["HOME"])
    app_dir = home / ".var/app" / APP
    marker = app_dir / "data/marker"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("library data\n")

    cancelled = driver.call("delete-data", APP, "cancel")
    driver.check(cancelled.returncode != 0, "cancelled user-data deletion must fail")
    driver.check(marker.read_text() == "library data\n",
                 "cancelled user-data deletion must preserve data")

    deleted = driver.call("delete-data", APP, "normal")
    driver.check(deleted.returncode == 0, f"library user-data deletion failed: {deleted.stderr}")
    driver.check(not app_dir.exists(), "library user-data deletion removes app data")
    for table, entry in ENTRIES:
        _lookup(driver, table, entry, {OTHER: ["deny"]})

    outside = home / ".var/outside"
    outside.write_text("must survive\n")
    invalid = driver.call("delete-data", "../outside", "normal")
    driver.check(invalid.returncode != 0, "invalid app ID must fail")
    driver.check(outside.read_text() == "must survive\n",
                 "invalid app ID must not escape the app-data directory")


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    """Exercise mutations and queries, keeping fixture operations on public D-Bus."""
    with _service(driver):
        _seed(driver)
        if name == "permissions-delete-data":
            _delete_data(driver, url, fixture)
        elif name == "library-delete-data":
            _library_delete_data(driver)
        elif name == "permissions-persist":
            driver.cli_success("permission-set", "devices", "camera", APP, "ask", "record")
            _lookup(driver, "devices", "camera", {APP: ["ask", "record"], OTHER: ["deny"]})
            _rows(driver, ("permissions", "devices", "camera"), {
                ("devices", "camera", APP, "ask,record", "'fixture'"),
                ("devices", "camera", OTHER, "deny", "'fixture'")})
            driver.cli_success("permission-set", "new-table", "new-object", APP, "yes")
            _lookup(driver, "new-table", "new-object", {APP: ["yes"]}, "byte 0x00")
        elif name == "permissions-data":
            driver.cli_success("permission-set", "--data=(uint32 42, 'payload')",
                               "devices", "camera", APP, "ask")
            _lookup(driver, "devices", "camera", {APP: ["ask"], OTHER: ["deny"]},
                    "(uint32 42, 'payload')")
            # Omitting --data must preserve the existing variant.
            driver.cli_success("permission-set", "devices", "camera", APP, "yes")
            _lookup(driver, "devices", "camera", {APP: ["yes"], OTHER: ["deny"]},
                    "(uint32 42, 'payload')")
            bad = driver.cli_call("permission-set", "--data=not a variant",
                                  "devices", "camera", APP, "no")
            driver.check(bad.returncode > 0 and bool(bad.stderr.strip()),
                         "invalid GVariant must fail with a diagnostic")
            _lookup(driver, "devices", "camera", {APP: ["yes"], OTHER: ["deny"]},
                    "(uint32 42, 'payload')")
        elif name == "permissions-selection":
            _rows(driver, ("permissions",), _expected(ENTRIES))
            _rows(driver, ("permissions", "devices"), _expected(ENTRIES[:2]))
            _rows(driver, ("permissions", "devices", "camera"), _expected(ENTRIES[:1]))
        elif name == "permissions-show":
            _rows(driver, ("permission-show", APP), _expected(ENTRIES, (APP,)))
            _rows(driver, ("permission-show", OTHER), _expected(ENTRIES, (OTHER,)))
            _rows(driver, ("permission-show", "org.test.Absent"), set())
        elif name in ("permissions-remove-app", "permissions-remove-object"):
            args = (APP,) if name.endswith("-app") else ()
            driver.cli_success("permission-remove", "devices", "camera", *args)
            if args:
                _lookup(driver, "devices", "camera", {OTHER: ["deny"]})
            else:
                output = _bus(driver, "List", "devices")
                driver.check(ast.literal_eval(output) == (["microphone"],),
                             f"selected object must disappear: {output}")
            for table, entry in ENTRIES[1:]:
                _lookup(driver, table, entry, {APP: ["read", "write"], OTHER: ["deny"]})
        elif name in ("permissions-reset-app", "permissions-reset-all"):
            driver.cli_success("permission-reset", APP)
            for table, entry in ENTRIES:
                _lookup(driver, table, entry, {OTHER: ["deny"]})
            _rows(driver, ("permission-show", APP), set())
            _rows(driver, ("permission-show", OTHER), _expected(ENTRIES, (OTHER,)))
            if name.endswith("-all"):
                driver.cli_success("permission-reset", "--all")
                for table, entry in ENTRIES:
                    _lookup(driver, table, entry, {})
                _rows(driver, ("permission-show", OTHER), set())
        else:
            raise ValueError(f"unknown permission scenario: {name}")
