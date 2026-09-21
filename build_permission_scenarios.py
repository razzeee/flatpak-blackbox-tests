# SPDX-License-Identifier: LGPL-2.1-or-later
"""Observe build sandbox permissions through independent payload operations."""

from __future__ import annotations

import configparser
import shutil
import socket
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest

if TYPE_CHECKING:
    import subprocess

    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    del repository
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    tree = driver.root / "build-tree"
    shutil.copytree(Path(fixture["directory"]) / fixture["assets"]["app_tree"], tree)
    (tree / "var").mkdir(exist_ok=True)
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture", url)
    driver.cli_success("install", "--user", "--noninteractive", "fixture", runtime)
    driver.query(runtime, fixture["runtime_commit"])

    def call(*args: str, options: tuple[str, ...] = ()) -> subprocess.CompletedProcess[str]:
        return driver.cli_call("build", *options, str(tree), "/app/bin/blackbox-probe", *args)

    def probe(*args: str, options: tuple[str, ...] = ()) -> str:
        result = call(*args, options=options)
        driver.check(result.returncode == 0, f"build probe {args}: {result.stderr}")
        return result.stdout.strip()

    def denied(*args: str, options: tuple[str, ...]) -> None:
        result = call(*args, options=options)
        driver.check(result.returncode == 1 and f"{args[0]}:" in result.stderr,
                     f"denial must come from the payload, not sandbox setup: {result.stderr}")

    driver.check(probe() == "A", "independent build payload must run before permission assertions")
    options: tuple[str, ...]
    if name == "build-permissions-network":
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(8)
            port = str(server.getsockname()[1])
            for options, allowed in (
                (("--share=network",), True),
                (("--share=network", "--unshare=network"), False),
                (("--unshare=network", "--share=network"), True),
            ):
                if allowed:
                    driver.check(probe("tcp-connect", "127.0.0.1", port, options=options) ==
                                 "connected", "network grant must reach the host listener")
                    server.settimeout(2)
                    accepted, _ = server.accept()
                    accepted.close()
                else:
                    denied("tcp-connect", "127.0.0.1", port, options=options)
    elif name == "build-permissions-shm":
        with tempfile.NamedTemporaryFile(prefix="build-permission-", dir="/dev/shm") as marker:
            marker.write(b"independent-shared-memory")
            marker.flush()
            denied("read", marker.name, options=("--nodevice=shm",))
            driver.check(probe("read", marker.name,
                               options=("--nodevice=shm", "--device=shm")) ==
                         "independent-shared-memory", "shm grant exposes exact host marker")
            denied("read", marker.name, options=("--device=shm", "--nodevice=shm"))
    elif name == "build-permissions-socket":
        endpoint = driver.root / "ssh-agent.sock"
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(endpoint))
            server.listen(1)
            driver.env["SSH_AUTH_SOCK"] = str(endpoint)
            path = probe("env", "SSH_AUTH_SOCK", options=("--socket=ssh-auth",))
            driver.check(probe("exists", path, options=("--socket=ssh-auth",)) == "exists",
                         "socket grant exposes the controlled endpoint")
            denied("exists", path, options=("--socket=ssh-auth", "--nosocket=ssh-auth"))
            driver.check(probe("exists", path,
                               options=("--nosocket=ssh-auth", "--socket=ssh-auth")) == "exists",
                         "later socket grant restores endpoint visibility")
    elif name == "build-permissions-policy":
        with (tree / "metadata").open("a") as stream:
            stream.write("\n[Policy blackbox]\nvalues=old;\n")
        metadata = configparser.ConfigParser(interpolation=None)
        metadata.read_string(probe("read", "/.flatpak-info"))
        driver.check(metadata.get("Policy blackbox", "values") == "old;", "initial policy control")
        options = ("--add-policy=blackbox.values=keep", "--add-policy=blackbox.values=new",
                   "--remove-policy=blackbox.values=old")
        metadata.read_string(probe("read", "/.flatpak-info", options=options))
        values = set(filter(None, metadata.get("Policy blackbox", "values").split(";")))
        driver.check(values == {"keep", "new"}, f"effective policy additions and removal: {values}")
    elif name == "build-permissions-appdir":
        home = Path(driver.env["HOME"])
        data = home / ".var/app" / fixture["app"] / "data"
        data.mkdir(parents=True)
        (data / "marker").write_text("independent-app-data", encoding="utf-8")
        control = call("env", "XDG_DATA_HOME")
        driver.check(control.returncode in (0, 1) and not control.stderr,
                     "ordinary build must report a value or an unset XDG_DATA_HOME")
        ordinary = control.stdout.strip() or str(home / ".local/share")
        selected = probe("env", "XDG_DATA_HOME", options=("--with-appdir",))
        driver.check(selected == str(data) and selected != ordinary,
                     "with-appdir must select the documented per-app data directory")
        driver.check(probe("read", str(data / "marker"), options=("--with-appdir",)) ==
                     "independent-app-data", "per-app data grant exposes the seeded bytes")
        probe("write", str(data / "written"), "written-through-sandbox",
              options=("--with-appdir",))
        driver.check((data / "written").read_text() == "written-through-sandbox",
                     "with-appdir writes reach the independent host app-data directory")
        denied("read", str(Path(ordinary) / "written"), options=())
        isolated = ("--with-appdir", "--nofilesystem=host", "--nofilesystem=home")
        persistent = home / "blackbox-persist/value"
        driver.check(probe("env", "HOME", options=isolated) == str(home),
                     "persistence test uses only the isolated home")
        probe("write", str(persistent), "persistent-build-data",
              options=(*isolated, "--persist=blackbox-persist"))
        driver.check(not persistent.exists(), "persist must not write into the ordinary host home")
        denied("read", str(persistent), options=isolated)
        driver.check(probe("read", str(persistent),
                           options=(*isolated, "--persist=blackbox-persist")) ==
                     "persistent-build-data", "persisted build data survives a later invocation")
    elif name == "run-permissions-devel":
        from run import PrerequisiteError

        binary = tree / "files/bin/devel-probe"
        result = driver.external_call([
            "cc", "-Wall", "-Wextra", "-Werror", "-O2",
            str(Path(__file__).with_name("fixture-devel-probe.c")), "-o", str(binary),
        ], "setup")
        driver.check(result.returncode == 0, f"independent feature probe compile: {result.stderr}")
        host = driver.external_call([str(binary)], "setup")
        if host.returncode != 0 or "ptrace-allowed" not in host.stdout:
            raise PrerequisiteError(f"host must permit the ptrace control: {host.stderr}")
        driver.cli_success("install", "--user", "--noninteractive", "fixture", app)
        command = ("run", "--user", f"--filesystem={binary}:ro", f"--command={binary}")
        variants = [(("--disallow=devel",), False), (("--allow=devel",), True),
                    (("--allow=devel", "--disallow=devel"), False),
                    (("--allow-if=devel:true",), True), (("--allow-if=devel:false",), False)]
        for options, allowed in variants:
            result = driver.cli_call(*command, *options, app)
            driver.check(result.stdout.startswith("probe-started\n"),
                         f"feature probe must execute before its syscall: {result.stderr}")
            if allowed:
                driver.check(result.returncode == 0 and "ptrace-allowed" in result.stdout,
                             f"devel grant must allow ptrace: {result.stderr}")
            else:
                driver.check(result.returncode == 1 and "ptrace:" in result.stderr,
                             f"devel denial must reject ptrace: {result.stderr}")
    elif name == "build-permissions-diagnostics":
        for option in ("--verbose", "--ostree-verbose"):
            before, verbose, after = call(), call(options=(option,)), call()
            driver.check(before.returncode == verbose.returncode == after.returncode == 0,
                         "diagnostic and quiet build probes must succeed")
            driver.check(before.stdout == verbose.stdout == after.stdout == "A\n",
                         "diagnostics must preserve independent probe output")
            driver.check(before.stderr == after.stderr and
                         bool(set(verbose.stderr.splitlines()) - set(before.stderr.splitlines())),
                         f"build {option} must add diagnostics beyond stable quiet controls")
    else:
        raise ValueError(f"unknown build permission scenario: {name}")
    driver.query(runtime, fixture["runtime_commit"])
