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
import termios
import time
from contextlib import suppress
from pathlib import Path

from fixture_manifest import FixtureManifest
from run import Driver, PrerequisiteError, RepositoryServer, require


def _interactive_shell_argv(driver: Driver, app: str, mode: str = "-") -> list[str]:
    """Build the command that gives Bash a controlling pseudo-terminal."""
    setsid = shutil.which("setsid")
    if setsid is None:
        raise PrerequisiteError("setsid is required for pseudo-terminal execution")
    command = (
        "printf '%s\\n' 'blackbox stdin marker' | "
        f"{shlex.join([driver.cli, 'run', '--user', app, mode])}; "
        "status=$?; jobs -l; printf '\\n__BLACKBOX_RUN_STATUS=%s__\\n' \"$status\""
    )
    return [setsid, "--ctty", "/bin/bash", "--noprofile", "--norc", "-i", "-c", command]


def _terminate_terminal_session(process: subprocess.Popen[bytes]) -> None:
    """Kill all job groups in the private session, including stopped bwrap children."""
    groups = {process.pid}
    for stat in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = stat.read_text().rsplit(")", 1)[1].split()
            if int(fields[3]) == process.pid:
                groups.add(int(fields[2]))
        except (OSError, ValueError, IndexError):
            continue
    for group in groups:
        if group > 0 and group != os.getpgrp():
            with suppress(ProcessLookupError):
                os.killpg(group, signal.SIGKILL)
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=2)


def _run_interactive_pipeline(driver: Driver, app: str,
                              mode: str = "-") -> tuple[int | None, str]:
    """Read PTY output through the status marker or EOF, including after shell exit."""
    argv = _interactive_shell_argv(driver, app, mode)
    terminal, slave = pty.openpty()
    try:
        original = termios.tcgetattr(slave)
        process = subprocess.Popen(
            argv, env=driver.env, stdin=slave, stdout=slave, stderr=slave,
        )
    except BaseException:
        os.close(slave)
        os.close(terminal)
        raise
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
            if not chunk:
                break
            output.extend(chunk)
            match = re.search(rb"__BLACKBOX_RUN_STATUS=(\d+)__", output)
            if match is not None:
                status = int(match.group(1))
                break
    finally:
        _terminate_terminal_session(process)
        with suppress(termios.error):
            termios.tcsetattr(terminal, termios.TCSANOW, original)
        os.close(terminal)
    return status, output.decode(errors="replace")


def _check_pipeline(status: int | None, output: str, mode: str) -> None:
    """Distinguish job-control suspension from missing output or a command timeout."""
    require(status != 128 + signal.SIGTTOU and "Stopped" not in output,
            f"application pipeline was suspended for terminal output: {output}")
    require(status is not None,
            f"piped stdin app run timed out or ended without a status: {output}")
    require(status == 0, f"piped stdin app run exited with status {status}: {output}")
    require(output.splitlines().count("blackbox stdin marker") == 1,
            f"application did not echo exactly one marker line: {output}")
    if mode == "stdin-terminal-control":
        require("stdin-pipe=1 stdout-tty=1" in output,
                f"application did not confirm pipe input and terminal output: {output}")
        for marker in ("APPLY", "RESTORE", "COMPLETE"):
            require(output.splitlines().count(f"__BLACKBOX_TERMINAL_{marker}__") == 1,
                    f"terminal-control operation {marker} did not complete: {output}")


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    """Install the fixture and verify the CLI preserves piped stdin and terminal output."""
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    driver.setup_success("remote", url)
    driver.setup_success("install", app)
    mode = "stdin-terminal-control" if name == "stdin-terminal-control" else "-"
    status, output = _run_interactive_pipeline(driver, app, mode)
    driver.evidence.append({
        "argv": _interactive_shell_argv(driver, app, mode),
        "cli_argv": [driver.cli, "run", "--user", app, mode],
        "interface": "cli",
        "stdout": output,
        "stderr": "",
        "exit_status": status if status is not None else -1,
        "timed_out": status is None,
    })
    _check_pipeline(status, output, mode)
