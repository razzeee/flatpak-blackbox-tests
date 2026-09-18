# SPDX-License-Identifier: LGPL-2.1-or-later
"""Execute the prepared cache builder with only the fixture's files available."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import prepare


class RuntimeLdconfigTests(unittest.TestCase):
    def run_ldconfig(self, runtime: Path, *args: str) -> subprocess.CompletedProcess[str]:
        if shutil.which("bwrap") is None:
            self.skipTest("requires bubblewrap")
        probe = subprocess.run(
            ["bwrap", "--ro-bind", "/", "/", "/usr/bin/true"],
            capture_output=True, text=True, check=False, timeout=15,
        )
        if probe.returncode:
            self.skipTest(f"unprivileged namespaces unavailable: {probe.stderr.strip()}")
        cache = runtime / "etc"
        cache.mkdir()
        return subprocess.run(
            ["bwrap", "--ro-bind", str(runtime / "usr"), "/usr",
             "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
             "--symlink", "usr/lib64", "/lib64", "--bind", str(cache), "/etc",
             "--setenv", "PATH", "/usr/bin", "--unsetenv", "LD_LIBRARY_PATH",
             "--chdir", "/", "ldconfig", *args],
            capture_output=True, text=True, check=False, timeout=15,
        )

    def check_cache(self, runtime: Path) -> None:
        result = self.run_ldconfig(runtime, "-X", "-C", "/etc/ld.so.cache")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater((runtime / "etc/ld.so.cache").stat().st_size, 0)

    def make_runtime(self, root: Path) -> Path:
        runtime = root / "runtime"
        (runtime / "usr/bin").mkdir(parents=True)
        (runtime / "usr/lib").mkdir()
        (runtime / "usr/lib64").symlink_to("lib")
        return runtime

    def test_host_ldconfig_builds_sandbox_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = self.make_runtime(Path(temporary))
            prepare.copy_ldconfig(runtime)
            self.check_cache(runtime)

    def test_wrapper_and_relative_symlink_layouts(self) -> None:
        which = shutil.which
        source = (which("ldconfig.real", path="/usr/sbin:/sbin")
                  or which("ldconfig", path="/usr/sbin:/sbin"))
        self.assertIsNotNone(source)
        assert source is not None
        for wrapper in (True, False):
            with self.subTest(wrapper=wrapper), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                host = root / "host"
                host.mkdir()
                if wrapper:
                    shutil.copy2(source, host / "ldconfig.real")
                    (host / "ldconfig").write_text('#!/bin/sh\nexec /sbin/ldconfig.real "$@"\n')
                    (host / "ldconfig").chmod(0o755)
                else:
                    shutil.copy2(source, host / "cache-builder")
                    (host / "ldconfig").symlink_to("cache-builder")
                runtime = self.make_runtime(root)

                def host_which(command: str, *, path: str, host_path: Path = host) -> str | None:
                    return which(command, path=str(host_path))

                with patch("prepare.shutil.which", side_effect=host_which):
                    prepare.copy_ldconfig(runtime)
                self.check_cache(runtime)

    def test_dynamic_executable_dependencies_are_usable(self) -> None:
        # Use a real dynamically linked executable even on hosts with static ldconfig.
        executable = shutil.which("true")
        self.assertIsNotNone(executable)
        with tempfile.TemporaryDirectory() as temporary:
            runtime = self.make_runtime(Path(temporary))
            with patch("prepare.shutil.which", side_effect=[None, executable]):
                prepare.copy_ldconfig(runtime)
            self.assertTrue(list((runtime / "usr/lib").iterdir()))
            result = self.run_ldconfig(runtime)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_unsupported_wrapper_fails_during_preparation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "ldconfig"
            script.write_text("#!/bin/sh\nexit 0\n")
            script.chmod(0o755)
            runtime = self.make_runtime(root)
            with (patch("prepare.shutil.which", side_effect=[None, str(script)]),
                  self.assertRaisesRegex(RuntimeError, "requires an ELF ldconfig")):
                prepare.copy_ldconfig(runtime)

    def test_missing_ldconfig_fails_during_preparation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = self.make_runtime(Path(temporary))
            with (patch("prepare.shutil.which", return_value=None),
                  self.assertRaisesRegex(RuntimeError, "requires ldconfig")):
                prepare.copy_ldconfig(runtime)


if __name__ == "__main__":
    unittest.main()
