# SPDX-License-Identifier: LGPL-2.1-or-later
"""Document CLI contracts against a private real document portal and sandbox."""

from __future__ import annotations

import ast
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from permission_scenarios import _service
from sandbox_scenarios import _denied, _external_service, _probe

if TYPE_CHECKING:
    from run import Driver, RepositoryServer

BUS = "org.freedesktop.portal.Documents"
OTHER = "org.flatpak.DocumentControl"


def _bus(driver: Driver, method: str, *args: str) -> str:
    result = driver.external_call(
        ["gdbus", "call", "--session", "--dest", BUS,
         "--object-path", "/org/freedesktop/portal/documents",
         "--method", f"{BUS}.{method}", *args], "setup")
    driver.check(result.returncode == 0, f"Documents.{method}: {result.stderr}")
    return result.stdout.strip()


@contextmanager
def _portal(driver: Driver) -> Iterator[Path]:
    from run import PrerequisiteError

    if not os.access("/dev/fuse", os.R_OK | os.W_OK):
        raise PrerequisiteError("document contracts require accessible /dev/fuse")
    executable = next((str(path) for path in (
        Path("/usr/libexec/xdg-document-portal"), Path("/usr/lib/xdg-document-portal"))
        if path.is_file()), None)
    if executable is None:
        raise PrerequisiteError("real xdg-document-portal is required")
    mount = Path(driver.env["XDG_RUNTIME_DIR"]) / "doc"
    try:
        with _external_service(driver, executable) as process:
            deadline = time.monotonic() + 10
            while True:
                owner = driver.external_call(
                    ["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                     "--object-path", "/org/freedesktop/DBus", "--method",
                     "org.freedesktop.DBus.NameHasOwner", BUS], "setup")
                if owner.returncode == 0 and owner.stdout.strip() == "(true,)":
                    break
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise PrerequisiteError("private document portal did not acquire its bus name")
                time.sleep(0.05)
            reported, = ast.literal_eval(_bus(driver, "GetMountPoint"))
            driver.check(reported == os.fsencode(mount), "portal mount is inside case runtime")
            driver.check(mount.is_mount(), "document portal has a live FUSE mount")
            yield mount
    finally:
        result = driver.external_call(["fusermount3", "-u", str(mount)], "setup")
        driver.check(not mount.is_mount(), f"document mount cleaned up: {result.stderr}")


def _export(driver: Driver, mount: Path, file: Path, *options: str) -> Path:
    path = Path(driver.cli_success("document-export", *options, str(file)))
    driver.check(path.is_absolute() and path.parent.parent == mount and path.name == file.name,
                 f"export returns document path under private mount: {path}")
    return path


def _permissions(driver: Driver, document: Path, origin: Path,
                 expected: dict[str, list[str]]) -> None:
    output = _bus(driver, "Info", document.parent.name)
    original, permissions = ast.literal_eval(output.replace("@a{sas} ", "").replace("@as ", ""))
    driver.check(original == os.fsencode(origin), f"document origin: {output}")
    actual = {app: set(values) for app, values in permissions.items()}
    driver.check(actual == {app: set(values) for app, values in expected.items()},
                 f"document permissions: {output}")


def _rows(driver: Driver, expected: set[tuple[str, str]], *apps: str) -> None:
    output = driver.cli_success("documents", "--columns=id,origin", *apps)
    rows = [tuple(line.split("\t")) for line in output.splitlines()]
    driver.check(len(rows) == len(expected) and set(rows) == expected,
                 f"document rows: expected {expected!r}, got {rows!r}")


def _ids(driver: Driver, expected: set[str], *apps: str) -> None:
    output = driver.cli_success("documents", *apps)
    if output == "No documents found":
        output = ""
    identifiers = [line.split("\t", 1)[0] for line in output.splitlines()]
    driver.check(len(identifiers) == len(expected) and set(identifiers) == expected,
                 f"document IDs: expected {expected!r}, got {identifiers!r}")


def _listed(driver: Driver, expected: dict[str, Path]) -> None:
    output = _bus(driver, "List", "")
    documents, = ast.literal_eval(output.replace("@a{say} ", ""))
    driver.check(documents == {key: os.fsencode(path) for key, path in expected.items()},
                 f"public document list: {output}")


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    app = fixture["app"]
    file = driver.root / "document with spaces.txt"
    file.write_text("document-original")
    control = driver.root / "control.txt"
    control.write_text("control-original")
    sandbox = name in {"documents-read", "documents-write", "documents-revoke"}
    if sandbox:
        repository.version = "A"
        driver.success("remote", url)
        driver.success("install", f"app/{app}/{fixture['arch']}/{fixture['branch']}")
        _denied(driver, app, "read", str(file))

    with _service(driver):
        with _portal(driver) as mount:
            document = _export(driver, mount, file, f"--app={app}")
            _permissions(driver, document, file, {app: ["read"]})
            identifier = document.parent.name
            if sandbox:
                runtime = _probe(driver, app, "env", "XDG_RUNTIME_DIR")
                inside = str(Path(runtime) / "doc" / identifier / file.name)
                driver.check(_probe(driver, app, "read", inside) == "document-original",
                             "sandbox can read grant while original path is denied")

            if name == "documents-read":
                _denied(driver, app, "write", inside, "must-not-write")
                driver.check(file.read_text() == "document-original", "default grant is read-only")
            elif name == "documents-write":
                _export(driver, mount, file, f"--app={app}", "--allow-write")
                _permissions(driver, document, file, {app: ["read", "write"]})
                _probe(driver, app, "write", inside, "document-written")
                driver.check(file.read_text() == "document-written", "write grant changes origin")
                _export(driver, mount, file, f"--app={app}", "--forbid-write")
                _permissions(driver, document, file, {app: ["read"]})
                _denied(driver, app, "write", inside, "must-not-write")
                driver.check(file.read_text() == "document-written",
                             "revoked write leaves origin intact")
                driver.check(_probe(driver, app, "read", inside) == "document-written",
                             "write revocation preserves read grant")
            elif name == "documents-unique":
                reused = _export(driver, mount, file, f"--app={app}")
                driver.check(reused == document, "ordinary export reuses existing document")
                unique = _export(driver, mount, file, "--unique", f"--app={OTHER}")
                driver.check(unique.parent.name != identifier, "unique export has distinct ID")
                _permissions(driver, unique, file, {OTHER: ["read"]})
                _permissions(driver, document, file, {app: ["read"]})
                driver.cli_success("document-unexport", "--doc-id", unique.parent.name)
                driver.check(document.read_text() == "document-original",
                             "original export survives")
            elif name == "documents-info":
                for permissions, options in ((["read", "write"], ("--allow-write",)),
                                             (["read"], ("--forbid-write",))):
                    _export(driver, mount, file, f"--app={app}", *options)
                    for path in (file, document):
                        output = driver.cli_success("document-info", str(path))
                        lines = output.splitlines()
                        fields = dict(line.split(":", 1) for line in lines if ":" in line)
                        driver.check({key: value.strip() for key, value in fields.items()} == {
                            "id": identifier, "path": str(document), "origin": str(file),
                            "permissions": ""}, f"document identity fields: {output}")
                        grants = [line.split(None, 1) for line in lines if line[:1].isspace()]
                        driver.check(len(grants) == 1 and grants[0][0] == app and
                                     set(grants[0][1].split(", ")) == set(permissions),
                                     f"document-info reflects current permissions: {output}")
            elif name in {"documents-enumerate", "documents-filter"}:
                other = _export(driver, mount, control, f"--app={OTHER}")
                expected = {(identifier, str(file)), (other.parent.name, str(control))}
                if name == "documents-enumerate":
                    _rows(driver, expected)
                else:
                    _ids(driver, {identifier, other.parent.name})
                    _ids(driver, {identifier}, app)
                    _ids(driver, {other.parent.name}, OTHER)
                    _ids(driver, set(), "org.flatpak.AbsentDocumentApp")
            elif name in {"documents-revoke", "documents-by-id"}:
                other = _export(driver, mount, control, f"--app={OTHER}")
                if name == "documents-by-id":
                    file.unlink()
                    driver.cli_success("document-unexport", "--doc-id", identifier)
                else:
                    driver.cli_success("document-unexport", str(file))
                    _denied(driver, app, "read", inside)
                    driver.check(file.read_text() == "document-original", "unexport retains origin")
                driver.check(not document.exists(), "unexport removes FUSE document")
                _listed(driver, {other.parent.name: control})
                _permissions(driver, other, control, {OTHER: ["read"]})
            elif name == "documents-permissions":
                for permission in ("read", "write", "delete", "grant-permission"):
                    _export(driver, mount, file, f"--app={app}", f"--allow-{permission}")
                    token = "grant-permissions" if permission == "grant-permission" else permission
                    _permissions(driver, document, file, {app: sorted({"read", token})})
                    _export(driver, mount, file, f"--app={app}", f"--forbid-{permission}")
                    _permissions(driver, document, file,
                                 {} if permission == "read" else {app: ["read"]})
                _export(driver, mount, file, f"--app={app}", f"--app={OTHER}", "--allow-write")
                _permissions(driver, document, file,
                             {app: ["read", "write"], OTHER: ["read", "write"]})
            elif name == "documents-noexist":
                missing = driver.root / "not created yet.txt"
                rejected = driver.cli_call("document-export", f"--app={app}", str(missing))
                driver.check(rejected.returncode != 0, "ordinary export requires an existing file")
                created = _export(driver, mount, missing, "--noexist", f"--app={app}")
                driver.check(not missing.exists(), "noexist export does not create origin")
                missing.write_text("created-later")
                driver.check(created.read_text() == "created-later",
                             "grant resolves newly created file")
                _permissions(driver, created, missing, {app: ["read"]})
            elif name == "documents-transient":
                transient = _export(driver, mount, control, "--transient", f"--app={app}")
                _permissions(driver, transient, control, {app: ["read"]})
                _listed(driver, {identifier: file, transient.parent.name: control})
            else:
                raise ValueError(f"unknown document scenario: {name}")
        if name == "documents-transient":
            with _portal(driver) as mount:
                _listed(driver, {identifier: file})
                _permissions(driver, document, file, {app: ["read"]})
                driver.check(document.read_text() == "document-original",
                             "persistent grant survives restart")
