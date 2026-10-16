# SPDX-License-Identifier: LGPL-2.1-or-later
"""Canary supervisor: run only in a new private session, never the runner's group."""

import os
import signal
import subprocess
import sys


def main() -> None:
    # Driver.external_call starts a new session; refuse unsafe standalone use.
    if os.getsid(0) != os.getpid() or os.getpgrp() != os.getpid():
        raise RuntimeError("signal canary requires its own private session and process group")
    timeout, *argv = sys.argv[1:]
    if (len(argv) != 6 or argv[1:3] != ["run", "--user"]
            or argv[-2] != "signal-group" or argv[-1] not in {"kill", "killpg"}):
        raise RuntimeError("expected one controlled signal-group CLI invocation")
    received: list[int] = []
    # SIGCONT is caught by the canary and app, but harmless to the bwrap
    # supervisor, which is allowed to be in the app's process group.
    signal.signal(signal.SIGCONT, lambda number, frame: received.append(number))
    # Positive control proves that the signal canary's handler is armed.
    os.kill(os.getpid(), signal.SIGCONT)
    if received != [signal.SIGCONT]:
        raise RuntimeError("host signal handler control failed")
    received.clear()
    operation = argv[-1]
    result = subprocess.run(argv, text=True, capture_output=True,
                            timeout=max(1, float(timeout) - 5), check=False)
    if result.returncode or result.stdout != f"{operation} delivered\n" or received:
        raise RuntimeError(f"{operation}: status={result.returncode}, "
                           f"stdout={result.stdout!r}, stderr={result.stderr!r}, "
                           f"host-signals={received}")
    print(f"{operation} isolated", flush=True)


if __name__ == "__main__":
    main()
