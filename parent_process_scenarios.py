# SPDX-License-Identifier: LGPL-2.1-or-later
"""Observe parent sandbox PID visibility through procfs and public enter calls."""

from __future__ import annotations

import os
import selectors
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from json_validation import json_value
from parent_lifetime_scenarios import _descendants
from sandbox_scenarios import _background

if TYPE_CHECKING:
    from collections.abc import Iterator

    from run import Driver, RepositoryServer


@contextmanager
def _instance(driver: Driver, app: str, token: str,
              *options: str) -> Iterator[tuple[str, int]]:
    with _background(driver, "run", "--user", *options, f"--env=BLACKBOX_PARENT_TEST={token}",
                     app, "hold", "120") as process:
        record = driver.evidence[-1]
        assert process.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            driver.check(bool(selector.select(10)), "background sandbox must become ready")
            ready = process.stdout.readline()
        record["stdout"] = ready
        driver.check(ready == "ready\n", "background sandbox must execute the independent payload")
        deadline = time.monotonic() + 10
        while True:
            rows = driver.cli_success("ps", "--columns=instance,pid,child-pid").splitlines()
            matched = [row.split("\t") for row in rows
                       if len(row.split("\t")) == 3 and row.split("\t")[1] == str(process.pid)]
            if matched:
                driver.check(len(matched) == 1 and matched[0][2].isdecimal(),
                             "ps must identify exactly one running child")
                init = int(matched[0][2])
                # The public child PID is the sandbox init, whose environment
                # may be empty. Observe the actual holding payload below it.
                payloads = []
                for pid in _descendants(init):
                    try:
                        args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
                    except FileNotFoundError:
                        continue
                    if args and args[0].endswith(b"blackbox-probe") and b"hold" in args:
                        payloads.append(pid)
                driver.check(len(payloads) == 1, "holding sandbox must expose one fixture probe")
                yield matched[0][0], payloads[0]
                return
            driver.check(process.poll() is None and time.monotonic() < deadline,
                         "background sandbox must appear in public instance enumeration")
            time.sleep(0.02)


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    if name != "parent-process-options":
        raise ValueError(f"unknown parent process scenario: {name}")
    app = fixture["app"]
    repository.version = "A"
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture", url)
    driver.cli_success("install", "--user", "--noninteractive", "fixture", app)
    with _instance(driver, app, "parent") as (parent, parent_pid):
        parent_namespace = os.readlink(f"/proc/{parent_pid}/ns/pid")
        parent_status = Path(f"/proc/{parent_pid}/status").read_text()
        parent_pids = next(line.split()[1:] for line in parent_status.splitlines()
                           if line.startswith("NSpid:"))
        for mode in ("isolated", "expose", "share"):
            options = (() if mode == "isolated" else
                       (f"--parent-pid={parent_pid}", f"--parent-{mode}-pids"))
            token = f"child-{mode}"
            with _instance(driver, app, token, *options) as (_, child_pid):
                namespace = os.readlink(f"/proc/{child_pid}/ns/pid")
                driver.check((namespace == parent_namespace) == (mode == "share"),
                             "only sharing uses the parent's actual PID namespace")
                status = Path(f"/proc/{child_pid}/status").read_text()
                pids = next(line.split()[1:] for line in status.splitlines()
                            if line.startswith("NSpid:"))
                if mode == "expose":
                    driver.check(len(pids) > len(parent_pids),
                                 "exposure nests the child under the parent PID namespace")
                visible_pid = pids[-1] if mode == "isolated" else pids[len(parent_pids) - 1]
                result = driver.cli_call("enter", parent, "/app/bin/blackbox-probe", "read",
                                         f"/proc/{visible_pid}/environ")
                visible = (result.returncode == 0 and
                           f"BLACKBOX_PARENT_TEST={token}\0" in result.stdout)
                driver.check(visible == (mode != "isolated"),
                             "the parent must see the exact child only with explicit PID exposure")
                driver.evidence.append({"observation": "parent PID visibility", "data": json_value({
                    "mode": mode, "parent_namespace": parent_namespace,
                    "child_namespace": namespace, "parent_pids": parent_pids,
                    "child_pids": pids, "child_visible_from_parent": visible,
                })})
        rejected = driver.cli_call("run", "--user", "--parent-pid=2147483647",
                                   "--parent-share-pids", app)
        driver.check(rejected.returncode != 0 and rejected.stdout != "A\n",
                     "an absent parent cannot silently start an unrelated sandbox")
