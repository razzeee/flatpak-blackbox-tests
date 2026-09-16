# SPDX-License-Identifier: LGPL-2.1-or-later
"""Direct-root installation selectors in disposable user/mount namespaces.

Every target invocation, including setup and public verification queries, enters
bubblewrap. Persistent state is bound only from this case's fresh directory.
BLACKBOX_SYSTEM_INSTALL_DIR and BLACKBOX_SYSTEM_CONFIG_DIR describe the target's
compiled defaults. They are test expectations, never Flatpak path redirects.
This does not exercise polkit, the non-root helper, or multiple users.
"""

from __future__ import annotations

import configparser
import json
import os
import resource
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING:
    from fixture_manifest import FixtureManifest
    from run import Driver, RepositoryServer


DEFAULT_SYSTEM = "/var/local/lib/flatpak"
NAMED = "/var/lib/flatpak-selector-alt"
DEFAULT_CONFIG = "/usr/local/etc/flatpak"
USER = "/root/.local/share/flatpak"
SELECTORS = {"system": "--system", "alt": "--installation=alt", "user": "--user"}
PRIVATE_ROOTS = ("/etc", "/var", "/run", "/tmp", "/home", "/root")
FIXTURES = "/tmp/system-selector-fixtures"
HELPERS = ("FLATPAK_BWRAP", "FLATPAK_DBUSPROXY", "FLATPAK_TRIGGERSDIR",
           "FLATPAK_VALIDATE_ICON", "FLATPAK_PORTAL")


def _expectation(env: dict[str, str], key: str, default: str) -> str:
    value = env.get(key, default)
    path = Path(value)
    if (not path.is_absolute() or path == Path("/") or ".." in path.parts
            or any(character.isspace() for character in value)):
        raise ValueError(f"{key} must be an absolute path without '..' or whitespace")
    return str(path)


class _OverrideConfig(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


def _inspect_location(base: Path, location: Path, version: str) -> None:
    """Inspect public fixture payload, never infer a store's ref/commit layout."""
    assert location.is_absolute(), "deployment location must be absolute"
    directory = location.resolve(strict=True)
    installation = base.resolve(strict=True)
    assert directory.is_dir(), "deployment location is not a directory"
    assert directory != installation and directory.is_relative_to(installation), (
        "deployment location must identify content within the selected installation")
    # The controlled fixture exports bin/blackbox-probe. Accept its payload
    # root directly or one enclosing deployment directory, without naming that
    # wrapper. Do not recursively search installation roots or ref containers.
    candidates = [directory / "bin/blackbox-probe"]
    candidates.extend(directory.glob("*/bin/blackbox-probe"))
    probes = {path.resolve() for path in candidates if path.is_file()}
    assert len(probes) == 1, "location must contain exactly one fixture payload"
    probe = probes.pop()
    assert probe.is_relative_to(directory), "fixture probe escapes returned location"
    result = subprocess.run([str(probe)], capture_output=True, text=True,
                            timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == version, "returned location has wrong fixture version"
    print(json.dumps({"location": str(location), "probe": str(probe),
                      "version": result.stdout.strip()}))


def _bootstrap() -> None:
    """Runs inside bwrap before exec; fail closed if isolation is incomplete."""
    assert os.getuid() == os.getgid() == 0
    mapping = Path("/proc/self/uid_map").read_text().split()
    assert len(mapping) == 3 and mapping[0] == "0" and mapping[2] == "1"
    assert not any(key in os.environ for key in (
        "FLATPAK_SYSTEM_DIR", "FLATPAK_USER_DIR", "FLATPAK_CONFIG_DIR",
        "DBUS_SYSTEM_BUS_ADDRESS", "DBUS_SESSION_BUS_ADDRESS"))
    assert not Path("/run/dbus/system_bus_socket").exists()
    mounts = {line.split()[1]: line.split()[3].split(",")
              for line in Path("/proc/mounts").read_text().splitlines()}
    assert "ro" in mounts["/"]
    assert all("rw" in mounts[path] for path in ("/var", "/root", "/run", "/tmp", "/etc"))
    system = os.environ["BLACKBOX_SYSTEM_INSTALL_DIR"]
    config = os.environ["BLACKBOX_SYSTEM_CONFIG_DIR"]
    assert "rw" in mounts[system]
    assert "ro" in mounts[config] and "ro" in mounts[FIXTURES]
    if sys.argv[1] == "--outer":
        assert mapping[1] != "0"
        Path("/tmp/selector-outer-map.json").write_text(json.dumps(mapping))
        os.execv(sys.argv[2], sys.argv[2:])
    assert mapping[1] == "0"
    outer_mapping = json.loads(Path("/tmp/selector-outer-map.json").read_text())
    assert outer_mapping[0] == "0" and outer_mapping[1] != "0" and outer_mapping[2] == "1"
    # SYS_ADMIN is needed by Flatpak's root sandbox path. A second user
    # namespace locks inherited read-only flags, unlike a single-layer ro-bind.
    # Check that the target cannot remove the read-only host protection.
    import ctypes
    import errno
    libc = ctypes.CDLL(None, use_errno=True)
    mount = libc.mount
    mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
                      ctypes.c_ulong, ctypes.c_void_p]
    mount.restype = ctypes.c_int
    assert mount(None, b"/", None, 32 | 4096, None) == -1
    assert ctypes.get_errno() in (errno.EPERM, errno.EACCES)
    os.umask(0o022)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    with open("/dev/null", "rb") as stdin:
        os.dup2(stdin.fileno(), 0)
    Path("/etc/passwd").write_text(
        "root:x:0:0:root:/root:/bin/sh\nnobody:x:65534:65534:nobody:/:/sbin/nologin\n")
    Path("/etc/group").write_text("root:x:0:\nnobody:x:65534:\n")
    Path("/etc/machine-id").write_text("0123456789abcdef0123456789abcdef\n")
    Path("/run/user/0").mkdir(parents=True, mode=0o700)
    # The enumeration client first verifies this reachable control, then
    # obstructs the configured installation path itself, not backend contents.
    Path("/tmp/selector-unreachable").mkdir()
    if sys.argv[2] == "--probe":
        print(json.dumps({"uid": os.getuid(), "uid_map": mapping,
                          "outer_uid_map": outer_mapping, "host_remount_denied": True,
                          "system": system, "config": config, "named": NAMED, "user": USER,
                          "host_root_read_only": True, "host_bus": False}))
        return
    argv = sys.argv[2:]
    if argv[0] == "--inspect-location":
        assert len(argv) == 4
        _inspect_location(Path(argv[1]), Path(argv[2]), argv[3])
        return
    if argv[0] == "--session":
        # No host service activation directories, and the bus dies with this PID
        # namespace even if the parent times out.
        bus_config = Path("/tmp/selector-dbus.conf")
        bus_config.write_text('<busconfig><type>session</type><listen>unix:tmpdir=/tmp</listen>'
                              '<auth>EXTERNAL</auth><policy context="default">'
                              '<allow send_destination="*"/><allow receive_sender="*"/>'
                              '<allow own="*"/></policy></busconfig>')
        bus = subprocess.Popen(
            ["dbus-daemon", f"--config-file={bus_config}", "--nofork", "--print-address=1"],
            text=True, stdout=subprocess.PIPE)
        try:
            assert bus.stdout is not None
            address = bus.stdout.readline().strip()
            assert address.startswith("unix:")
            os.environ["DBUS_SESSION_BUS_ADDRESS"] = address
            raise SystemExit(subprocess.run(argv[1:], check=False).returncode)
        finally:
            bus.terminate()
            bus.wait(timeout=5)
    os.execv(argv[0], argv)


class Namespace:
    def __init__(self, driver: Driver, fixture_directory: Path,
                 *, unreachable: bool = False) -> None:
        self.driver = driver
        if os.getuid() == 0:
            self.block("root-userns scenarios must be launched by an ordinary host user")
        system = _expectation(driver.env, "BLACKBOX_SYSTEM_INSTALL_DIR", DEFAULT_SYSTEM)
        config = _expectation(driver.env, "BLACKBOX_SYSTEM_CONFIG_DIR", DEFAULT_CONFIG)
        self.paths = {"system": system, "alt": NAMED, "user": USER}
        self.app_versions: dict[str, str] = {}
        locations = [Path(system), Path(config), Path(NAMED), Path(USER)]
        for index, path in enumerate(locations):
            if any(other.is_relative_to(path) or path.is_relative_to(other)
                   for other in locations[index + 1:]):
                self.block("installation and configuration expectations must not overlap")
            if any(Path(root).is_relative_to(path) for root in PRIVATE_ROOTS):
                self.block("expectations must not cover namespace scaffolding directories")
        self.state = driver.root / "system-selector-state"
        self.state.mkdir(mode=0o700)
        for directory in ("var", "system", "home", "config", "inputs"):
            (self.state / directory).mkdir()
        installations = self.state / "config/installations.d"
        installations.mkdir()
        (installations / "selectors.conf").write_text(
            f'[Installation "alt"]\nPath={NAMED}\nDisplayName=Selector alternate\n'
            'Priority=25\nStorageType=network\n' +
            ('[Installation "unreachable"]\nPath=/tmp/selector-unreachable\n'
             if unreachable else ''))
        bwrap = shutil.which("bwrap", path=driver.env.get("PATH"))
        if bwrap is None:
            self.block("bubblewrap is unavailable")
        self.prefix = [bwrap, "--unshare-all", "--die-with-parent", "--new-session",
                       "--ro-bind", "/", "/"]
        private_parents = [Path(root) for root in PRIVATE_ROOTS]
        for location in (Path(system), Path(config)):
            if any(location.is_relative_to(root) for root in private_parents):
                continue
            parent = location.parent
            while not parent.is_dir():
                parent = parent.parent
            if parent in (Path("/"), Path("/usr")):
                self.block(f"no suitable private parent for expectation {location}")
            private_parents.append(parent)
        for parent in sorted(set(private_parents)):
            if not any(parent != other and parent.is_relative_to(other)
                       for other in private_parents):
                self.prefix += ["--tmpfs", str(parent)]
        # The suite can live directly in /tmp/blackbox or /opt/blackbox.
        # Ancestors of the suite are not part of the exposure contract.
        target_paths = [Path(__file__).resolve().parent, Path(driver.cli)]
        if driver.client is not None:
            target_paths.append(Path(driver.client))
        target_paths += [Path(driver.env[key]) for key in HELPERS if key in driver.env]
        target_paths += [Path(p) for p in driver.env.get("LD_LIBRARY_PATH", "").split(os.pathsep)
                         if p]
        target_paths += [Path(p) for p in driver.env.get(
            "BLACKBOX_TARGET_READONLY_PATHS", "").split(os.pathsep) if p]
        private_contents = [*locations, self.state, Path(FIXTURES),
                            Path("/tmp/selector-inputs"), Path("/tmp/selector-bootstrap.py"),
                            Path("/proc"), Path("/dev"), Path("/sys")]
        for path in sorted(set(target_paths), key=lambda item: (len(item.parts), str(item))):
            if not path.is_absolute() or ".." in path.parts or not path.exists():
                self.block(f"target path must be existing and absolute: {path}")
            # Validate the destination and resolved source, including symlinks.
            # A readonly bind must never replace a private root or expose host
            # contents over/beneath the case's installation and service paths.
            for candidate in {path, path.resolve()}:
                if any(root.is_relative_to(candidate) for root in private_parents):
                    self.block(f"readonly target path covers a private namespace root: {path}")
                if any(root.is_relative_to(candidate) or candidate.is_relative_to(root)
                       for root in private_contents):
                    self.block(f"readonly target path overlaps protected namespace content: {path}")
            self.prefix += ["--ro-bind", str(path), str(path)]
        self.prefix += ["--bind", str(self.state / "var"), "/var",
                        "--bind", str(self.state / "system"), system,
                        "--bind", str(self.state / "home"), "/root",
                        "--ro-bind", str(self.state / "config"), config,
                        "--ro-bind", str(self.state / "inputs"), "/tmp/selector-inputs",
                        "--ro-bind", str(fixture_directory.resolve()), FIXTURES,
                        "--ro-bind", str(Path(__file__).resolve()), "/tmp/selector-bootstrap.py",
                        "--proc", "/proc", "--dev", "/dev", "--uid", "0", "--gid", "0",
                        "--cap-add", "CAP_SETFCAP", "--clearenv"]
        env = {"PATH": "/usr/bin:/bin", "HOME": "/root", "USER": "root", "LOGNAME": "root",
               "XDG_RUNTIME_DIR": "/run/user/0", "LC_ALL": "C", "GIO_USE_VFS": "local",
               "TERM": "dumb", "TZ": "UTC", "BLACKBOX_SYSTEM_INSTALL_DIR": system,
               "BLACKBOX_SYSTEM_CONFIG_DIR": config}
        env.update({key: driver.env[key] for key in (*HELPERS, "LD_LIBRARY_PATH")
                    if key in driver.env})
        for key, value in env.items():
            self.prefix += ["--setenv", key, value]
        self.prefix += ["--chdir", "/tmp", "/usr/bin/python3", "-B",
                        "/tmp/selector-bootstrap.py", "--outer",
                        bwrap, "--unshare-all", "--die-with-parent", "--new-session",
                        "--bind", "/", "/",
                        "--proc", "/proc", "--dev", "/dev", "--uid", "0", "--gid", "0",
                        "--cap-add", "CAP_SYS_ADMIN", "--cap-add", "CAP_NET_ADMIN",
                        "--cap-add", "CAP_SETUID", "--cap-add", "CAP_SETGID",
                        "--cap-add", "CAP_SETFCAP",
                        "--chdir", "/tmp", "/usr/bin/python3", "-B",
                        "/tmp/selector-bootstrap.py", "--inside"]
        probe = driver.external_call([*self.prefix, "--probe"], "setup")
        if probe.returncode:
            self.block(f"root-userns isolation probe failed: {probe.stderr}")
        driver.check(json.loads(probe.stdout)["host_root_read_only"],
                     "read-only host mount required")

    def block(self, message: str) -> NoReturn:
        # run.py can be imported or executed as __main__. Use the driver's
        # exception class so the active main runner catches prerequisite blocks.
        runner = sys.modules[self.driver.check.__module__]
        raise runner.PrerequisiteError(message)

    def call(self, command: str, *args: str, scope: str | None = None,
             library: bool = False, session: bool = False) -> subprocess.CompletedProcess[str]:
        executable = str(self.driver.client) if library else self.driver.cli
        argv = [executable, command]
        if scope is not None:
            argv += [scope if library else SELECTORS[scope]]
        argv += list(args)
        result = self.driver.external_call(
            [*self.prefix, *(["--session"] if session else []), *argv],
            "library" if library else "cli")
        # Namespace root cannot set some security xattrs. This is an environment
        # prerequisite failure, never evidence that an install contract passed.
        diagnostic = result.stderr.lower()
        if result.returncode and any(fragment in diagnostic for fragment in (
            "setting security.selinux", "setting xattr", "setxattr", "lsetxattr"
        )) and ("operation not permitted" in diagnostic or "permission denied" in diagnostic):
            self.block(f"root-userns security xattr restriction: {result.stderr}")
        if result.returncode and any(fragment in result.stderr.lower() for fragment in (
            "disk quota exceeded", "no space left on device")):
            self.block(f"disposable installation storage exhausted: {result.stderr}")
        return result

    def ok(self, command: str, *args: str, scope: str | None = None,
           library: bool = False, session: bool = False) -> str:
        result = self.call(command, *args, scope=scope, library=library, session=session)
        self.driver.check(
            result.returncode == 0,
            f"isolated {command} {args} failed ({result.returncode}): {result.stderr}")
        return result.stdout.strip()

    def equal(self, actual: object, expected: object, context: str) -> None:
        self.driver.check(actual == expected, f"{context}: expected {expected!r}, got {actual!r}")

    def input(self, name: str, text: str) -> str:
        (self.state / "inputs" / name).write_text(text)
        return f"/tmp/selector-inputs/{name}"

    def remote(self, scope: str, version: str = "A", name: str = "fixture") -> None:
        self.ok("remote-add", "--no-gpg-verify", name, f"file://{FIXTURES}/{version}", scope=scope)

    def tip(self, scope: str, version: str) -> None:
        self.ok("remote-modify", f"--url=file://{FIXTURES}/{version}", "fixture", scope=scope)

    def installed(self, scope: str, ref: str, commit: str) -> None:
        self.equal(self.ok("info", "--show-ref", "--show-commit", ref, scope=scope).split(),
                   [ref, commit], f"{scope} installed identity")
        if not ref.startswith("app/"):
            return
        location = self.ok("info", "--show-location", ref, scope=scope)
        self.inspect_location(scope, location, self.app_versions[commit])

    def inspect_location(self, scope: str, location: str, version: str) -> None:
        inspected = self.driver.external_call(
            [*self.prefix, "--inspect-location", self.paths[scope], location, version], "setup")
        self.driver.check(inspected.returncode == 0,
                          f"invalid {scope} deployment location {location!r}: {inspected.stderr}")

    def refs(self, scope: str, *options: str) -> set[str]:
        return set(self.ok("list", "--columns=ref", *options, scope=scope).splitlines())


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    """Use local immutable fixtures; the HTTP server is outside the namespace."""
    directory = Path(fixture.get("directory", repository.fixtures))
    state = driver.root / "system-selector-state"
    driver.check(not state.exists() and not state.is_symlink(),
                 "system-selector state must be fresh")
    try:
        ns = Namespace(driver, directory,
                       unreachable=name == "system-selectors-library-enumeration")
        _run(ns, fixture, name)
    finally:
        # Every wrapper has exited before returning. Its PID namespace kills
        # descendants, and only this case's generated writable stores remain.
        # Keep the driver's command evidence, not accumulated installation data.
        if state.exists():
            shutil.rmtree(state)


def _run(ns: Namespace, fixture: FixtureManifest, name: str) -> None:
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    a, b = fixture["commits"]["A"], fixture["commits"]["B"]
    ns.app_versions = {a: "A", b: "B"}

    if name == "system-selectors-config":
        values = {"system": "de;fr", "alt": "ja;en", "user": "es;it"}
        defaults = {scope: ns.ok("config", "--get", "languages", scope=scope)
                    for scope in SELECTORS}
        for scope, value in values.items():
            ns.ok("config", "--set", "languages", value, scope=scope)
        for scope, value in values.items():
            ns.equal(ns.ok("config", "--get", "languages", scope=scope), value, scope)
        ns.ok("config", "--set", "languages", "pt")
        values["system"] = "pt"
        for scope, value in values.items():
            ns.equal(ns.ok("config", "--get", "languages", scope=scope), value, scope)
        for scope in SELECTORS:
            ns.ok("config", "--unset", "languages", scope=scope)
            values[scope] = defaults[scope]
            for other, value in values.items():
                ns.equal(ns.ok("config", "--get", "languages", scope=other), value,
                         "unset affects selected installation only")
        return

    if name == "system-selectors-remotes":
        for scope in SELECTORS:
            ns.remote(scope, "B" if scope == "alt" else "A", scope + "-only")
            ns.equal(ns.ok("remotes", "--columns=name", scope=scope), scope + "-only", scope)
        ns.equal(ns.ok("remotes", "--user", "--columns=name"), "user-only",
                 "system adds did not create user remotes")
        for scope in SELECTORS:
            ns.remote(scope)
        for scope in SELECTORS:
            ns.ok("remote-modify", f"--title={scope} edited", f"--prio={20 + len(scope)}",
                  f"--url=file://{FIXTURES}/B", "fixture", scope=scope)
            for other in SELECTORS:
                rows = ns.ok("remotes", "--columns=name,title,priority,url",
                             scope=other).splitlines()
                expected_row = (f"fixture\t{scope} edited\t{20 + len(scope)}\tfile://{FIXTURES}/B"
                                if other == scope else f"fixture\t-\t1\tfile://{FIXTURES}/A")
                ns.driver.check(expected_row in rows,
                                f"remote edit crossed installation boundary: {rows}")
            ns.ok("remote-delete", "fixture", scope=scope)
            ns.equal(ns.ok("remotes", "--show-disabled", "--columns=name", scope=scope),
                     scope + "-only", "delete selected remote")
            # Same-name competitors remain present for every selector's turn.
            for other in SELECTORS:
                names = ns.ok("remotes", "--columns=name", scope=other).splitlines()
                ns.driver.check(other + "-only" in names,
                                "remote mutation crossed installation boundary")
            for other in SELECTORS:
                if other == scope:
                    continue
                names = ns.ok("remotes", "--columns=name", scope=other).splitlines()
                ns.driver.check("fixture" in names,
                                "deleting selected fixture removed another installation's remote")
            ns.remote(scope)
        return

    if name == "system-selectors-remote-queries":
        for scope in SELECTORS:
            ns.remote(scope, "B" if scope == "alt" else "A")
        for scope in SELECTORS:
            ns.equal(ns.ok("remote-info", "--show-ref", "--show-commit", "fixture", app,
                           scope=scope).split(),
                     [app, b if scope == "alt" else a], "selected remote commit")
            ns.equal(ns.refs(scope), set(), "remote queries do not deploy refs")
        ns.tip("user", "B")
        ns.equal(ns.ok("remote-info", "--show-commit", "fixture", app, scope="user"), b,
                 "user remote B differs from default remote A")
        ns.equal(ns.ok("remote-info", "--show-commit", "fixture", app, scope="system"), a,
                 "default remote remains A after user changes to B")
        allowed = {"system": {app, runtime}, "alt": {runtime}, "user": {app}}
        for scope in ("alt", "user"):
            path = ns.input(scope + ".filter",
                            "deny *\n" + "".join(f"allow {ref}\n" for ref in allowed[scope]))
            ns.ok("remote-modify", f"--filter={path}", "fixture", scope=scope)
        for scope, expected in allowed.items():
            ns.equal(set(ns.ok("remote-ls", "--columns=ref", "fixture", scope=scope).splitlines()),
                     expected, "remote-ls selects independently filtered installation")
        ns.ok("remote-modify", "--no-filter", "fixture", scope="alt")
        ns.equal(set(ns.ok("remote-ls", "--columns=ref", "fixture", scope="alt").splitlines()),
                 {app, runtime}, "clear selected filter")
        ns.equal(set(ns.ok("remote-ls", "--columns=ref", "fixture", scope="user").splitlines()),
                 {app}, "other filter unchanged")
        return

    if name in ("system-selectors-overrides", "system-selectors-override-named"):
        scopes = SELECTORS if name.endswith("override-named") else ("system", "user")
        values = {}
        for scope in scopes:
            ns.ok("override", f"--env=SELECTOR={scope}", fixture["app"], scope=scope)
            values[scope] = scope
            for other in scopes:
                output = ns.ok("override", "--show", fixture["app"], scope=other)
                if other in values:
                    data = _OverrideConfig(interpolation=None)
                    data.read_string(output)
                    ns.equal(dict(data["Environment"]), {"SELECTOR": values[other]},
                             "selected override persists")
                else:
                    ns.equal(output, "", f"{other} override excludes other installation")
        for scope in scopes:
            ns.ok("override", "--reset", fixture["app"], scope=scope)
            ns.equal(ns.ok("override", "--show", fixture["app"], scope=scope), "",
                     "selected override reset")
            del values[scope]
            for other in values:
                output = ns.ok("override", "--show", fixture["app"], scope=other)
                ns.driver.check(f"SELECTOR={other}" in output,
                                "reset changed another installation")
        return

    if name == "system-selectors-patterns":
        for command, ref in (("mask", app), ("pin", runtime)):
            remaining = set()
            for scope in SELECTORS:
                ns.ok(command, ref, scope=scope)
                remaining.add(scope)
                for other in SELECTORS:
                    ns.equal(ns.ok(command, scope=other), ref if other in remaining else "",
                             "pattern storage is installation-scoped")
            for scope in SELECTORS:
                ns.ok(command, "--remove", ref, scope=scope)
                remaining.remove(scope)
                for other in SELECTORS:
                    ns.equal(ns.ok(command, scope=other), ref if other in remaining else "",
                             "pattern removal is installation-scoped")
        return

    if name.startswith("system-selectors-library-"):
        operation = name.removeprefix("system-selectors-library-")
        output = ns.ok("system-" + operation, app, runtime, a, b, fixture["runtime_commit"],
                       library=True)
        lines = output.splitlines()
        ns.driver.check(bool(lines) and lines[-1] == f"PASS system-{operation}",
                        "library client did not finish the selected assertion group")
        return

    # Install three independent copies. No selector is intentional for the
    # default-system contract; the named B copy distinguishes query selection.
    ns.remote("system")
    ns.ok("install", "--noninteractive", "fixture", app)
    ns.installed("system", app, a)
    ns.equal(ns.refs("alt"), set(), "implicit install excludes named installation")
    ns.equal(ns.refs("user"), set(), "implicit install excludes user installation")
    ns.remote("alt", "B")
    ns.remote("user")
    ns.ok("install", "--noninteractive", "fixture", app, scope="alt")
    ns.installed("alt", app, b)
    ns.installed("system", app, a)
    ns.equal(ns.refs("user"), set(), "named install excludes user installation")
    ns.ok("install", "--noninteractive", "fixture", app, scope="user")
    for scope in SELECTORS:
        ns.ok("install", "--noninteractive", "fixture", runtime, scope=scope)
        ns.installed(scope, app, b if scope == "alt" else a)

    if name == "system-selectors-lifecycle":
        ns.tip("system", "B")
        ns.ok("update", "--noninteractive", app, scope="system")
        ns.installed("system", app, b)
        ns.installed("user", app, a)
        ns.installed("alt", app, b)
        ns.ok("update", "--noninteractive", f"--commit={a}", app, scope="alt")
        ns.installed("alt", app, a)
        ns.installed("system", app, b)
        ns.installed("user", app, a)
        ns.tip("user", "B")
        ns.ok("update", "--noninteractive", app, scope="user")
        ns.installed("user", app, b)
        ns.installed("alt", app, a)
        ns.installed("system", app, b)
        installed_copies = {"system": b, "alt": a, "user": b}
        for scope in SELECTORS:
            ns.ok("uninstall", "--noninteractive", app, scope=scope)
            ns.equal(ns.refs(scope, "--app"), set(), "selected application removed")
            absent = ns.call("info", app, scope=scope)
            ns.driver.check(absent.returncode != 0 and "not installed" in absent.stderr,
                            "removed deployment remains queryable")
            ns.installed(scope, runtime, fixture["runtime_commit"])
            for other, commit in installed_copies.items():
                if other != scope:
                    ns.installed(other, app, commit)
            # Restore the selected copy so every following removal is tested
            # against both competing installations, including --user last.
            ns.ok("install", "--noninteractive", "fixture", app, scope=scope)
            ns.ok("update", "--noninteractive", f"--commit={installed_copies[scope]}", app,
                  scope=scope)
            ns.installed(scope, app, installed_copies[scope])
        return

    if name == "system-selectors-install-options":
        # A real --system install after removal must recreate only that copy.
        ns.ok("uninstall", "--noninteractive", app, scope="system")
        ns.ok("install", "--noninteractive", "fixture", app, scope="system")
        ns.installed("system", app, a)
        ns.installed("alt", app, b)
        ns.installed("user", app, a)
        ns.tip("system", "B")
        ns.ok("install", "--noninteractive", "--or-update", "fixture", app, scope="system")
        ns.installed("system", app, b)
        ns.installed("user", app, a)
        ns.ok("update", "--noninteractive", f"--commit={a}", app, scope="system")
        ns.ok("install", "--noninteractive", "--reinstall", "fixture", app, scope="system")
        ns.installed("system", app, b)
        ns.installed("user", app, a)
        return

    if name == "system-selectors-ambiguous":
        result = ns.call("uninstall", "--noninteractive", app)
        ns.driver.check(result.returncode != 0
                        and "multiple installed refs match" in result.stderr.lower()
                        and fixture["app"] in result.stderr,
                        f"unselected ambiguous uninstall must fail: {result.stderr}")
        for scope in SELECTORS:
            ns.installed(scope, app, b if scope == "alt" else a)
        return

    if name == "system-selectors-remote-force":
        for scope in SELECTORS:
            result = ns.call("remote-delete", "fixture", scope=scope)
            ns.driver.check(result.returncode != 0 and "installed" in result.stderr.lower()
                            and "fixture" in result.stderr,
                            "ordinary deletion must refuse an installed origin")
            ns.ok("remote-delete", "--force", "fixture", scope=scope)
            ns.equal(ns.ok("remotes", "--show-disabled", "--columns=name", scope=scope), "",
                     "forced remote deletion")
            ns.installed(scope, app, b if scope == "alt" else a)
        return

    if name == "system-selectors-disabled":
        for scope in ("system", "user"):
            ns.tip(scope, "B")
        ns.ok("remote-modify", "--disable", "fixture", scope="system")
        ns.equal(ns.ok("remotes", "--columns=name", scope="system"), "",
                 "disabled default is omitted")
        ns.equal(ns.ok("remotes", "--show-disabled", "--columns=name", scope="system"),
                 "fixture", "disabled default is explicitly visible")
        ns.equal(ns.ok("remotes", "--columns=name", scope="user"), "fixture",
                 "user remote stays enabled")
        ns.ok("update", "--noninteractive", scope="system")
        ns.installed("system", app, a)
        ns.ok("update", "--noninteractive", scope="user")
        ns.installed("user", app, b)
        ns.ok("remote-modify", "--enable", "fixture", scope="system")
        ns.ok("update", "--noninteractive", scope="system")
        ns.installed("system", app, b)
        return

    if name == "system-selectors-queries":
        for scope in SELECTORS:
            short_app, short_runtime = app.removeprefix("app/"), runtime.removeprefix("runtime/")
            ns.equal(ns.refs(scope, "--app"), {short_app}, "app filter")
            ns.equal(ns.refs(scope, "--runtime"), {short_runtime}, "runtime filter")
            ns.equal(ns.refs(scope, f"--arch={fixture['arch']}"), {short_app, short_runtime},
                     "matching architecture")
            ns.equal(ns.refs(scope, "--arch=nonexistent"), set(), "unmatched architecture")
            ns.equal(ns.ok("info", "--show-origin", app, scope=scope), "fixture", "origin")
            ns.equal(ns.ok("info", "--show-runtime", app, scope=scope), short_runtime, "runtime")
            ns.equal(ns.ok("info", "--show-sdk", app, scope=scope), short_runtime, "sdk")
            metadata = configparser.ConfigParser(interpolation=None)
            metadata.read_string(ns.ok("info", "--show-metadata", app, scope=scope))
            ns.equal(dict(metadata["Application"]), {
                     "name": fixture["app"], "runtime": short_runtime,
                     "sdk": short_runtime, "command": "blackbox-probe"}, "metadata")
        ns.ok("uninstall", "--noninteractive", "--all", scope="system")
        ns.equal(ns.refs("system"), set(), "system list excludes user-only refs")
        ns.installed("user", app, a)
        ns.installed("alt", app, b)
        ns.ok("uninstall", "--noninteractive", app, scope="alt")
        ns.equal(ns.refs("alt"), {runtime.removeprefix("runtime/")},
                 "named list differs from default and user")
        ns.equal(ns.refs("user"), {app.removeprefix("app/"), runtime.removeprefix("runtime/")},
                 "user list differs from both system installations")
        ns.equal(ns.refs("system"), set(), "default remains empty")
        return

    if name == "system-selectors-run":
        ns.equal(ns.ok("run", app, scope="alt", session=True), "B",
                 "named B executes while default/user are A")
        ns.tip("system", "B")
        ns.ok("update", "--noninteractive", app, scope="system")
        ns.installed("system", app, b)
        ns.installed("user", app, a)
        ns.equal(ns.ok("run", app, scope="system", session=True), "B",
                 "default B executes while user remains A")
        ns.equal(ns.ok("run", app, scope="user", session=True), "A",
                 "user A executes while both systems are B")
        return
    raise ValueError(f"unknown system selector scenario: {name}")


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("--inside", "--outer"):
        raise SystemExit("internal bubblewrap bootstrap only")
    _bootstrap()
