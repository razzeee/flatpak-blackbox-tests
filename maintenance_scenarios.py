# SPDX-License-Identifier: LGPL-2.1-or-later
"""Maintenance contracts using public configuration and disposable installations."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from report_schema import EvidenceRecord
from system_selector_scenarios import Namespace
from typed_json import parse_typed

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def _definition(ns: Namespace, fixture: FixtureManifest, *, install: bool) -> None:
    directory = ns.state / "config/preinstall.d"
    directory.mkdir(exist_ok=True)
    (directory / "maintenance.preinstall").write_text(
        f"[Flatpak Preinstall {fixture['app']}]\n"
        f"Branch={fixture['branch']}\nInstall={str(install).lower()}\n"
        f"[Flatpak Preinstall {fixture['runtime']}]\n"
        f"Branch={fixture['branch']}\nIsRuntime=true\n")


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    state = driver.root / "system-selector-state"
    driver.check(not state.exists() and not state.is_symlink(),
                 "fresh maintenance state")
    try:
        ns = Namespace(driver, Path(fixture.get("directory", repository.fixtures)))
        _run(ns, fixture, name)
    finally:
        if state.exists():
            shutil.rmtree(state)


def _run(ns: Namespace, fixture: FixtureManifest, name: str) -> None:
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    short_app = app.removeprefix("app/")
    short_runtime = runtime.removeprefix("runtime/")
    ns.app_versions = {fixture["commits"]["A"]: "A", fixture["commits"]["B"]: "B"}

    if name in {"maintenance-history", "maintenance-history-equivalent"}:
        history_flags = ["--verbose", "--ostree-verbose"] if name.endswith("-equivalent") else []
        result = ns.driver.external_call(
            [*ns.prefix, "/usr/bin/python3", "-B", str(Path(__file__).resolve()),
             "--journal", ns.driver.cli, app, runtime, *history_flags], "cli")
        if history_flags:
            for line in result.stdout.splitlines():
                if not line.startswith("{"):
                    continue
                data = json.loads(line)
                if (isinstance(data, dict)
                        and data.get("argv", [])[:2] == [ns.driver.cli, "history"]):
                    record = parse_typed(data, EvidenceRecord, "history command")
                    record["interface"] = "cli"
                    ns.driver.evidence.append(record)
        if result.returncode == 77:
            ns.block("private real journal unavailable: "
                     f"{result.stdout} {result.stderr}")
        ns.equal(result.returncode, 0, f"private journal history: {result.stderr}")
        ns.driver.check(result.stdout.splitlines()[-1] == "PASS maintenance-history",
                        "history assertions completed")
        return

    if name == "maintenance-global":
        paths = ns.ok("--installations").splitlines()
        ns.equal(set(paths), {ns.paths["system"], ns.paths["alt"]},
                 "global installation paths exclude user")
        ns.equal(len(paths), 2, "no duplicate installation paths")
        outputs = []
        for options in ((), ("--print-system-only",)):
            text = ns.ok("--print-updated-env", *options)
            values = dict(line.split("=", 1) for line in text.splitlines())
            outputs.append(values)
        user, system = outputs
        key = "XDG_DATA_DIRS"
        user_paths, system_paths = user[key].split(":"), system[key].split(":")
        for scope in ("system", "alt"):
            exported = ns.paths[scope] + "/exports/share"
            ns.driver.check(exported in user_paths and exported in system_paths,
                            f"{scope} exports in both generated environments")
        exported = ns.paths["user"] + "/exports/share"
        ns.driver.check(exported in user_paths and exported not in system_paths,
                        "system-only excludes user exports present in ordinary output")
        ns.equal([path for path in user_paths if path != exported], system_paths,
                 "system-only preserves all other data directories")
        result = ns.driver.external_call(
            [*ns.prefix, "/usr/bin/env",
             "XDG_DATA_DIRS=/tmp/maintenance-sentinel:/usr/share",
             ns.driver.cli, "--print-updated-env"], "cli")
        ns.equal(result.returncode, 0, "amend supplied environment")
        amended = dict(line.split("=", 1) for line in result.stdout.splitlines())
        paths = amended[key].split(":")
        ns.driver.check("/tmp/maintenance-sentinel" in paths,
                        "generated environment retains supplied data directory")
        ns.equal(paths.count("/usr/share"), 1, "existing data directory not duplicated")
        for scope in ("system", "alt", "user"):
            ns.driver.check(ns.paths[scope] + "/exports/share" in paths,
                            "amended environment adds installation exports")
        return

    if name == "maintenance-repair-root":
        ns.remote("system")
        ns.ok("install", "--noninteractive", "fixture", app, scope="system")
        ns.installed("system", app, fixture["commits"]["A"])
        result = ns.driver.external_call(
            [*ns.prefix, "/usr/bin/python3", "-B", str(Path(__file__).resolve()),
             "--repair-root", ns.driver.cli, ns.paths["system"],
             json.dumps({app: fixture["commits"]["A"],
                         runtime: fixture["runtime_commit"]})], "cli")
        if result.returncode == 77:
            ns.block(f"third repair namespace unavailable: {result.stderr}")
        ns.equal(result.returncode, 0, f"isolated non-root repair: {result.stderr}")
        ns.driver.check(result.stdout.splitlines()[-1] == "PASS maintenance-repair-root",
                        "same-store non-root repair assertions completed")
        ns.installed("system", app, fixture["commits"]["A"])
        ns.installed("system", runtime, fixture["runtime_commit"])
        return

    _definition(ns, fixture, install=True)
    for scope in ("system", "alt", "user"):
        ns.remote(scope)
    if name == "maintenance-preinstall-download":
        ns.ok("preinstall", "--noninteractive", "--no-deploy")
        ns.equal(ns.refs("system"), set(),
                 "download-only preinstall has no deployments")
        missing = "file:///tmp/maintenance-unavailable-origin"
        ns.ok("remote-modify", f"--url={missing}", "fixture", scope="system")
        ns.ok("install", "--noninteractive", "--no-pull", "fixture", app,
              scope="system")
        ns.installed("system", app, fixture["commits"]["A"])
        ns.installed("system", runtime, fixture["runtime_commit"])
        ns.equal(ns.refs("alt"), set(),
                 "download/deploy excludes alternate installation")
        ns.equal(ns.refs("user"), set(), "download/deploy excludes user installation")
        return
    if name == "maintenance-library-preinstall":
        for action in ("install", "remove"):
            _definition(ns, fixture, install=action == "install")
            output = ns.ok("maintenance-sync", action, app, runtime, library=True)
            ns.driver.check(output.splitlines()[-1] == "PASS maintenance-sync",
                            "public transaction completed operation assertions")
            if action == "install":
                ns.installed("system", app, fixture["commits"]["A"])
            else:
                ns.equal(ns.refs("system"), {short_runtime},
                         "library sync removes vendor app and retains runtime")
            ns.installed("system", runtime, fixture["runtime_commit"])
            ns.equal(ns.refs("alt"), set(), "library sync excludes named installation")
            ns.equal(ns.refs("user"), set(), "library sync excludes user installation")
        return
    ns.ok("preinstall", "--noninteractive")
    ns.installed("system", app, fixture["commits"]["A"])
    ns.installed("system", runtime, fixture["runtime_commit"])
    ns.equal(ns.refs("alt"), set(), "default preinstall excludes named store")
    ns.equal(ns.refs("user"), set(), "default preinstall excludes user store")

    if name == "maintenance-preinstall-sync":
        _definition(ns, fixture, install=False)
        ns.ok("preinstall", "--noninteractive")
        ns.equal(ns.refs("system"), {short_runtime},
                 "vendor removal retains designated runtime")
        ns.driver.check(ns.call("info", app, scope="system").returncode != 0,
                        "vendor-removed app cannot be queried")
        _definition(ns, fixture, install=True)
        ns.ok("preinstall", "--noninteractive")
        ns.equal(ns.refs("system"), {short_app, short_runtime},
                 "vendor-removed app can be preinstalled again")
        ns.installed("system", app, fixture["commits"]["A"])
        return

    if name == "maintenance-preinstall-optout":
        ns.ok("uninstall", "--noninteractive", app, scope="system")
        ns.equal(ns.refs("system"), {short_runtime}, "manual removal baseline")
        # Identical configuration and remote in a fresh named installation give
        # the counterfactual: the definition remains actionable after opt-out.
        ns.ok("preinstall", "--noninteractive", scope="alt")
        ns.installed("alt", app, fixture["commits"]["A"])
        ns.ok("preinstall", "--noninteractive", scope="system")
        ns.equal(ns.refs("system"), {short_runtime}, "manual uninstall opts out")
        ns.installed("alt", app, fixture["commits"]["A"])
        ns.equal(ns.refs("user"), set(), "selected preinstalls exclude user")
        ns.ok("preinstall", "--noninteractive", scope="user")
        ns.installed("user", app, fixture["commits"]["A"])
        ns.equal(ns.refs("system"), {short_runtime},
                 "user selector does not undo default opt-out")
        return
    raise ValueError(f"unknown maintenance scenario: {name}")


def _repair_guard(uid: int) -> None:
    assert os.getuid() == os.geteuid() == os.getgid() == os.getegid() == uid
    expected_map = [str(uid), "0", "1"]
    assert Path("/proc/self/uid_map").read_text().split() == expected_map
    assert Path("/proc/self/gid_map").read_text().split() == expected_map
    outer = json.loads(Path("/tmp/selector-outer-map.json").read_text())
    assert outer[0] == "0" and outer[1] != "0" and outer[2] == "1"
    assert not any(key in os.environ for key in (
        "FLATPAK_SYSTEM_DIR", "FLATPAK_CONFIG_DIR", "FLATPAK_USER_DIR",
        "DBUS_SYSTEM_BUS_ADDRESS", "DBUS_SESSION_BUS_ADDRESS"))
    assert not Path("/run/dbus/system_bus_socket").exists()
    mounts = {line.split()[1]: line.split()[3].split(",")
              for line in Path("/proc/mounts").read_text().splitlines()}
    assert "ro" in mounts["/"]
    for path in ("/var", "/root", "/run", "/tmp",
                 os.environ["BLACKBOX_SYSTEM_INSTALL_DIR"]):
        assert "rw" in mounts[path], path
    assert "ro" in mounts[os.environ["BLACKBOX_SYSTEM_CONFIG_DIR"]]
    print(json.dumps({"uid": os.getuid(), "euid": os.geteuid(), "gid": os.getgid(),
                      "uid_map": expected_map, "gid_map": expected_map,
                      "outer_uid_map": outer, "host_root_read_only": True,
                      "host_bus": False, "installation_redirects": False}), flush=True)


def _repair_call(cli: str, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run([cli, *args], text=True, capture_output=True,
                            check=False, timeout=60)
    print(json.dumps({"argv": [cli, *args], "exit_status": result.returncode,
                      "stdout": result.stdout, "stderr": result.stderr}), flush=True)
    return result


def _repair_identity(cli: str, system: str,
                     commits: dict[str, str]) -> dict[str, list[int]]:
    """Compare filesystem identities only at public installation/deployment paths."""
    paths = [system]
    for ref, commit in commits.items():
        result = _repair_call(cli, "info", "--system", "--show-ref", "--show-commit", ref)
        assert result.returncode == 0, result.stderr
        assert result.stdout.split() == [ref, commit], result.stdout
        location = _repair_call(cli, "info", "--system", "--show-location", ref)
        assert location.returncode == 0, location.stderr
        deployment = Path(location.stdout.strip())
        assert deployment.is_absolute() and deployment.is_dir()
        assert deployment != Path(system) and deployment.is_relative_to(system)
        paths.append(str(deployment))
    identity = {}
    for path in paths:
        stat = Path(path).stat()
        identity[path] = [stat.st_dev, stat.st_ino]
    assert Path(system).stat().st_uid == os.getuid()
    assert os.access(system, os.W_OK), "system base must be caller-writable"
    print(json.dumps({"uid": os.getuid(), "system_owner": Path(system).stat().st_uid,
                      "system_writable": True, "public_path_identity": identity}),
          flush=True)
    return identity


def _repair_root(cli: str, system: str, commits_json: str) -> int:
    _repair_guard(0)
    commits = json.loads(commits_json)
    _repair_identity(cli, system, commits)
    control = _repair_call(cli, "repair", "--system")
    assert control.returncode == 0, control.stderr
    diagnostic = (control.stdout + control.stderr).lower()
    assert "dry-run" not in diagnostic and "privileges are required" not in diagnostic
    # Authorized repair may rebuild deployments. Preserve ref/commit checks,
    # but establish filesystem identity only for the subsequent read-only phase.
    identity = _repair_identity(cli, system, commits)
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        return 77
    Path("/run/user/1000").mkdir(mode=0o700)
    argv = [bwrap, "--unshare-all", "--die-with-parent", "--new-session",
            "--bind", "/", "/"]
    for path in ("/var", "/root", "/run", "/tmp", system):
        argv += ["--bind", path, path]
    argv += ["--proc", "/proc", "--dev", "/dev", "--uid", "1000", "--gid", "1000",
             "--cap-drop", "ALL", "--setenv", "XDG_RUNTIME_DIR", "/run/user/1000",
             "--chdir", "/tmp", "/usr/bin/python3", "-B", str(Path(__file__).resolve()),
             "--repair-nonroot", cli, system, commits_json, json.dumps(identity)]
    result = subprocess.run(argv, text=True, capture_output=True, check=False, timeout=90)
    print(json.dumps({"argv": argv, "exit_status": result.returncode,
                      "stdout": result.stdout, "stderr": result.stderr}), flush=True)
    if result.returncode and result.stderr.startswith("bwrap:"):
        print(result.stderr, file=sys.stderr)
        return 77
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "PASS maintenance-repair-nonroot"
    assert _repair_identity(cli, system, commits) == identity
    print("PASS maintenance-repair-root")
    return 0


def _repair_nonroot(cli: str, system: str, commits_json: str, identity_json: str) -> int:
    _repair_guard(1000)
    commits = json.loads(commits_json)
    identity = json.loads(identity_json)
    assert _repair_identity(cli, system, commits) == identity
    result = _repair_call(cli, "repair", "--system")
    diagnostic = (result.stdout + result.stderr).lower()
    denied = result.returncode != 0 and "root" in diagnostic
    readonly = (result.returncode == 0 and "privileges are required" in diagnostic
                and "assuming --dry-run" in diagnostic)
    assert denied or readonly, diagnostic
    assert _repair_identity(cli, system, commits) == identity
    print("PASS maintenance-repair-nonroot")
    return 0


def _history_change(label: str) -> str | None:
    """Recognize lifecycle concepts, not pull/remote wording or event counts.

    The manual names installs, updates and removals, but does not specify exact
    labels. Accept common noun/verb forms and an optional deployment prefix.
    Unknown labels are auxiliary; they cannot satisfy a required lifecycle step.
    """
    words = label.casefold().replace("-", " ").split()
    if words and words[0] in ("deploy", "deployed", "deployment"):
        words = words[1:]
    aliases = {"install": "install", "installed": "install", "installation": "install",
               "update": "update", "updated": "update",
               "uninstall": "uninstall", "uninstalled": "uninstall",
               "remove": "uninstall", "removed": "uninstall", "removal": "uninstall"}
    return aliases.get(" ".join(words))


def _history_contract(rows: list[str], installation: str,
                      required: list[tuple[str, str]]) -> None:
    """Require ordered (ref, lifecycle) steps in installation/ref/change columns."""
    lifecycle = []
    for row in rows:
        fields = row.split("\t")
        assert len(fields) == 3, f"expected installation/ref/change columns: {row!r}"
        source, ref, label = fields
        # Named system IDs may carry a presentation wrapper in this column.
        if source.startswith("system (") and source.endswith(")"):
            source = source[len("system ("):-1]
        elif source == "default":
            source = "system"
        change = _history_change(label)
        # The documented installation column may identify a temporary repository
        # for auxiliary operations. It must name the selected store for lifecycle
        # evidence, and never another configured installation for any record.
        assert source == installation or (change is None and Path(source).is_absolute()), (
            f"history source {source!r} differs from selected {installation!r}")
        if change is not None:
            lifecycle.append((ref, change))
    remaining = iter(lifecycle)
    for step in required:
        assert any(event == step for event in remaining), (
            f"missing or out-of-order lifecycle step {step!r}: {lifecycle!r}")


def _history_controls() -> None:
    app = "app/org.flatpak.History/x86_64/test"
    runtime = "runtime/org.flatpak.HistoryPlatform/x86_64/test"
    required = [(runtime, "install"), (app, "install"),
                (app, "update"), (app, "uninstall")]
    rows = [f"user\t{runtime}\tinstalled", f"user\t{app}\tdeploy install",
            f"user\t{app}\tupdated", f"user\t{app}\tremoval"]
    _history_contract(rows, "user", required)
    _history_contract([row.replace("user\t", "system (alt)\t", 1) for row in rows],
                      "alt", required)
    extra = ["user\t\tremote configuration changed", f"user\t{app}\tpull",
             "/tmp/history-transfer\t\ttransfer completed"]
    augmented = [*extra, rows[0], rows[0], *extra, *rows[1:], *extra]
    _history_contract(augmented, "user", required)
    invalid = [([row.replace("user\t", "system (alt)\t", 1) for row in rows],
                "wrong selector"),
               ([rows[0], rows[2], rows[1], rows[3]], "wrong chronological order"),
               (["\t".join(reversed(row.split("\t"))) for row in rows], "wrong columns")]
    invalid.extend((rows[:index] + rows[index + 1:], f"omitted {step}")
                   for index, step in enumerate(required))
    for candidate, reason in invalid:
        try:
            _history_contract(candidate, "user", required)
        except AssertionError:
            continue
        raise AssertionError(f"history control accepted {reason}")
    print(json.dumps({"history_controls": "passed", "negative_controls": len(invalid),
                      "auxiliary_events_accepted": True,
                      "duplicate_events_accepted": True, "semantic_aliases_accepted": True}))


def _journal(cli: str, app: str, runtime: str, *history_options: str) -> int:
    """One guarded namespace invocation keeps its real journald alive for all calls."""
    assert os.getuid() == 0
    assert all(option in {"--verbose", "--ostree-verbose"} for option in history_options)
    assert Path("/proc/self/uid_map").read_text().split() == ["0", "0", "1"]
    outer = json.loads(Path("/tmp/selector-outer-map.json").read_text())
    assert outer[0] == "0" and outer[1] != "0" and outer[2] == "1"
    daemon = Path("/usr/lib/systemd/systemd-journald")
    if not daemon.is_file():
        print("systemd-journald executable missing")
        return 77
    config = Path("/etc/systemd")
    config.mkdir()
    (config / "journald.conf").write_text(
        "[Journal]\nStorage=volatile\nForwardToSyslog=no\nForwardToKMsg=no\n"
        "ForwardToConsole=no\nRateLimitIntervalSec=0\n")
    log = Path("/tmp/maintenance-journald.log")
    with log.open("w") as stream:
        journal = subprocess.Popen([str(daemon)], stdout=stream, stderr=stream)
    try:
        for _ in range(100):
            if Path("/run/systemd/journal/socket").exists():
                break
            if journal.poll() is not None:
                print(log.read_text())
                return 77
            time.sleep(0.05)
        else:
            print(log.read_text())
            return 77

        def call(*args: str) -> str:
            if args[0] == "history":
                args = (args[0], *history_options, *args[1:])
            result = subprocess.run([cli, *args], text=True, capture_output=True,
                                    check=False, timeout=60)
            print(json.dumps({"argv": [cli, *args], "exit_status": result.returncode,
                              "stdout": result.stdout, "stderr": result.stderr}),
                  flush=True)
            diagnostic = result.stderr.lower()
            storage = any(text in diagnostic for text in
                          ("disk quota exceeded", "no space left on device"))
            xattr = ("xattr" in diagnostic and any(text in diagnostic for text in
                     ("operation not permitted", "permission denied")))
            if result.returncode and (storage or xattr):
                raise SystemExit(77)
            assert result.returncode == 0, result.stderr
            return result.stdout.strip()

        for selector in ("--user", "--system", "--installation=alt"):
            call("remote-add", selector, "--no-gpg-verify", "fixture",
                 "file:///tmp/system-selector-fixtures/A")
            call("install", selector, "--noninteractive", "fixture", runtime)
            call("install", selector, "--noninteractive", "fixture", app)
        for selector in ("--user", "--installation=alt"):
            call("remote-modify", selector,
                 "--url=file:///tmp/system-selector-fixtures/B", "fixture")
            call("update", selector, "--noninteractive", app)
        call("uninstall", "--user", "--noninteractive", app)
        # journalctl synchronizes the real daemon through its own private socket.
        flushed = subprocess.run(["journalctl", "--sync"],
                                 text=True, capture_output=True,
                                 check=False, timeout=15)
        print(json.dumps({"argv": ["journalctl", "--sync"],
                          "exit_status": flushed.returncode,
                          "stdout": flushed.stdout, "stderr": flushed.stderr}),
              flush=True)
        if flushed.returncode:
            print(log.read_text())
            return 77
        columns = "--columns=installation,ref,change"
        user = call("history", "--user", columns).splitlines()
        required = [(runtime, "install"), (app, "install"),
                    (app, "update"), (app, "uninstall")]
        _history_contract(user, "user", required)
        for selector, installation, steps in (
            ("--system", "system", required[:2]),
            ("--installation=alt", "alt", required[:3]),
        ):
            rows = call("history", selector, columns).splitlines()
            _history_contract(rows, installation, steps)
            try:
                _history_contract(rows, "user", required)
            except AssertionError:
                pass
            else:
                raise AssertionError("wrong installation history satisfied user contract")
        reverse = call("history", "--user", "--reverse", columns).splitlines()
        assert reverse == user[::-1], reverse
        assert call("history", "--user", "--since=2100-01-01", columns) == ""
        assert call("history", "--user", "--until=2000-01-01", columns) == ""
        print("PASS maintenance-history")
        return 0
    finally:
        journal.terminate()
        try:
            journal.wait(timeout=5)
        except subprocess.TimeoutExpired:
            journal.kill()
            journal.wait(timeout=5)


if __name__ == "__main__":
    if sys.argv[1:] == ["--history-checks"]:
        _history_controls()
        raise SystemExit(0)
    if len(sys.argv) in (5, 7) and sys.argv[1] == "--journal":
        raise SystemExit(_journal(*sys.argv[2:]))
    if len(sys.argv) == 5 and sys.argv[1] == "--repair-root":
        raise SystemExit(_repair_root(*sys.argv[2:]))
    if len(sys.argv) == 6 and sys.argv[1] == "--repair-nonroot":
        raise SystemExit(_repair_nonroot(*sys.argv[2:]))
    raise SystemExit("internal private namespace runner only")
