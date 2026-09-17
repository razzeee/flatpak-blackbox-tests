# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exercise the CI namespace probe with real bubblewrap."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class CompatibilityProbeTests(unittest.TestCase):
    def test_nested_root_namespace_probe(self) -> None:
        bwrap = shutil.which("bwrap")
        if bwrap is None or os.getuid() == 0:
            self.skipTest("requires bubblewrap and an ordinary user")
        outer = subprocess.run([
            bwrap, "--unshare-all", "--ro-bind", "/", "/", "--proc", "/proc",
            "--dev", "/dev", "--uid", "0", "--gid", "0", "/usr/bin/true",
        ], capture_output=True, text=True, timeout=15, check=False)
        if outer.returncode:
            self.skipTest(f"unprivileged namespaces unavailable: {outer.stderr.strip()}")

        with tempfile.TemporaryDirectory(prefix="ci-probe-") as temporary:
            root = Path(temporary)
            (root / "logs").mkdir()
            helper = root / "build/subprojects/bubblewrap/flatpak-bwrap"
            helper.parent.mkdir(parents=True)
            helper.symlink_to(bwrap)
            suite = Path(__file__).resolve().parent
            result = subprocess.run([
                "bash", str(suite / "ci/compatibility.sh"), "probe",
            ], cwd=suite, env={
                **os.environ, "BB_CI_ROOT": str(root), "TMPDIR": str(root),
                "FLATPAK_REFERENCE_COMMIT": "0" * 40,
            }, capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
