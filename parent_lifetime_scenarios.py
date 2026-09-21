# SPDX-License-Identifier: LGPL-2.1-or-later
"""Test sandbox lifetime after the actual launching process exits."""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from report_schema import EvidenceRecord
from typed_json import parse_typed

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def _alive(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def _descendants(pid: int) -> list[int]:
    pending = [pid]
    found = []
    while pending:
        parent = pending.pop()
        found.append(parent)
        assert len(found) < 100, "unexpectedly large fixture process tree"
        with suppress(FileNotFoundError):
            children = Path(f"/proc/{parent}/task/{parent}/children").read_text().split()
            pending.extend(map(int, children))
    return found


def _launch(root: Path, argv: list[str]) -> None:
    with (root / "stdout").open("w") as stdout, (root / "stderr").open("w") as stderr:
        child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
        print(child.pid, flush=True)
        sys.stdin.read(1)
        # Exit without waiting for the sandbox. Its lifetime is what the parent
        # supervisor observes, and a subreaper owns cleanup afterward.
        os._exit(0)


def _supervise(root: Path, die: bool, argv: list[str]) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER, in this helper only
        print("subreaper unavailable", file=sys.stderr)
        return 77
    launcher = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--launch", str(root), *argv],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert launcher.stdout is not None
    target = int(launcher.stdout.readline())
    tracked = [target]
    observation = {}
    try:
        deadline = time.monotonic() + 10
        while "ready\n" not in (root / "stdout").read_text():
            assert _alive(target) and time.monotonic() < deadline, (
                "sandbox did not execute holding probe: " + (root / "stderr").read_text())
            time.sleep(0.02)
        tracked = _descendants(target)
        payloads = []
        for pid in tracked:
            try:
                args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
                if args and args[0].endswith(b"blackbox-probe") and b"hold" in args:
                    payloads.append(pid)
            except FileNotFoundError:
                pass
        assert len(payloads) == 1, f"expected one independent holding payload: {payloads}"
        payload, = payloads
        launcher.communicate("x", timeout=5)
        assert launcher.returncode == 0, "launching process did not exit normally"
        deadline = time.monotonic() + (5 if die else 1)
        while time.monotonic() < deadline:
            if die and not _alive(target) and not _alive(payload):
                break
            time.sleep(0.02)
        target_alive, payload_alive = _alive(target), _alive(payload)
        observation = {"die_with_parent": die, "launching_process_exited": True,
                       "launcher_pid": launcher.pid, "target_pid": target, "payload_pid": payload,
                       "target_alive_after_parent_exit": target_alive,
                       "payload_alive_after_parent_exit": payload_alive}
        assert target_alive == payload_alive == (not die), observation
        return 0
    finally:
        if launcher.poll() is None:
            launcher.kill()
            launcher.communicate(timeout=5)
        for pid in reversed(tracked):
            if _alive(pid):
                with suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)
        _, status = os.waitpid(target, 0)
        print(json.dumps({"argv": argv, "interface": "cli",
                          "exit_status": os.waitstatus_to_exitcode(status),
                          "stdout": (root / "stdout").read_text(),
                          "stderr": (root / "stderr").read_text()}), flush=True)
        print(json.dumps({"observation": "sandbox parent lifetime", "data": observation}),
              flush=True)
        # All owned descendants have been stopped; reap orphaned sandbox init and
        # proxy processes rather than leaving zombies in a long-running host.
        while True:
            try:
                os.waitpid(-1, 0)
            except ChildProcessError:
                break


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    command = name.removeprefix("parent-lifetime-")
    if command not in {"build", "run"}:
        raise ValueError(f"unknown parent lifetime scenario: {name}")
    repository.version = "A"
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture", url)
    driver.cli_success("install", "--user", "--noninteractive", "fixture",
                       app if command == "run" else runtime)
    tree = driver.root / "build-tree"
    if command == "build":
        shutil.copytree(Path(fixture["directory"]) / fixture["assets"]["app_tree"], tree)
        (tree / "var").mkdir(exist_ok=True)
    for die in (False, True):
        root = driver.root / f"lifetime-{die}"
        root.mkdir()
        flags = ("--die-with-parent",) if die else ()
        args = (("run", "--user", *flags, app, "hold", "120") if command == "run" else
                ("build", *flags, str(tree), "/app/bin/blackbox-probe", "hold", "120"))
        result = driver.external_call([
            sys.executable, str(Path(__file__).resolve()), "--supervise", str(root), str(int(die)),
            driver.cli, *args,
        ], "setup")
        for line in result.stdout.splitlines():
            driver.evidence.append(parse_typed(json.loads(line), EvidenceRecord, "parent lifetime"))
        if result.returncode == 77:
            raise PrerequisiteError(result.stderr)
        driver.check(result.returncode == 0,
                     f"{command} sandbox parent lifetime assertions failed: {result.stderr}")


if __name__ == "__main__":
    if len(sys.argv) >= 5 and sys.argv[1] == "--launch":
        _launch(Path(sys.argv[2]), sys.argv[3:])
    elif len(sys.argv) >= 6 and sys.argv[1] == "--supervise":
        raise SystemExit(_supervise(Path(sys.argv[2]), sys.argv[3] == "1", sys.argv[4:]))
    else:
        raise SystemExit("internal parent lifetime helper only")
