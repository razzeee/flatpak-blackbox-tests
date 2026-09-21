# SPDX-License-Identifier: LGPL-2.1-or-later
"""Real private-bus ownership, method access and traffic logging in sandboxes."""

from __future__ import annotations

import shutil
import subprocess
import sysconfig
import time
from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from report_schema import EvidenceRecord

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError, terminate

    del repository
    _, _, command, bus = name.split("-")
    if command not in {"build", "run"} or bus not in {"session", "system"}:
        raise ValueError(f"unknown bus option scenario: {name}")
    for tool in ("/usr/bin/dbus-send", "/usr/bin/dbus-test-tool"):
        if not Path(tool).is_file():
            raise PrerequisiteError(f"private bus tests require {tool}")
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture", url)
    driver.cli_success("install", "--user", "--noninteractive", "fixture",
                       app if command == "run" else runtime)
    tree = driver.root / "build-tree"
    if command == "build":
        shutil.copytree(Path(fixture["directory"]) / fixture["assets"]["app_tree"], tree)
        (tree / "var").mkdir(exist_ok=True)
    libraries = ["/run/host/usr/lib64", "/run/host/usr/lib"]
    multiarch = sysconfig.get_config_var("MULTIARCH")
    if isinstance(multiarch, str) and (Path("/usr/lib") / multiarch).is_dir():
        libraries.insert(0, f"/run/host/usr/lib/{multiarch}")
    access: tuple[str, ...] = (
        "--filesystem=host-os:ro", f"--env=LD_LIBRARY_PATH={':'.join(libraries)}")
    prefix = "system-" if bus == "system" else ""
    if bus == "system":
        driver.env["DBUS_SYSTEM_BUS_ADDRESS"] = driver.env["DBUS_SESSION_BUS_ADDRESS"]
        access += ("--unset-env=DBUS_SYSTEM_BUS_ADDRESS",)
    owner = "org.blackbox.Ownership"
    destination = "org.blackbox.Echo"
    ping = (f"--{bus}", "--print-reply", "--reply-timeout=2000", f"--dest={destination}",
            "/", "org.blackbox.Test.Ping")
    own = (f"--{bus}", "--print-reply", "--reply-timeout=2000", "--dest=org.freedesktop.DBus",
           "/org/freedesktop/DBus", "org.freedesktop.DBus.RequestName",
           f"string:{owner}", "uint32:4")

    def invoke(args: tuple[str, ...], *options: str) -> subprocess.CompletedProcess[str]:
        if command == "run":
            return driver.cli_call("run", "--user", *access, *options,
                                   "--command=/run/host/usr/bin/dbus-send", app, *args)
        return driver.cli_call("build", *access, *options, str(tree),
                               "/run/host/usr/bin/dbus-send", *args)

    def denied(result: subprocess.CompletedProcess[str]) -> None:
        driver.check(result.returncode != 0 and any(
            text in result.stderr for text in ("AccessDenied", "ServiceUnknown")),
            f"the private bus proxy must reject access: {result.stdout} {result.stderr}")

    # build normally bypasses its bus proxies. An unrelated explicit rule keeps
    # the relevant proxy active even when the option under test is removed.
    unrelated_talk = f"--{prefix}talk-name=org.blackbox.Unrelated"
    unrelated_own = f"--{prefix}own-name=org.blackbox.Unrelated"
    denied(invoke(own, unrelated_talk))
    granted = invoke(own, unrelated_talk, f"--{prefix}own-name={owner}")
    driver.check(granted.returncode == 0 and
                 any(line.strip() == "uint32 1" for line in granted.stdout.splitlines()),
                 f"ownership grant must actually acquire the bus name: {granted.stderr}")
    denied(invoke(own, unrelated_talk))

    argv = ["/usr/bin/dbus-test-tool", "echo", f"--{bus}", f"--name={destination}"]
    record: EvidenceRecord = {"argv": argv}
    driver.evidence.append(record)
    service = subprocess.Popen(argv, env=driver.env, cwd=driver.root, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while True:
            result = driver.external_call(["/usr/bin/dbus-send", *ping], "setup")
            if result.returncode == 0:
                break
            driver.check(service.poll() is None and time.monotonic() < deadline,
                         f"independent echo service failed: {result.stderr}")
            time.sleep(0.02)
        denied(invoke(ping, unrelated_own))
        options = (unrelated_own, f"--{prefix}talk-name={destination}")
        quiet = invoke(ping, *options)
        logged = invoke(ping, *options, f"--log-{bus}-bus")
        after = invoke(ping, *options)
        for result in (quiet, logged, after):
            driver.check(result.returncode == 0 and "method return" in result.stdout,
                         f"granted echo call must return through the proxy: {result.stderr}")
        driver.check("Ping" not in quiet.stdout + quiet.stderr and
                     "Ping" not in after.stdout + after.stderr,
                     "quiet controls must not log the method traffic")
        traffic = logged.stdout + logged.stderr
        driver.check("Ping" in traffic and destination in traffic,
                     f"traffic logging must identify the controlled call: {traffic}")
        denied(invoke(ping, unrelated_own))
    finally:
        terminate(service)
        stdout, stderr = service.communicate()
        record.update({"stdout": stdout, "stderr": stderr, "exit_status": service.returncode})
    driver.query(runtime, fixture["runtime_commit"])
    if command == "run":
        driver.query(app, fixture["commits"]["A"])
