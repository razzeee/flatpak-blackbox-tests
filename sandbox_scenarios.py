# SPDX-License-Identifier: LGPL-2.1-or-later
"""Sandbox contracts observed through CLI output and controlled host resources."""

from __future__ import annotations

import configparser
import io
import os
import selectors
import shutil
import socket
import struct
import subprocess
import sysconfig
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from report_schema import EvidenceRecord

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


@contextmanager
def _background(driver: Driver, *args: str,
                pass_fds: tuple[int, ...] = ()) -> Iterator[subprocess.Popen[str]]:
    from run import terminate

    record: EvidenceRecord = {"argv": [driver.cli, *args], "interface": "cli"}
    driver.evidence.append(record)
    process = subprocess.Popen(record["argv"], env=driver.env, cwd=driver.root,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True, pass_fds=pass_fds)
    try:
        yield process
    finally:
        terminate(process)
        stdout, stderr = process.communicate()
        record.update({"stdout": record.get("stdout", "") + stdout, "stderr": stderr,
                       "exit_status": process.wait()})


@contextmanager
def _external_service(driver: Driver, *argv: str) -> Iterator[subprocess.Popen[str]]:
    from run import PrerequisiteError, terminate

    if not Path(argv[0]).is_file():
        raise PrerequisiteError(f"private service executable missing: {argv[0]}")
    record: EvidenceRecord = {"argv": list(argv)}
    driver.evidence.append(record)
    process = subprocess.Popen(argv, env=driver.env, cwd=driver.root,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        yield process
    finally:
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            terminate(process)
            stdout, stderr = process.communicate()
        record.update({"stdout": stdout, "stderr": stderr, "exit_status": process.wait()})


def _equal(driver: Driver, actual: object, expected: object, reason: str) -> None:
    driver.check(actual == expected, f"{reason}: expected {expected!r}, got {actual!r}")


def _probe(driver: Driver, app: str, *args: str, options: tuple[str, ...] = ()) -> str:
    return driver.cli_success("run", "--user", *options, app, *args)


def _denied(driver: Driver, app: str, *args: str, options: tuple[str, ...] = ()) -> None:
    result = driver.cli_call("run", "--user", *options, app, *args)
    driver.check(result.returncode == 1, f"probe must fail, got {result!r}")
    # Reject a launcher failure as evidence of sandbox denial.
    driver.check(result.stderr.startswith(f"{args[0]}:"),
                 f"failure must come from probe {args[0]}, got {result.stderr!r}")


def _absent_env(driver: Driver, app: str, name: str, *options: str) -> None:
    result = driver.cli_call("run", "--user", *options, app, "env", name)
    driver.check(result.returncode == 1 and not result.stdout and not result.stderr,
                 f"environment variable {name} should be absent: {result!r}")


class _CaseConfig(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


def _config(text: str) -> configparser.ConfigParser:
    parser = _CaseConfig(interpolation=None)
    parser.read_string(text)
    return parser


def _set(config: configparser.ConfigParser, group: str, key: str) -> set[str]:
    return set(filter(None, config.get(group, key, fallback="").split(";")))


def _override(driver: Driver, app: str, *options: str) -> None:
    driver.cli_success("override", "--user", *options, app)


def _environment(driver: Driver, app: str, name: str) -> None:
    if name == "sandbox-environment":
        _equal(driver, _probe(driver, app, "env", "BLACKBOX_META"), "metadata", "metadata env")
        _equal(driver, _probe(driver, app, "env", "BLACKBOX_META",
                             options=("--env=BLACKBOX_META=run=value with spaces",)),
               "run=value with spaces", "run overrides metadata")
        _absent_env(driver, app, "BLACKBOX_META", "--unset-env=BLACKBOX_META")
    elif name == "sandbox-clear-env":
        driver.env["BLACKBOX_HOST"] = "inherited"
        _equal(driver, _probe(driver, app, "env", "BLACKBOX_HOST"), "inherited", "control")
        _absent_env(driver, app, "BLACKBOX_HOST", "--clear-env")
        _equal(driver, _probe(driver, app, "env", "BLACKBOX_EXPLICIT",
                             options=("--clear-env", "--env=BLACKBOX_EXPLICIT=explicit")),
               "explicit", "explicit env survives clear")
    elif name == "sandbox-override-env":
        _override(driver, app, "--env=BLACKBOX_META=override=value")
        config = _config(driver.cli_success("override", "--user", "--show", app))
        _equal(driver, config["Environment"]["BLACKBOX_META"], "override=value", "stored env")
        for _ in range(2):
            _equal(driver, _probe(driver, app, "env", "BLACKBOX_META"), "override=value",
                   "override survives separate launches")
        _equal(driver, _probe(driver, app, "env", "BLACKBOX_META",
                             options=("--env=BLACKBOX_META=command-line",)),
               "command-line", "run takes precedence")
        _override(driver, app, "--unset-env=BLACKBOX_META")
        _absent_env(driver, app, "BLACKBOX_META")
        _override(driver, app, "--reset")
        _equal(driver, driver.cli_success("override", "--user", "--show", app), "", "reset")
        _equal(driver, _probe(driver, app, "env", "BLACKBOX_META"), "metadata", "restored env")
    elif name == "sandbox-global-override":
        driver.cli_success("override", "--user", "--env=BLACKBOX_META=global")
        _equal(driver, _probe(driver, app, "env", "BLACKBOX_META"), "global", "global override")
        _override(driver, app, "--env=BLACKBOX_META=app")
        _equal(driver, _probe(driver, app, "env", "BLACKBOX_META"), "app", "app precedence")
        _override(driver, app, "--reset")
        _equal(driver, _probe(driver, app, "env", "BLACKBOX_META"), "global", "global survives")
        driver.cli_success("override", "--user", "--reset")
        _equal(driver, _probe(driver, app, "env", "BLACKBOX_META"), "metadata", "global reset")


def _filesystem(driver: Driver, app: str, name: str, fixture: FixtureManifest) -> None:
    directory = driver.root / "host-files"
    directory.mkdir()
    marker = directory / "marker"
    marker.write_text("host-original")
    path = str(marker)
    grant = f"--filesystem={directory}"
    if name == "sandbox-filesystem":
        _denied(driver, app, "read", path)
        _equal(driver, _probe(driver, app, "read", path, options=(grant + ":ro",)),
               "host-original", "read-only grant")
        _denied(driver, app, "write", path, "forbidden", options=(grant + ":ro",))
        _equal(driver, marker.read_text(), "host-original", "host bytes unchanged")
        _probe(driver, app, "write", path, "host-replaced", options=(grant + ":rw",))
        _equal(driver, marker.read_text(), "host-replaced", "read-write host effect")
        _denied(driver, app, "read", path)
    elif name == "sandbox-filesystem-create":
        created = directory / "created"
        _probe(driver, app, "write", str(created / "new"), "created",
               options=(f"--filesystem={created}:create",))
        _equal(driver, (created / "new").read_text(), "created", "create host directory")
    elif name == "sandbox-filesystem-reset":
        metadata_directory = driver.root / "metadata-files"
        metadata_directory.mkdir()
        metadata_marker = metadata_directory / "marker"
        metadata_marker.write_text("metadata-original")
        metadata_path = str(metadata_marker)
        _denied(driver, app, "read", metadata_path)
        _denied(driver, app, "read", path)
        _metadata_variant(driver, fixture,
                          {"Context": {"filesystems": f"{metadata_directory}:ro;"}})
        _equal(driver, _probe(driver, app, "read", metadata_path),
               "metadata-original", "metadata-only grant control")
        _denied(driver, app, "read", path)
        _override(driver, app, grant)
        granted_paths = ((metadata_path, "metadata-original"), (path, "host-original"))
        for granted_path, content in granted_paths:
            _equal(driver, _probe(driver, app, "read", granted_path), content, "grant control")
            _denied(driver, app, "read", granted_path, options=("--nofilesystem=host:reset",))
            _equal(driver, _probe(driver, app, "read", granted_path), content, "reset is per-run")
        _override(driver, app, f"--nofilesystem={directory}")
        _denied(driver, app, "read", path)
        _override(driver, app, grant + ":ro")
        _equal(driver, _probe(driver, app, "read", path), "host-original", "stored ro")
        _denied(driver, app, "write", path, "forbidden")
        _override(driver, app, grant + ":rw")
        _probe(driver, app, "write", path, "override-write")
        _equal(driver, marker.read_text(), "override-write", "stored rw effect")
        _override(driver, app, "--reset")
        _denied(driver, app, "read", path)
    elif name == "sandbox-cwd":
        _equal(driver, _probe(driver, app, "read", "marker",
                             options=(grant + ":ro", f"--cwd={directory}")),
               "host-original", "relative read uses requested cwd")
    elif name == "sandbox-persist":
        home = driver.env["HOME"]
        persistent = f"{home}/blackbox-persist/marker"
        _probe(driver, app, "write", persistent, "persisted",
               options=("--persist=blackbox-persist",))
        _equal(driver, _probe(driver, app, "read", persistent,
                             options=("--persist=blackbox-persist",)), "persisted", "persist run")
        driver.check(not (Path(home) / "blackbox-persist/marker").exists(),
                     "persist must not write directly into host home")
        _override(driver, app, "--persist=blackbox-persist")
        _equal(driver, _probe(driver, app, "read", persistent), "persisted", "persist override")
        _probe(driver, app, "write", persistent, "stored")
        _equal(driver, _probe(driver, app, "read", persistent), "stored", "stored persistence")


def _network(driver: Driver, app: str, name: str) -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(16)
        port = str(server.getsockname()[1])

        def connects(*options: str) -> None:
            _equal(driver, _probe(driver, app, "tcp-connect", "127.0.0.1", port,
                                 options=options), "connected", "host loopback connection")
            server.settimeout(2)
            accepted, _ = server.accept()
            accepted.close()

        if name == "sandbox-network":
            _denied(driver, app, "tcp-connect", "127.0.0.1", port)
            connects("--share=network")
            _override(driver, app, "--share=network")
            connects()
            _denied(driver, app, "tcp-connect", "127.0.0.1", port,
                    options=("--unshare=network",))
            _override(driver, app, "--unshare=network")
            _denied(driver, app, "tcp-connect", "127.0.0.1", port)
        else:
            connects("--share-if=network:true")
            _denied(driver, app, "tcp-connect", "127.0.0.1", port,
                    options=("--share-if=network:false",))


@contextmanager
def _dummy_socket(endpoint: Path, wayland: bool) -> Iterator[None]:
    """Answer Wayland display sync with an empty registry, without a compositor."""
    stopped = threading.Event()
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(endpoint))
        server.listen(16)
        server.settimeout(0.1)

        def serve() -> None:
            while not stopped.is_set():
                try:
                    connection, _ = server.accept()
                except TimeoutError:
                    continue
                with connection:
                    connection.settimeout(0.1)
                    buffer = b""
                    while not stopped.is_set():
                        try:
                            received = connection.recv(4096)
                        except TimeoutError:
                            continue
                        except ConnectionError:
                            break
                        if not received:
                            break
                        buffer += received
                        while len(buffer) >= 8:
                            object_id, header = struct.unpack("=II", buffer[:8])
                            size, opcode = header >> 16, header & 0xffff
                            if size < 8 or size > 4096:
                                return
                            if len(buffer) < size:
                                break
                            message, buffer = buffer[:size], buffer[size:]
                            if object_id == 1 and opcode == 0 and size == 12:
                                callback, = struct.unpack("=I", message[8:])
                                # wl_callback.done, followed by wl_display.delete_id.
                                reply = (struct.pack("=III", callback, 12 << 16, 0) +
                                         struct.pack("=III", 1, (12 << 16) | 1, callback))
                                try:
                                    connection.sendall(reply)
                                except ConnectionError:
                                    break

        thread = threading.Thread(target=serve, daemon=True) if wayland else None
        if thread:
            thread.start()
        try:
            yield
        finally:
            stopped.set()
            if thread:
                thread.join(timeout=2)


def _sockets(driver: Driver, app: str, name: str) -> None:
    wayland = name != "sandbox-ssh"
    permission = "wayland" if wayland else "ssh-auth"
    endpoint = Path(driver.env["XDG_RUNTIME_DIR"]) / ("wayland-99" if wayland else "blackbox-ssh")
    variable = "WAYLAND_DISPLAY" if wayland else "SSH_AUTH_SOCK"
    driver.env[variable] = endpoint.name if wayland else str(endpoint)
    sandbox_path = "/run/flatpak/ssh-auth"
    with _dummy_socket(endpoint, wayland):
        if wayland:
            display = _probe(driver, app, "env", "WAYLAND_DISPLAY",
                             options=("--socket=wayland",))
            runtime = _probe(driver, app, "env", "XDG_RUNTIME_DIR")
            sandbox_path = str(Path(runtime) / display)
        if name == "sandbox-conditional-socket":
            _equal(driver, _probe(driver, app, "exists", sandbox_path,
                                 options=("--socket-if=wayland:true",)), "exists", "true socket")
            _denied(driver, app, "exists", sandbox_path, options=("--socket-if=wayland:false",))
        else:
            _denied(driver, app, "exists", sandbox_path)
            _equal(driver, _probe(driver, app, "exists", sandbox_path,
                                 options=(f"--socket={permission}",)), "exists", "socket grant")
            _override(driver, app, f"--socket={permission}")
            _equal(driver, _probe(driver, app, "exists", sandbox_path), "exists", "stored socket")
            _denied(driver, app, "exists", sandbox_path, options=(f"--nosocket={permission}",))
            _override(driver, app, f"--nosocket={permission}")
            _denied(driver, app, "exists", sandbox_path)


def _policy(driver: Driver, app: str, name: str) -> None:
    options = ("--own-name=org.blackbox.Own", "--talk-name=org.blackbox.Talk",
               "--system-own-name=org.blackbox.SystemOwn",
               "--system-talk-name=org.blackbox.SystemTalk")
    if name == "sandbox-override-policy":
        _override(driver, app, *options)
        config = _config(driver.cli_success("override", "--user", "--show", app))
    else:
        config = _config(_probe(driver, app, "read", "/.flatpak-info", options=options))
    _equal(driver, config["Session Bus Policy"]["org.blackbox.Own"], "own", "session own policy")
    _equal(driver, config["Session Bus Policy"]["org.blackbox.Talk"], "talk", "session talk policy")
    _equal(driver, config["System Bus Policy"]["org.blackbox.SystemOwn"], "own", "system own")
    _equal(driver, config["System Bus Policy"]["org.blackbox.SystemTalk"], "talk", "system talk")
    if name == "sandbox-override-policy":
        _override(driver, app, "--no-talk-name=org.blackbox.Talk",
                  "--system-no-talk-name=org.blackbox.SystemTalk")
        config = _config(driver.cli_success("override", "--user", "--show", app))
        _equal(driver, config["Session Bus Policy"]["org.blackbox.Talk"], "none", "session deny")
        _equal(driver, config["System Bus Policy"]["org.blackbox.SystemTalk"],
               "none", "system deny")


def _context(driver: Driver, app: str, name: str) -> None:
    options = ("--share=ipc", "--unshare=network", "--device=dri", "--nodevice=kvm",
               "--allow=devel", "--disallow=multiarch")
    if name == "sandbox-override-context":
        _override(driver, app, *options)
        config = _config(driver.cli_success("override", "--user", "--show", app))
        _equal(driver, _set(config, "Context", "shared"), {"ipc", "!network"}, "stored sharing")
        _equal(driver, _set(config, "Context", "devices"), {"dri", "!kvm"}, "stored devices")
        _equal(driver, _set(config, "Context", "features"),
               {"devel", "!multiarch"}, "stored features")
    else:
        _override(driver, app, "--device=kvm", "--allow=multiarch", "--share=network")
        control = _config(_probe(driver, app, "read", "/.flatpak-info"))
        _equal(driver, _set(control, "Context", "devices"), {"kvm"}, "device control")
        _equal(driver, _set(control, "Context", "features"), {"multiarch"}, "feature control")
        _equal(driver, _set(control, "Context", "shared"), {"network"}, "sharing control")
        config = _config(_probe(driver, app, "read", "/.flatpak-info", options=options))
        _equal(driver, _set(config, "Context", "shared"), {"ipc"}, "effective sharing")
        _equal(driver, _set(config, "Context", "devices"), {"dri"}, "effective devices")
        _equal(driver, _set(config, "Context", "features"), {"devel"}, "effective features")


def _extra_context(driver: Driver, app: str, name: str) -> None:
    stored = "override" in name
    query_file = driver.root / "usb-queries"
    query_file.write_text("# ignored comment\nvnd:1234\n!vnd:2345\n")
    options = ("--usb=vnd:0123+dev:4567", "--nousb=cls:03:*",
               "--usb-list=vnd:3456;!vnd:4567", f"--usb-list-file={query_file}",
               "--add-policy=blackbox.values=keep", "--add-policy=blackbox.values=new",
               "--remove-policy=blackbox.values=old", "--a11y-own-name=org.blackbox.Accessible")
    _override(driver, app, "--add-policy=blackbox.values=old")
    control = _config(driver.cli_success("override", "--user", "--show", app))
    _equal(driver, _set(control, "Policy blackbox", "values"), {"old"}, "policy control")
    if stored:
        _override(driver, app, *options)
        config = _config(driver.cli_success("override", "--user", "--show", app))
    else:
        config = _config(_probe(driver, app, "read", "/.flatpak-info", options=options))
    _equal(driver, _set(config, "USB Devices", "enumerable-devices"),
           {"vnd:0123+dev:4567", "vnd:3456", "vnd:1234"}, "USB allow queries")
    _equal(driver, _set(config, "USB Devices", "hidden-devices"),
           {"cls:03:*", "vnd:4567", "vnd:2345"}, "USB hide queries")
    _equal(driver, _set(config, "Policy blackbox", "values"),
           {"keep", "new", "!old"} if stored else {"keep", "new"}, "generic policy")
    _equal(driver, config["Accessibility Bus Policy"]["org.blackbox.Accessible"],
           "own", "accessibility name policy")


def _conditional_context(driver: Driver, app: str, name: str) -> None:
    if name == "sandbox-override-conditional":
        _override(driver, app, "--share-if=network:false", "--socket-if=wayland:true",
                  "--device-if=shm:true", "--allow-if=devel:false")
        config = _config(driver.cli_success("override", "--user", "--show", app))
        for key, value in (("shared", "network:false"), ("sockets", "wayland:true"),
                           ("devices", "shm:true"), ("features", "devel:false")):
            _equal(driver, _set(config, "Context", key),
                   {value.split(":")[0], f"if:{value}"}, f"stored conditional {key}")
    else:
        with tempfile.NamedTemporaryFile(prefix="blackbox-conditional-", dir="/dev/shm") as marker:
            marker.write(b"conditional-host-shm")
            marker.flush()
            _denied(driver, app, "read", marker.name)
            _equal(driver, _probe(driver, app, "read", marker.name,
                                 options=("--device-if=shm:true",)),
                   "conditional-host-shm", "true device condition exposes host shared memory")
            _denied(driver, app, "read", marker.name, options=("--device-if=shm:false",))
        for condition in ("true", "false"):
            options = (f"--device-if=shm:{condition}", f"--allow-if=devel:{condition}")
            config = _config(_probe(driver, app, "read", "/.flatpak-info", options=options))
            _equal(driver, _set(config, "Context", "devices"),
                   {"shm", f"if:shm:{condition}"}, "device conditional expression")
            _equal(driver, _set(config, "Context", "features"),
                   {"devel", f"if:devel:{condition}"}, "feature conditional expression")


def _process(driver: Driver, app: str, name: str) -> None:
    with _background(driver, "run", "--user", "--env=BLACKBOX_PROCESS=process-env",
                     app, "hold", "120") as process:
        assert process.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            driver.check(bool(selector.select(10)), "background probe must become ready")
            ready = process.stdout.readline()
        driver.evidence[-1]["stdout"] = ready
        _equal(driver, ready, "ready\n", "background app has executed probe")
        deadline = time.monotonic() + 10
        instance = ""
        while time.monotonic() < deadline:
            rows = driver.cli_success("ps", "--columns=instance,application,pid,child-pid")
            for line in rows.splitlines():
                fields = line.split("\t")
                if len(fields) == 4 and fields[1] == app:
                    instance, _, pid, child = fields
                    driver.check(pid.isdecimal() and child.isdecimal(), "ps has numeric PIDs")
                    driver.check(int(pid) > 0 and int(child) > 0, "ps has positive PIDs")
                    _equal(driver, int(pid), process.pid, "ps identifies background launch PID")
                    os.kill(int(pid), 0)
                    os.kill(int(child), 0)
                    break
            if instance:
                break
            driver.check(process.poll() is None, "background app exited before appearing in ps")
            time.sleep(0.05)
        driver.check(bool(instance), "running instance must appear in ps within ten seconds")
        if name == "sandbox-enter":
            _equal(driver, driver.cli_success("enter", instance, "/app/bin/blackbox-probe",
                                             "env", "BLACKBOX_PROCESS"),
                   "process-env", "enter inherits application environment")
            _equal(driver, driver.cli_success("enter", instance, "/app/bin/blackbox-probe",
                                             "args", "two words", "--literal"),
                   "two words\n--literal", "enter forwards arguments")
        driver.cli_success("kill", instance)
        deadline = time.monotonic() + 10
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        driver.check(process.poll() is not None, "kill must stop the selected instance")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            rows = driver.cli_success("ps", "--columns=instance,application")
            if instance not in {line.split("\t")[0] for line in rows.splitlines()}:
                return
            time.sleep(0.05)
        driver.check(False, "killed instance must disappear from ps")


def _shm(driver: Driver, app: str) -> None:
    with tempfile.NamedTemporaryFile(prefix="blackbox-shm-", dir="/dev/shm") as marker:
        marker.write(b"host-shared-memory")
        marker.flush()
        _denied(driver, app, "read", marker.name)
        _equal(driver, _probe(driver, app, "read", marker.name, options=("--device=shm",)),
               "host-shared-memory", "shared host /dev/shm")
        _override(driver, app, "--device=shm")
        _equal(driver, _probe(driver, app, "read", marker.name), "host-shared-memory", "stored shm")
        _denied(driver, app, "read", marker.name, options=("--nodevice=shm",))
        _override(driver, app, "--nodevice=shm")
        _denied(driver, app, "read", marker.name)


def _environment_descriptor(driver: Driver, app: str) -> None:
    from run import ContractFailure

    with tempfile.TemporaryFile(dir=driver.root) as data:
        fd = data.fileno()
        data.write(b"BLACKBOX_FD=fd=value with spaces\0")
        options = (f"--env-fd={fd}",)
        args = ("env", "BLACKBOX_FD")
        expected = "fd=value with spaces\n"
        data.flush()
        data.seek(0)
        with _background(driver, "run", "--user", *options, app, *args,
                         pass_fds=(fd,)) as process:
            try:
                stdout, stderr = process.communicate(timeout=driver.timeout)
            except subprocess.TimeoutExpired as error:
                raise ContractFailure("descriptor probe timed out") from error
            _equal(driver, process.returncode, 0, f"descriptor launch status, stderr={stderr!r}")
            _equal(driver, stdout, expected, "descriptor contents reach probe")


def _instance_descriptor(driver: Driver, app: str) -> None:
    with tempfile.TemporaryFile(dir=driver.root) as data:
        fd = data.fileno()
        with _background(driver, "run", "--user", f"--instance-id-fd={fd}", app, "hold", "120",
                         pass_fds=(fd,)) as process:
            assert process.stdout is not None
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                driver.check(bool(selector.select(10)), "instance probe must become ready")
                ready = process.stdout.readline()
            driver.evidence[-1]["stdout"] = ready
            _equal(driver, ready, "ready\n", "instance app has executed probe")
            data.seek(0)
            instance = data.read().decode().strip()
            driver.check(instance.isdecimal(), f"instance descriptor returned {instance!r}")
            rows = driver.cli_success("ps", "--columns=instance,application,pid")
            driver.check(f"{instance}\t{app}\t{process.pid}" in rows.splitlines(),
                         "descriptor instance ID must equal public ps ID for this launch")
            driver.cli_success("kill", instance)


def _make_current(driver: Driver, fixture: FixtureManifest, app: str) -> None:
    from run import execute

    # Construct independent branch inputs from immutable reference repositories.
    repo = driver.root / "branches-repo"
    shutil.copytree(Path(fixture["directory"]) / "B", repo)

    def ostree(*args: str) -> str:
        if args and args[0] == "checkout":
            args = ("checkout", "--force-copy", "--disable-cache", *args[1:])
        result = execute(["ostree", f"--repo={repo}", *args], driver.env, driver.root,
                         driver.evidence, driver.timeout)
        driver.check(result.returncode == 0, f"reference branch setup failed: {result.stderr}")
        return result.stdout.strip()

    arch = fixture["arch"]
    branches = ((fixture["branch"], "A"), ("blackbox-alternate", "B"))
    for branch, version in branches:
        tree = driver.root / f"branch-{version}"
        ostree("checkout", "--user-mode", fixture["commits"][version], str(tree))
        # OSTree checkout uses hardlinks; replace the export with a new file only.
        exports = tree / "export/share/applications"
        exports.mkdir(parents=True, exist_ok=True)
        desktop = exports / f"{app}.desktop"
        desktop.unlink(missing_ok=True)
        desktop.write_text(f"[Desktop Entry]\nType=Application\nName=Blackbox {version}\n"
                           f"Exec=flatpak run --branch={branch} {app}\n")
        ostree("commit", f"--branch=app/{app}/{arch}/{branch}", f"--tree=dir={tree}",
               f"--add-metadata-string=xa.metadata={(tree / 'metadata').read_text()}",
               "--subject=Independent branch export")
    ostree("summary", "--update")
    (repo / "summary.idx").unlink(missing_ok=True)
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "branches", str(repo))
    # Replace initial branch to get its independently prepared desktop export.
    driver.cli_success("install", "--user", "--noninteractive", "--reinstall", "branches",
                       f"app/{app}/{arch}/{fixture['branch']}")
    driver.cli_success("install", "--user", "--noninteractive", "branches",
                       f"app/{app}/{arch}/blackbox-alternate")
    exported = (Path(driver.env["XDG_DATA_HOME"]) /
                f"flatpak/exports/share/applications/{app}.desktop")
    for branch, version in reversed(branches):
        driver.cli_success("make-current", "--user", f"--arch={arch}", app, branch)
        _equal(driver, _probe(driver, app), version, "current branch selects runnable version")
        desktop_config = _config(exported.read_text())
        _equal(driver, desktop_config["Desktop Entry"]["Name"], f"Blackbox {version}",
               "current branch selects public desktop export")
        other_branch = next(candidate for candidate, _ in branches if candidate != branch)
        unavailable_arch = "aarch64" if arch != "aarch64" else "x86_64"
        before_export = exported.read_bytes()
        result = driver.cli_call("make-current", "--user", f"--arch={unavailable_arch}",
                                 app, other_branch)
        driver.check(result.returncode != 0 and unavailable_arch in result.stderr,
                     f"unavailable architecture must be refused: {result!r}")
        _equal(driver, _probe(driver, app), version,
               "failed architecture selection preserves branch")
        _equal(driver, exported.read_bytes(), before_export,
               "failed architecture selection preserves public export")


def _metadata_variant(driver: Driver, fixture: FixtureManifest,
                      values: dict[str, dict[str, str]]) -> None:
    from run import execute

    repo = driver.root / "metadata-repo"
    shutil.copytree(Path(fixture["directory"]) / "A", repo)
    tree = driver.root / "metadata-tree"

    def ostree(*args: str) -> None:
        if args and args[0] == "checkout":
            args = ("checkout", "--force-copy", "--disable-cache", *args[1:])
        result = execute(["ostree", f"--repo={repo}", *args], driver.env, driver.root,
                         driver.evidence, driver.timeout)
        driver.check(result.returncode == 0, f"reference metadata setup failed: {result.stderr}")

    ostree("checkout", "--user-mode", fixture["commits"]["A"], str(tree))
    metadata = tree / "metadata"
    config = _config(metadata.read_text())
    for group, entries in values.items():
        if not config.has_section(group):
            config.add_section(group)
        for key, value in entries.items():
            config[group][key] = value
    text = io.StringIO()
    config.write(text)
    metadata.unlink()
    metadata.write_text(text.getvalue())
    ref = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    ostree("commit", f"--branch={ref}", f"--tree=dir={tree}",
           f"--add-metadata-string=xa.metadata={text.getvalue()}", "--subject=Metadata input")
    ostree("summary", "--update")
    (repo / "summary.idx").unlink(missing_ok=True)
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "metadata", str(repo))
    driver.cli_success("install", "--user", "--noninteractive", "--reinstall", "metadata", ref)


def _mount_paths(driver: Driver, fixture: FixtureManifest, app: str) -> None:
    from run import execute

    repo = Path(fixture["directory"]) / "A"
    for mount, commit in (("app", fixture["commits"]["A"]), ("usr", fixture["runtime_commit"])):
        tree = driver.root / f"replacement-{mount}"
        result = execute(["ostree", f"--repo={repo}", "checkout", "--user-mode",
                          "--force-copy", "--disable-cache", commit, str(tree)],
                         driver.env, driver.root, driver.evidence, driver.timeout)
        driver.check(result.returncode == 0, f"reference replacement checkout: {result.stderr}")
        (tree / "files/blackbox-replacement").write_text(f"replacement-{mount}")
        options: tuple[str, ...] = (f"--{mount}-path={tree / 'files'}",)
        path = f"/{mount}/blackbox-replacement"
        _denied(driver, app, "read", path)
        _equal(driver, _probe(driver, app, "read", path, options=options),
               f"replacement-{mount}", "replacement mount supplies marker")
        _denied(driver, app, "read", f"/run/parent/{mount}/blackbox-replacement", options=options)
        executable = "blackbox-probe" if mount == "app" else "ldconfig"
        original = f"/run/parent/{mount}/bin/{executable}"
        _equal(driver, _probe(driver, app, "exists", original, options=options),
               "exists", "original contents redirected to parent mount")
    options = ("--app-path=", "--command=/run/parent/app/bin/blackbox-probe")
    _equal(driver, _probe(driver, app, options=options), "A", "original app remains runnable")
    _denied(driver, app, "exists", "/app/bin/blackbox-probe", options=options)


def _metadata_cases(driver: Driver, fixture: FixtureManifest, app: str, name: str) -> None:
    if name == "sandbox-metadata-network":
        _metadata_variant(driver, fixture, {"Context": {"shared": "network;"}})
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = str(server.getsockname()[1])
            _equal(driver, _probe(driver, app, "tcp-connect", "127.0.0.1", port),
                   "connected", "metadata network control")
            server.settimeout(2)
            accepted, _ = server.accept()
            accepted.close()
            _denied(driver, app, "tcp-connect", "127.0.0.1", port,
                    options=("--unshare=network",))
    elif name == "sandbox-devel":
        sdk = f"org.blackbox.MissingSDK/{fixture['arch']}/{fixture['branch']}"
        _metadata_variant(driver, fixture, {"Application": {"sdk": sdk}})
        _equal(driver, _probe(driver, app), "A", "normal mode uses runtime")
        result = driver.cli_call("run", "--user", "--devel", app)
        driver.check(result.returncode != 0 and "org.blackbox.MissingSDK" in result.stderr,
                     "devel selects unavailable SDK instead of available runtime")
    elif name == "sandbox-restrict":
        marker = driver.root / "restricted-marker"
        marker.write_text("host-granted")
        _override(driver, app, f"--filesystem={marker}:ro")
        _equal(driver, _probe(driver, app, "read", str(marker)), "host-granted", "control")
        _denied(driver, app, "read", str(marker), options=("--sandbox",))


def _bus(driver: Driver, app: str, name: str) -> None:
    from run import PrerequisiteError, execute, terminate

    for binary in ("/usr/bin/dbus-send", "/usr/bin/dbus-test-tool"):
        if not Path(binary).is_file():
            raise PrerequisiteError(f"bus probe needs host tool {binary}")
    # Host OS files supply an independent D-Bus client, including its libraries.
    # No host /run access is granted; the client still uses the sandbox bus proxy.
    library_dirs = [Path("/usr/lib64"), Path("/usr/lib")]
    multiarch = sysconfig.get_config_var("MULTIARCH")
    if isinstance(multiarch, str) and multiarch:
        directory = Path("/usr/lib") / multiarch
        if directory.is_dir():
            library_dirs.insert(0, directory)
    library_path = ":".join(f"/run/host{directory}" for directory in library_dirs)
    tool_options: tuple[str, ...] = (
        "--filesystem=host-os:ro",
        f"--env=LD_LIBRARY_PATH={library_path}",
        "--command=/run/host/usr/bin/dbus-send")
    destination = "org.blackbox.Echo"
    system = name in {"sandbox-system-bus", "sandbox-system-socket"}
    bus = "system" if system else "session"
    prefix = "system-" if system else ""
    if system:
        driver.env["DBUS_SYSTEM_BUS_ADDRESS"] = driver.env["DBUS_SESSION_BUS_ADDRESS"]
        tool_options += ("--unset-env=DBUS_SYSTEM_BUS_ADDRESS",)
    call = (f"--{bus}", "--print-reply", "--reply-timeout=2000",
            f"--dest={destination}", "/", "org.blackbox.Test.Ping")
    argv = ["/usr/bin/dbus-test-tool", "echo", f"--{bus}", f"--name={destination}"]
    record: EvidenceRecord = {"argv": argv}
    driver.evidence.append(record)
    service = subprocess.Popen(argv, env=driver.env, cwd=driver.root,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while True:
            result = execute(["/usr/bin/dbus-send", *call], driver.env, driver.root,
                             driver.evidence, driver.timeout)
            if result.returncode == 0:
                break
            driver.check(service.poll() is None and time.monotonic() < deadline,
                         f"private bus echo service failed to become ready: {result.stderr}")
            time.sleep(0.05)

        def denied(*options: str) -> None:
            result = driver.cli_call("run", "--user", *tool_options, *options, app, *call)
            driver.check(result.returncode != 0 and
                         ("ServiceUnknown" in result.stderr or "AccessDenied" in result.stderr or
                          (system and "Failed to open connection" in result.stderr)),
                         f"filtered bus must deny destination, got {result!r}")

        def allowed(*options: str) -> None:
            output = _probe(driver, app, *call, options=(*tool_options, *options))
            driver.check("method return" in output, "echo service must reply through bus")

        denied()
        if name in {"sandbox-bus", "sandbox-system-bus"}:
            allowed(f"--{prefix}talk-name={destination}")
            _override(driver, app, f"--{prefix}talk-name={destination}")
            allowed()
            denied(f"--{prefix}no-talk-name={destination}")
            _override(driver, app, f"--{prefix}no-talk-name={destination}")
            denied()
        elif name == "sandbox-session-switches":
            allowed("--sandbox", "--session-bus", f"--talk-name={destination}")
            result = driver.cli_call("run", "--user", *tool_options, "--no-session-bus",
                                     f"--talk-name={destination}", app, *call)
            driver.check(result.returncode != 0 and "Failed to open connection" in result.stderr,
                         f"no-session-bus must remove bus connection: {result!r}")
        else:
            allowed(f"--socket={bus}-bus")
            _override(driver, app, f"--socket={bus}-bus")
            allowed()
            denied(f"--nosocket={bus}-bus")
            _override(driver, app, f"--nosocket={bus}-bus")
            denied()
    finally:
        terminate(service)
        stdout, stderr = service.communicate()
        record.update({"stdout": stdout, "stderr": stderr, "exit_status": service.wait()})


def _file_forwarding(driver: Driver, app: str) -> None:
    from run import PrerequisiteError, execute

    if not os.access("/dev/fuse", os.R_OK | os.W_OK):
        raise PrerequisiteError("private document portal needs accessible /dev/fuse")
    mount = Path(driver.env["XDG_RUNTIME_DIR"]) / "doc"
    marker = driver.root / "forwarded-marker"
    marker.write_text("host-document")

    def portal_call(method: str, *args: str) -> subprocess.CompletedProcess[str]:
        return execute(["gdbus", "call", "--session", "--dest", "org.freedesktop.portal.Documents",
                        "--object-path", "/org/freedesktop/portal/documents", "--method",
                        f"org.freedesktop.portal.Documents.{method}", *args],
                       driver.env, driver.root, driver.evidence, driver.timeout)

    document_id = ""
    with _external_service(driver, "/usr/libexec/xdg-permission-store"):
        for iteration in range(2):
            try:
                with _external_service(driver, "/usr/libexec/xdg-document-portal") as portal:
                    deadline = time.monotonic() + 10
                    while True:
                        result = portal_call("GetMountPoint")
                        if result.returncode == 0:
                            break
                        if portal.poll() is not None or time.monotonic() >= deadline:
                            raise PrerequisiteError("private document portal failed to start")
                        time.sleep(0.05)
                    driver.check(str(mount) in result.stdout,
                                 "private portal must mount in isolated runtime directory")
                    if iteration == 0:
                        forwarded = _probe(driver, app, "args", "@@", str(marker), "@@",
                                           options=("--file-forwarding",))
                        driver.check(forwarded != str(marker) and
                                     forwarded.endswith("/" + marker.name),
                                     f"file argument must become document path: {forwarded!r}")
                        document_id = Path(forwarded).parent.name
                        _equal(driver, _probe(driver, app, "read", "@@", str(marker), "@@",
                                             options=("--file-forwarding",)),
                               "host-document", "forwarded document is readable")
                        _probe(driver, app, "write", "@@", str(marker), "@@", "document-written",
                               options=("--file-forwarding",))
                        _equal(driver, marker.read_text(), "document-written",
                               "forwarded document is writable")
                        listed = portal_call("List", app)
                        driver.check(listed.returncode == 0 and document_id in listed.stdout,
                                     "public document listing identifies forwarded grant")
                    else:
                        listed = portal_call("List", app)
                        driver.check(listed.returncode == 0 and document_id not in listed.stdout,
                                     "forwarded document export must not survive portal restart")
            finally:
                # The mountpoint was obtained from the public portal API. Unmount
                # after graceful shutdown as well, to cover daemon startup failure.
                execute(["fusermount3", "-u", str(mount)], driver.env, driver.root,
                        driver.evidence, driver.timeout)


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    """Run one isolated contract; the runner owns environment and repository cleanup."""
    app = str(fixture["app"])
    repository.version = "A"
    driver.success("remote", url)
    driver.success("install", f"app/{app}/{fixture['arch']}/{fixture['branch']}")
    if name in {"sandbox-environment", "sandbox-clear-env", "sandbox-override-env",
                "sandbox-global-override"}:
        if name != "sandbox-clear-env":
            _metadata_variant(driver, fixture, {"Environment": {"BLACKBOX_META": "metadata"}})
        _environment(driver, app, name)
    elif name in {"sandbox-filesystem", "sandbox-filesystem-create", "sandbox-filesystem-reset",
                  "sandbox-cwd", "sandbox-persist"}:
        _filesystem(driver, app, name, fixture)
    elif name in {"sandbox-network", "sandbox-conditional-network"}:
        _network(driver, app, name)
    elif name in {"sandbox-wayland", "sandbox-ssh", "sandbox-conditional-socket"}:
        _sockets(driver, app, name)
    elif name in {"sandbox-override-policy", "sandbox-run-policy"}:
        _policy(driver, app, name)
    elif name in {"sandbox-override-context", "sandbox-run-context"}:
        _context(driver, app, name)
    elif name in {"sandbox-override-extra", "sandbox-run-extra"}:
        _extra_context(driver, app, name)
    elif name in {"sandbox-override-conditional", "sandbox-run-conditional"}:
        _conditional_context(driver, app, name)
    elif name in {"sandbox-process", "sandbox-enter"}:
        _process(driver, app, name)
    elif name == "sandbox-shm":
        _shm(driver, app)
    elif name == "sandbox-env-fd":
        _environment_descriptor(driver, app)
    elif name == "sandbox-instance-fd":
        _instance_descriptor(driver, app)
    elif name == "sandbox-make-current":
        _make_current(driver, fixture, app)
    elif name == "sandbox-mount-paths":
        _mount_paths(driver, fixture, app)
    elif name in {"sandbox-metadata-network", "sandbox-devel", "sandbox-restrict"}:
        _metadata_cases(driver, fixture, app, name)
    elif name in {"sandbox-bus", "sandbox-session-bus", "sandbox-system-bus",
                  "sandbox-system-socket", "sandbox-session-switches"}:
        _bus(driver, app, name)
    elif name == "sandbox-file-forwarding":
        _file_forwarding(driver, app)
    elif name == "sandbox-command":
        _equal(driver, _probe(driver, app), "A", "metadata command")
        _equal(driver, _probe(driver, app, "args", "two words", "--literal", "", "last"),
               "two words\n--literal\n\nlast", "argument forwarding")
        output = _probe(driver, app, "--version", options=("--command=/usr/bin/ldconfig",))
        driver.check(output.startswith("ldconfig "), "runtime command overrides app probe")
        _equal(driver, _probe(driver, app, "exists", "/app/bin/blackbox-probe"), "exists", "/app")
        _equal(driver, _probe(driver, app, "exists", "/usr/bin/ldconfig"), "exists", "/usr")
    elif name == "sandbox-var":
        _probe(driver, app, "write", "/var/data/blackbox-marker", "persistent-data")
        _equal(driver, _probe(driver, app, "read", "/var/data/blackbox-marker"),
               "persistent-data", "var data persists across invocations")
    elif name == "sandbox-selectors":
        options: tuple[str, ...] = (f"--arch={fixture['arch']}", f"--branch={fixture['branch']}")
        _equal(driver, _probe(driver, app, options=options), "A", "explicit installed ref")
        unavailable_arch = "aarch64" if fixture["arch"] != "aarch64" else "x86_64"
        result = driver.cli_call("run", "--user", f"--arch={unavailable_arch}", app)
        driver.check(result.returncode != 0 and unavailable_arch in result.stderr,
                     f"run must not fall back from unavailable architecture: {result!r}")
        _equal(driver, _probe(driver, app), "A", "failed run selector preserves current app")
        missing = driver.cli_call("run", "--user", "--branch=blackbox-missing", app)
        driver.check(missing.returncode != 0 and "blackbox-missing" in missing.stderr,
                     "missing branch must not fall back to current")
        for option in ("--runtime=org.blackbox.Missing", "--runtime-version=blackbox-missing"):
            result = driver.cli_call("run", "--user", option, app)
            driver.check(result.returncode != 0 and "Missing" in result.stderr
                         if "org.blackbox" in option else
                         result.returncode != 0 and "blackbox-missing" in result.stderr,
                         f"runtime selector must not fall back: {result!r}")
        options = (f"--runtime={fixture['runtime']}/{fixture['arch']}/blackbox-missing",
                   f"--runtime-version={fixture['branch']}")
        _equal(driver, _probe(driver, app, options=options), "A", "runtime version precedence")
    else:
        raise ValueError(f"unknown sandbox scenario: {name}")
