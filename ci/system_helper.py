# SPDX-License-Identifier: LGPL-2.1-or-later
"""Provision and probe the selected system helper in a disposable CI machine."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import pwd
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WRITER = "bb-flatpak-writer"
READER = "bb-flatpak-reader"
INSTALLATION = Path("/var/lib/flatpak-blackbox-ci")
CONFIG = Path("/etc/flatpak/installations.d/blackbox-ci.conf")
BUS_POLICY = Path("/etc/dbus-1/system.d/org.freedesktop.Flatpak.Blackbox.conf")
POLKIT_POLICY = Path("/usr/share/polkit-1/actions/org.freedesktop.Flatpak.policy")
RULES = Path("/etc/polkit-1/rules.d/00-flatpak-blackbox.rules")
BUS_NAME = "org.freedesktop.Flatpak.SystemHelper"


def command(argv: list[str], *, success: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, text=True, capture_output=True, timeout=90, check=False)
    print(json.dumps({"argv": argv, "exit_status": result.returncode,
                      "stdout": result.stdout, "stderr": result.stderr}), flush=True)
    if success and result.returncode:
        raise RuntimeError(f"command failed: {argv}: {result.stderr}")
    return result


def bus_call(method: str, *arguments: str, success: bool = True) -> str:
    return command(["gdbus", "call", "--system", "--dest", "org.freedesktop.DBus",
                    "--object-path", "/org/freedesktop/DBus", "--method",
                    "org.freedesktop.DBus." + method, *arguments], success=success).stdout


def environment(root: Path) -> dict[str, str]:
    build = root / "build"
    return {
        "PATH": os.defpath,
        "LANG": "C.UTF-8",
        "LD_LIBRARY_PATH": str(build / "common"),
        "FLATPAK_BWRAP": str(build / "subprojects/bubblewrap/flatpak-bwrap"),
        "FLATPAK_DBUSPROXY": "/usr/bin/xdg-dbus-proxy",
        "FLATPAK_TRIGGERSDIR": str(root / "source/triggers"),
        "FLATPAK_VALIDATE_ICON": str(build / "icon-validator/flatpak-validate-icon"),
        "FLATPAK_PORTAL": str(build / "portal/flatpak-portal"),
        "FLATPAK_REVOKEFS_FUSE": str(build / "revokefs/revokefs-fuse"),
    }


def start(root: Path) -> None:
    state = root / "system-helper-state"
    # Refuse stale state and existing installations/policies rather than changing
    # an unrelated service. Cleanup is scoped to paths recorded in this directory.
    for path in (state, INSTALLATION, CONFIG, BUS_POLICY, RULES):
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"system-helper provisioning needs a fresh path: {path}")
    for user in (WRITER, READER):
        try:
            pwd.getpwnam(user)
        except KeyError:
            continue
        raise RuntimeError(f"system-helper test user already exists: {user}")
    if "true" in bus_call("NameHasOwner", BUS_NAME):
        raise RuntimeError("a system helper already owns the bus name")
    state.mkdir(mode=0o700)
    (state / "created-files").write_text("")
    (state / "created-users").write_text("")

    def install(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x") as stream:
            stream.write(content)
        path.chmod(0o644)
        with (state / "created-files").open("a") as stream:
            stream.write(str(path) + "\n")

    for user in (WRITER, READER):
        command(["useradd", "--create-home", "--shell", "/usr/sbin/nologin", user])
        with (state / "created-users").open("a") as stream:
            stream.write(user + "\n")
    try:
        pwd.getpwnam("flatpak")
    except KeyError:
        command(["systemd-sysusers", str(root / "build/system-helper/flatpak.conf")])
        (state / "helper-user-created").touch()
    INSTALLATION.mkdir(mode=0o755)
    (state / "installation-created").touch()
    install(CONFIG, f'[Installation "blackbox-ci"]\nPath={INSTALLATION}\n'
                    'DisplayName=Blackbox helper probe\nStorageType=harddisk\n')
    install(BUS_POLICY, (root / "source/system-helper/org.freedesktop.Flatpak.SystemHelper.conf")
            .read_text())
    if POLKIT_POLICY.exists():
        shutil.copy2(POLKIT_POLICY, state / "original-polkit-policy")
        POLKIT_POLICY.unlink()
    install(POLKIT_POLICY,
            (root / "build/system-helper/org.freedesktop.Flatpak.policy").read_text())
    install(RULES, 'polkit.addRule(function(action, subject) {\n'
                   '  if (action.id.indexOf("org.freedesktop.Flatpak.") !== 0) return;\n'
                   f'  if (subject.user === "{WRITER}") return polkit.Result.YES;\n'
                   f'  if (subject.user === "{READER}") return polkit.Result.AUTH_SELF;\n'
                   '});\n')
    bus_call("ReloadConfig")
    # Request polkit activation and wait for its rules watcher before the probe.
    bus_call("StartServiceByName", "org.freedesktop.PolicyKit1", "0")
    helper = root / "build/system-helper/flatpak-system-helper"
    with (root / "logs/system-helper.log").open("w") as log:
        process = subprocess.Popen([str(helper), "--no-idle-exit"], env=environment(root),
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   start_new_session=True)
    (state / "pid").write_text(str(process.pid))
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("selected system helper exited; see system-helper.log")
        if "true" in bus_call("NameHasOwner", BUS_NAME):
            owner = bus_call("GetConnectionUnixProcessID", BUS_NAME)
            match = re.fullmatch(r"\(uint32 (\d+),\)\s*", owner)
            if match is None or int(match[1]) != process.pid:
                raise RuntimeError(f"unexpected helper process owns the bus name: {owner}")
            print(f"Selected helper owns the system bus name, pid={process.pid}", flush=True)
            return
        time.sleep(0.1)
    raise RuntimeError("selected system helper did not acquire its bus name")


def probe(root: Path) -> None:
    fixture = json.loads((root / "fixtures/fixture.json").read_text())
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"

    def call(user: str, *args: str, success: bool = True) -> subprocess.CompletedProcess[str]:
        account = pwd.getpwnam(user)
        env = {**environment(root), "HOME": account.pw_dir, "USER": user, "LOGNAME": user}
        return command(["runuser", "--user", user, "--", "env", "-i",
                        *(f"{key}={value}" for key, value in env.items()),
                        str(root / "build/app/flatpak"), *args], success=success)

    os.umask(0o022)
    selector = "--installation=blackbox-ci"
    origin = (root / "fixtures/A").as_uri()
    for user in (WRITER, READER):
        identity = command(["runuser", "--user", user, "--", "id", "-u"]).stdout.strip()
        if identity != str(pwd.getpwnam(user).pw_uid) or identity == "0":
            raise RuntimeError(f"probe caller is not the expected ordinary user: {identity}")
    call(WRITER, "remote-add", selector, "--no-gpg-verify", "fixture", origin)
    call(WRITER, "install", selector, "--noninteractive", "fixture", app)
    for user in (WRITER, READER):
        for ref, expected in ((app, fixture["commits"]["A"]),
                              (runtime, fixture["runtime_commit"])):
            result = call(user, "info", selector, "--show-commit", ref)
            if result.stdout.strip() != expected:
                raise RuntimeError(f"{user} did not observe expected commit for {ref}")
    # The same operation must succeed for the allowed identity. This prevents a
    # syntax error or unsupported option from masquerading as authorization denial.
    call(WRITER, "remote-modify", selector, "--url=file:///blackbox-denied", "fixture")
    call(WRITER, "remote-modify", selector, f"--url={origin}", "fixture")
    denied = call(READER, "remote-modify", selector,
                  "--url=file:///blackbox-denied", "fixture", success=False)
    if denied.returncode == 0:
        raise RuntimeError("unauthorized reader modified the system remote")
    if "not allowed" not in denied.stderr and "not authorized" not in denied.stderr:
        raise RuntimeError(f"reader failed for a reason other than authorization: {denied.stderr}")
    remotes = call(READER, "remotes", selector, "--columns=name,url").stdout.strip()
    if remotes != f"fixture\t{origin}":
        raise RuntimeError(f"denied mutation changed the system remote: {remotes}")
    print("PASS system-helper authorization and cross-user visibility probe", flush=True)


def stop(root: Path) -> None:
    state = root / "system-helper-state"
    if not state.is_dir():
        return
    pid_file = state / "pid"
    if pid_file.exists():
        pid = int(pid_file.read_text())
        executable = Path(f"/proc/{pid}/exe")
        if executable.exists():
            expected = (root / "build/system-helper/flatpak-system-helper").resolve()
            if executable.resolve() != expected:
                raise RuntimeError("refusing to stop an unrelated process after PID reuse")
            os.kill(pid, signal.SIGTERM)
            for _ in range(100):
                if not executable.exists():
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("system helper did not stop before cleanup")
    for filename in (state / "created-files").read_text().splitlines():
        path = Path(filename)
        if path not in (CONFIG, BUS_POLICY, POLKIT_POLICY, RULES):
            raise RuntimeError(f"unexpected provisioning cleanup path: {path}")
        path.unlink(missing_ok=True)
    if (state / "original-polkit-policy").exists():
        shutil.copy2(state / "original-polkit-policy", POLKIT_POLICY)
    bus_call("ReloadConfig")
    if (state / "installation-created").exists():
        shutil.rmtree(INSTALLATION)
    for user in (state / "created-users").read_text().splitlines():
        if user not in (WRITER, READER):
            raise RuntimeError(f"unexpected provisioning cleanup user: {user}")
        command(["userdel", "--remove", user])
    if (state / "helper-user-created").exists():
        command(["userdel", "flatpak"])
    shutil.rmtree(state)


def run_case(root: Path, client: Path, fixtures: Path, scenario: str, agent: Path,
             preload: str | None) -> None:
    state = root / "system-helper-state"
    if not (state / "pid").exists():
        print("system-helper provisioning is missing", file=sys.stderr)
        raise SystemExit(77)
    pid = int((state / "pid").read_text())
    expected_helper = (root / "build/system-helper/flatpak-system-helper").resolve()
    if Path(f"/proc/{pid}/exe").resolve() != expected_helper:
        raise RuntimeError("provisioned system helper is no longer running")
    if bus_call("GetConnectionUnixProcessID", BUS_NAME).strip() != f"(uint32 {pid},)":
        raise RuntimeError("provisioned helper no longer owns the system bus name")
    fixture = json.loads((fixtures / "fixture.json").read_text())
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    a, b = fixture["commits"]["A"], fixture["commits"]["B"]
    runtime_commit = fixture["runtime_commit"]
    origin_a, origin_b = (fixtures / "A").as_uri(), (fixtures / "B").as_uri()
    with (state / "case.lock").open("w") as lock, tempfile.TemporaryDirectory(
            prefix="bb-system-case-") as temporary:
        fcntl.flock(lock, fcntl.LOCK_EX)
        directory = Path(temporary)
        directory.chmod(0o755)
        executable = directory / "client"
        shutil.copyfile(client, executable)
        executable.chmod(0o755)
        recording_agent = directory / "polkit-agent"
        shutil.copyfile(agent, recording_agent)
        recording_agent.chmod(0o755)
        homes = {}
        for user in (WRITER, READER):
            account = pwd.getpwnam(user)
            home = directory / user
            home.mkdir(mode=0o700)
            os.chown(home, account.pw_uid, account.pw_gid)
            homes[user] = home
        shutil.rmtree(INSTALLATION)
        INSTALLATION.mkdir(mode=0o755)
        os.umask(0o022)
        checked_users: set[str] = set()

        def invoke(user: str, op: str, *args: str, scope: str = "blackbox-ci") -> str:
            account = pwd.getpwnam(user)
            env = {**environment(root), "HOME": str(homes[user]), "USER": user, "LOGNAME": user,
                   "XDG_DATA_HOME": str(homes[user] / "data"),
                   "XDG_CONFIG_HOME": str(homes[user] / "config"),
                   "XDG_CACHE_HOME": str(homes[user] / "cache")}
            if preload:
                env["LD_PRELOAD"] = preload
            prefix = ["runuser", "--user", user, "--", "env", "-i",
                      *(f"{key}={value}" for key, value in env.items())]
            if user not in checked_users:
                linked = command([*prefix, "ldd", str(executable)]).stdout
                libraries = [line.split()[2] for line in linked.splitlines()
                             if line.split()[:2] == ["libflatpak.so.0", "=>"]]
                expected = (root / "build/common/libflatpak.so.0").resolve()
                if len(libraries) != 1 or Path(libraries[0]).resolve() != expected:
                    raise RuntimeError(f"{user} did not load the selected target library: {linked}")
                checked_users.add(user)
            result = command([*prefix,
                              str(executable), "multiuser", str(account.pw_uid), op, scope, *args],
                             success=False)
            # Forward actual child call traces for the runner's library evidence.
            # The complete command, output and exit status also remain in JSON above.
            sys.stderr.write(result.stderr)
            sys.stderr.flush()
            if result.returncode or not result.stdout.endswith(f"PASS multiuser {op}\n"):
                raise RuntimeError(f"{user} {op} did not complete its public assertions")
            return result.stdout

        def expect(commit: str, runtime_expected: str = runtime_commit) -> None:
            for user in (WRITER, READER):
                invoke(user, "expect", app, commit, runtime, runtime_expected)

        def remote_snapshots() -> dict[tuple[str, str], list[str]]:
            return {(user, scope): sorted(invoke(user, "remote-snapshot", scope=scope).splitlines())
                    for user in (WRITER, READER) for scope in ("system", "user")}

        try:
            controls = remote_snapshots()
            expect("-", "-")
            invoke(WRITER, "remote-add", origin_a)
            invoke(READER, "remote-query", origin_a)
            if scenario == "multiuser-remotes":
                invoke(WRITER, "remote-modify", origin_b)
                invoke(READER, "remote-query", origin_b)
                invoke(WRITER, "remote-remove")
                for user in (WRITER, READER):
                    if invoke(user, "remote-snapshot") != "PASS multiuser remote-snapshot\n":
                        raise RuntimeError("removed remote remains visible to another user")
                expect("-", "-")
            else:
                invoke(WRITER, "install", app)
                expect(a)
                if scenario == "multiuser-update":
                    invoke(WRITER, "remote-modify", origin_b)
                    invoke(WRITER, "update", app)
                    expect(b)
                elif scenario == "multiuser-uninstall":
                    invoke(WRITER, "uninstall", app)
                    expect("-")
                elif scenario == "multiuser-auth-installation":
                    invoke(WRITER, "config-set", "de")
                    for silent in ("false", "true", "false"):
                        invoke(READER, "auth-installation", silent, "inherit", app,
                               str(recording_agent))
                        invoke(READER, "config-check", "de")
                        expect(a)
                elif scenario == "multiuser-auth-transaction":
                    for inherited, override in (("false", "inherit"), ("true", "inherit"),
                                                ("true", "false"), ("false", "true"),
                                                ("false", "inherit")):
                        invoke(READER, "auth-transaction", inherited, override, app,
                               str(recording_agent))
                        expect(a)
                elif scenario != "multiuser-install":
                    raise ValueError(f"unknown provisioned system case: {scenario}")
            if remote_snapshots() != controls:
                raise RuntimeError("named system operations changed default or per-user remotes")
            print(f"PASS {scenario}", flush=True)
        finally:
            shutil.rmtree(INSTALLATION)
            INSTALLATION.mkdir(mode=0o755)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("start", "probe", "stop", "case"))
    parser.add_argument("root", type=Path)
    parser.add_argument("--disposable-container", action="store_true")
    parser.add_argument("--client", type=Path)
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--scenario")
    parser.add_argument("--agent", type=Path)
    parser.add_argument("--client-preload")
    args = parser.parse_args()
    hosted = (os.environ.get("GITHUB_ACTIONS") == "true" and
              os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted")
    container = args.disposable_container and Path("/run/.containerenv").exists()
    if os.geteuid() != 0 or not (hosted or container):
        parser.error("requires root in a disposable GitHub-hosted VM or opted-in Podman container")
    root = args.root.resolve()
    if not (root / "logs").is_dir():
        parser.error("root must contain the initialized CI logs directory")
    if args.phase == "case":
        if any(value is None for value in (args.client, args.fixtures, args.scenario, args.agent)):
            parser.error("case requires --client, --fixtures, --scenario and --agent")
        run_case(root, args.client.resolve(), args.fixtures.resolve(), args.scenario, args.agent,
                 args.client_preload)
    else:
        {"start": start, "probe": probe, "stop": stop}[args.phase](root)


if __name__ == "__main__":
    main()
