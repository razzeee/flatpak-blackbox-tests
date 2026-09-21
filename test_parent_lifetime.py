# SPDX-License-Identifier: LGPL-2.1-or-later
"""Check cleanup against late adopted processes and a stalled reap operation."""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import parent_lifetime_scenarios as lifetime
from run import terminate


class ParentLifetimeCleanupTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "linux", "requires Linux subreaper and procfs support")
    def test_late_adopted_child_is_stopped_and_reaped(self) -> None:
        script = r'''
import ctypes, os, signal, time
from parent_lifetime_scenarios import _alive, _cleanup_children, _descendants

if ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) != 0:
    raise SystemExit(77)
gate_read, gate_write = os.pipe()
pid_read, pid_write = os.pipe()
parent = os.fork()
if parent == 0:
    os.close(gate_write)
    os.close(pid_read)
    os.read(gate_read, 1)
    child = os.fork()
    if child == 0:
        os.write(pid_write, str(os.getpid()).encode())
        time.sleep(60)
    os._exit(0)
os.close(gate_read)
os.close(pid_write)
initial = _descendants(os.getpid())
assert parent in initial
os.write(gate_write, b'x')
os.close(gate_write)
late = int(os.read(pid_read, 64))
os.close(pid_read)
os.waitpid(parent, 0)
assert late not in initial and _alive(late)
statuses = {}
_cleanup_children(statuses, timeout=2)
assert statuses[late] == -signal.SIGKILL
assert not _alive(late)
try:
    os.waitpid(-1, os.WNOHANG)
except ChildProcessError:
    print('late child reaped')
else:
    raise AssertionError('cleanup left child processes behind')
'''
        process = subprocess.Popen([sys.executable, "-c", script],
                                   cwd=Path(__file__).parent, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=5)
            if process.returncode == 77:
                self.skipTest("subreaper unavailable")
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(stdout, "late child reaped\n")
        finally:
            terminate(process)

    def test_unreaped_children_reach_a_deadline_instead_of_succeeding_or_blocking(self) -> None:
        with (
            patch.object(lifetime, "_descendants", return_value=[os.getpid()]),
            patch("parent_lifetime_scenarios.os.waitpid", return_value=(0, 0)) as wait,
            patch("parent_lifetime_scenarios.time.monotonic", side_effect=(0, 0, 1)),
            patch("parent_lifetime_scenarios.time.sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "cleanup timed out"):
                lifetime._cleanup_children({}, timeout=0.5)
            self.assertGreaterEqual(wait.call_count, 2)
            self.assertTrue(all(call.args == (-1, os.WNOHANG) for call in wait.call_args_list))


if __name__ == "__main__":
    unittest.main()
