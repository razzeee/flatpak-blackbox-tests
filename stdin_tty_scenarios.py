# SPDX-License-Identifier: LGPL-2.1-or-later
"""Interactive-shell regression checks for piped app stdin and terminal output."""

import os
import pty
import re
import select
import shlex
import shutil
import signal
import subprocess
import time
from contextlib import suppress

from fixture_manifest import FixtureManifest
from run import Driver, PrerequisiteError, RepositoryServer, require


def _interactive_shell_argv(driver: Driver, app: str) -> list[str]:
    """Build the command that gives Bash a controlling pseudo-terminal."""
    setsid = shutil.which("setsid")
    if setsid is None:
        raise PrerequisiteError("setsid is required for pseudo-terminal execution")
    command = (
        "printf '%s\\n' 'blackbox stdin marker' | "
        f"{shlex.join([driver.cli, 'run', '--user', app, '-'])}; "
        "status=$?; printf '\\n__BLACKBOX_RUN_STATUS=%s__\\n' \"$status\""
    )
    return [setsid, "--ctty", "/bin/bash", "--noprofile", "--norc", "-i", "-c", command]


def _run_interactive_pipeline(driver: Driver, app: str) -> tuple[int | None, str]:
    """Read PTY output through the status marker or EOF, including after shell exit."""
    argv = _interactive_shell_argv(driver, app)
    terminal, slave = pty.openpty()
    process = subprocess.Popen(
        argv, env=driver.env, stdin=slave, stdout=slave, stderr=slave,
    )
    os.close(slave)
    output = bytearray()
    status: int | None = None
    deadline = time.monotonic() + min(driver.timeout, 30)
    try:
        while time.monotonic() < deadline:
            readable, _, _ = select.select([terminal], [], [], deadline - time.monotonic())
            if not readable:
                break
            try:
                chunk = os.read(terminal, 4096)
            except OSError:
                break
            output.extend(chunk)
            match = re.search(rb"__BLACKBOX_RUN_STATUS=(\d+)__", output)
            if match is not None:
                status = int(match.group(1))
                break
    finally:
        try:
            foreground = os.tcgetpgrp(terminal)
            with suppress(ProcessLookupError):
                os.killpg(foreground, signal.SIGKILL)
        except OSError:
            pass
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=2)
        os.close(terminal)
    return status, output.decode(errors="replace")


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    """Install the fixture and verify the CLI preserves piped stdin and terminal output."""
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    driver.setup_success("remote", url)
    driver.setup_success("install", app)
    status, output = _run_interactive_pipeline(driver, app)
    driver.evidence.append({
        "argv": _interactive_shell_argv(driver, app),
        "cli_argv": [driver.cli, "run", "--user", app, "-"],
        "interface": "cli",
        "stdout": output,
        "stderr": "",
        "exit_status": status if status is not None else -1,
        "timed_out": status is None,
    })
    require(status == 0, f"piped stdin app run did not finish successfully: {output}")
    require(output.splitlines().count("blackbox stdin marker") == 1,
            f"application did not echo exactly one marker line: {output}")
    require("Stopped (tty output)" not in output,
            f"application pipeline was stopped for terminal output: {output}")
