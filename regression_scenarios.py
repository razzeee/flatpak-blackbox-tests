# SPDX-License-Identifier: LGPL-2.1-or-later
"""Focused upstream regressions, using independent commits and public observations."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from sandbox_scenarios import _config

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


class PreparedRepository:
    """Reference-only input construction; never inspect the target's object store."""

    def __init__(self, driver: Driver, fixture: FixtureManifest) -> None:
        self.driver = driver
        self.fixture = fixture
        self.path = driver.root / "regression-repo"
        shutil.copytree(Path(fixture["directory"]) / "B", self.path)

    def ostree(self, *args: str) -> str:
        from run import DiagnosticFailure

        result = self.driver.external_call(["ostree", f"--repo={self.path}", *args], "setup")
        if result.returncode:
            raise DiagnosticFailure(f"independent regression fixture failed: {result.stderr}")
        return result.stdout.strip()

    def checkout(self, commit: str, label: str) -> Path:
        tree = self.driver.root / label
        self.ostree("checkout", "--user-mode", "--force-copy", "--disable-cache",
                    commit, str(tree))
        return tree

    def commit(self, tree: Path, ref: str, label: str) -> str:
        commit = self.ostree("commit", f"--branch={ref}", f"--tree=dir={tree}",
                             "--owner-uid=0", "--owner-gid=0", "--no-xattrs",
                             "--canonical-permissions",
                             f"--add-metadata-string=xa.metadata={(tree / 'metadata').read_text()}",
                             f"--subject={label}")
        self.ostree("summary", "--update")
        (self.path / "summary.idx").unlink(missing_ok=True)
        return commit


def _repair_pins(driver: Driver, fixture: FixtureManifest, app: str, runtime: str) -> None:
    from install_option_scenarios import _state

    repo = PreparedRepository(driver, fixture)
    control = runtime.rsplit("/", 1)[0] + "/pinned-control"
    tree = repo.checkout(fixture["runtime_commit"], "pinned-control-input")
    control_commit = repo.commit(tree, control, "Independent pinned control branch")
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "control", str(repo.path))
    driver.cli_success("install", "--user", "--noninteractive", "control", control)
    driver.cli_success("pin", "--user", control)
    before = set(driver.cli_success("pin", "--user").splitlines())
    driver.check(before == {control}, "only the independent control runtime is pinned")
    expected = (Path(fixture["directory"]) / fixture["assets"]["app_tree"] /
                "files/bin/blackbox-probe").read_bytes()
    command = "--command=/app/bin/blackbox-probe"
    for options in ((), ("--reinstall-all",)):
        if options:
            location = Path(driver.cli_success("info", "--user", "--show-location", app))
            executable = location / "files/bin/blackbox-probe"
            driver.check(executable.resolve().is_relative_to(driver.root)
                         and executable.read_bytes() == expected,
                         "redeployment control is the independent app inside isolated state")
            executable.unlink()
            driver.evidence.append({"observation": "removed-deployed-executable",
                                    "data": str(executable)})
            driver.check(driver.call("run", command, app).returncode != 0,
                         "missing app executable establishes forced-redeployment control")
        driver.cli_success("repair", "--user", *options)
        driver.check(set(driver.cli_success("pin", "--user").splitlines()) == before,
                     "repair must preserve pins without pinning automatic dependencies")
        driver.query(app, fixture["commits"]["A"])
        driver.query(runtime, fixture["runtime_commit"])
        driver.query(control, control_commit)
        if options:
            location = Path(driver.cli_success("info", "--user", "--show-location", app))
            driver.check((location / "files/bin/blackbox-probe").read_bytes() == expected
                         and driver.success("run", command, app) == "A",
                         "reinstall-all really redeploys A without changing pin policy")
    driver.cli_success("uninstall", "--user", "--noninteractive", app)
    driver.cli_success("uninstall", "--user", "--noninteractive", "--unused")
    _state(driver, {control: control_commit})


def _wrapped(driver: Driver, command: str, app: str) -> None:
    import shlex

    words = shlex.split(command)
    driver.check(len(words) > 2 and Path(words[0]).name == Path(driver.cli).name
                 and words[1] == "run" and app in words,
                 f"exported command must launch the application through Flatpak: {command}")


def _export_filter(driver: Driver, fixture: FixtureManifest, app: str) -> None:
    identity = fixture["app"]
    repo = PreparedRepository(driver, fixture)
    tree = repo.checkout(fixture["commits"]["A"], "export-input")
    desktop = tree / f"export/share/applications/{identity}.desktop"
    service = tree / f"export/share/dbus-1/services/{identity}.service"
    desktop.parent.mkdir(parents=True, exist_ok=True)
    service.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text(
        "[Desktop Entry]\nType=Application\nName=Safe name\nName[de]=Sicherer Name\n"
        f"Icon={identity}\nExec=blackbox-probe\nActions=Inspect;\nTryExec=/nonexistent\n"
        "X-Blackbox-Unsafe=discard\nX-GNOME-AutoRestart=true\n"
        "[Desktop Action Inspect]\nName=Inspect\nExec=blackbox-probe args action\n"
        "X-Blackbox-Unsafe=discard\n[Blackbox Unknown]\nExec=/nonexistent\n")
    service.write_text(f"[D-BUS Service]\nName={identity}\nExec=blackbox-probe\n"
                       "SystemdService=blackbox-never-activate.service\nUser=root\n"
                       "X-Blackbox-Unsafe=discard\n[Blackbox Unknown]\nName=discard\n")
    commit = repo.commit(tree, app, "Independent unsanitized export input")
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "exports", str(repo.path))
    driver.cli_success("install", "--user", "--noninteractive", "--reinstall", "exports", app)
    driver.query(app, commit)
    exports = Path(driver.env["XDG_DATA_HOME"]) / "flatpak/exports/share"
    config = _config((exports / f"applications/{identity}.desktop").read_text())
    driver.check(set(config.sections()) == {"Desktop Entry", "Desktop Action Inspect"},
                 "desktop exports discard unknown groups but retain valid actions")
    main = config["Desktop Entry"]
    driver.check(main["Name"] == "Safe name" and main["Name[de]"] == "Sicherer Name"
                 and main["Icon"] == identity and main["Actions"] == "Inspect;",
                 "safe and localized desktop fields must survive sanitization")
    for key in ("TryExec", "X-Blackbox-Unsafe", "X-GNOME-AutoRestart"):
        driver.check(key not in main, f"unsafe desktop key {key} must not be exported")
    _wrapped(driver, main["Exec"], identity)
    action = config["Desktop Action Inspect"]
    driver.check(action["Name"] == "Inspect" and "X-Blackbox-Unsafe" not in action,
                 "actions retain safe fields, not arbitrary extensions")
    _wrapped(driver, action["Exec"], identity)
    config = _config((exports / f"dbus-1/services/{identity}.service").read_text())
    driver.check(config.sections() == ["D-BUS Service"], "unknown service groups are removed")
    entry = config["D-BUS Service"]
    driver.check(set(entry) == {"Name", "Exec"} and entry["Name"] == identity,
                 "service exports retain only safe name and rewritten execution")
    _wrapped(driver, entry["Exec"], identity)
    driver.check(driver.success("run", app) == "A", "sanitization preserves a runnable app")


def _snapshot(directory: Path) -> dict[str, tuple[str, bytes | str]]:
    """Record file types as well as bytes, without following canary symlinks."""
    result: dict[str, tuple[str, bytes | str]] = {}
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory).as_posix()
        if path.is_symlink():
            result[relative] = ("symlink", os.readlink(path))
        elif path.is_file():
            result[relative] = ("file", path.read_bytes())
        elif path.is_dir():
            result[relative] = ("directory", "")
        else:
            raise ValueError(f"unexpected canary type: {path}")
    return result


def _deployment_traversal(driver: Driver, fixture: FixtureManifest, app: str,
                          runtime: str, kind: str) -> None:
    repo = PreparedRepository(driver, fixture)
    canary = driver.root / "external-canary"
    canary.mkdir()
    ref = runtime if kind == "etc" else app
    original = fixture["runtime_commit"] if kind == "etc" else fixture["commits"]["A"]
    tree = repo.checkout(original, "malicious-input")
    if kind == "etc":
        for name in ("passwd", "group", "machine-id"):
            (canary / f"{name}-original").write_text(f"independent {name} bytes\n")
            (canary / name).symlink_to(f"{name}-original")
        (canary / "resolv.conf").write_text("independent resolver bytes\n")
        path = tree / "files/etc"
    else:
        (canary / "bin").mkdir()
        (canary / "bin/keep").write_text("independent deletion canary\n")
        path = tree / "export"
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
    path.symlink_to(canary)
    malicious = repo.commit(tree, ref, f"Private {kind} symlink attack input")
    before = _snapshot(canary)
    driver.cli_success("remote-modify", "--user", f"--url={repo.path.as_uri()}", "fixture")
    # A failed deployment is allowed, but a crash, a no-op at the wrong revision,
    # or a damaged external canary must never count as confinement.
    result = driver.call("update", ref)
    driver.check(_snapshot(canary) == before,
                 f"deployment must not traverse {kind} into the external canary")
    driver.check(result.returncode >= 0, "malformed deployment must not crash the client")
    driver.query(ref, malicious if result.returncode == 0 else original)
    valid_tree = repo.checkout(original, "valid-recovery-input")
    recovered = repo.commit(valid_tree, ref, "Valid update following malformed deployment")
    driver.success("update", ref)
    driver.query(ref, recovered)
    driver.check(_snapshot(canary) == before, "valid recovery also preserves external canaries")
    driver.check(driver.success("run", app) == "A",
                 "a valid update remains deployable and runnable")


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    repository.version = "A"
    driver.setup_success("remote", url)
    driver.setup_success("install", app)
    driver.query(app, fixture["commits"]["A"])
    driver.check(driver.success("run", app) == "A", "healthy app control must run")
    if name == "repair-pins":
        _repair_pins(driver, fixture, app, runtime)
    elif name == "sandbox-export-filter":
        _export_filter(driver, fixture, app)
    elif name.startswith("sandbox-deployment-"):
        _deployment_traversal(driver, fixture, app, runtime,
                              name.removeprefix("sandbox-deployment-"))
    elif name == "sandbox-process-group":
        for operation in ("kill", "killpg"):
            command = [driver.cli, "run", "--user", app, "signal-group", operation]
            result = driver.external_call([
                sys.executable, str(Path(__file__).with_name("signal_supervisor.py")),
                str(driver.timeout), *command,
            ], "cli")
            driver.evidence[-1]["cli_argv"] = command
            driver.check(result.returncode == 0,
                         f"process-group isolation failed: {result.stderr}")
            driver.check(result.stdout == f"{operation} isolated\n",
                         f"{operation} executes without reaching the host supervisor")
    elif name == "instance-fd-immediate":
        output = driver.success("instance-fd-immediate", driver.cli, app,
                                fixture["commits"]["A"])
        driver.check(output == "immediate-instance-ok", "client completed immediate ID assertions")
    else:
        raise ValueError(f"unknown regression scenario: {name}")
