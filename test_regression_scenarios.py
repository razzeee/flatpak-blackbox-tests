# SPDX-License-Identifier: LGPL-2.1-or-later
"""Negative controls for regression fixtures and their safety boundaries."""

import hashlib
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from fixture_manifest import parse_build_options
from json_validation import ValidationError
from oci_registry import Image, Registry
from oci_signature_scenarios import signature_path
from regression_scenarios import _snapshot, _wrapped
from run import ContractFailure, Driver
from scenario_catalogue import load_behaviors

SUPERVISOR = Path(__file__).with_name("signal_supervisor.py")


class CanaryTests(unittest.TestCase):
    def test_instance_id_child_failure_reports_eof_without_timeout(self) -> None:
        if not shutil.which("cc") or not shutil.which("pkg-config"):
            self.skipTest("requires a C compiler and pkg-config")
        flags = subprocess.run(["pkg-config", "--cflags", "--libs", "flatpak"],
                               text=True, capture_output=True, check=False)
        if flags.returncode:
            self.skipTest("requires libflatpak development files")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            main = root / "main.c"
            main.write_text(
                "#include <sys/resource.h>\n"
                "int blackbox_regressions_main(int argc, char **argv);\n"
                "int main(int argc, char **argv) {\n"
                "  struct rlimit limit = {0, 0};\n"
                "  setrlimit(RLIMIT_CORE, &limit);\n"
                "  return blackbox_regressions_main(argc, argv);\n}\n")
            binary = root / "instance-client"
            built = subprocess.run([
                "cc", "-Wall", "-Wextra", "-Werror", str(main),
                str(Path(__file__).with_name("client-regressions.c")),
                "-o", str(binary), *shlex.split(flags.stdout),
            ], text=True, capture_output=True, timeout=30, check=False)
            self.assertEqual(built.returncode, 0, built.stderr)
            # The actual client must observe EOF when its CLI exits before
            # writing an instance ID, not wait for the outer runner deadline.
            result = subprocess.run([
                str(binary), "instance-fd-immediate", "/bin/false",
                "app/org.example.App/x86_64/test", "a" * 64,
            ], text=True, capture_output=True, timeout=5, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("length > 0", result.stderr)

    def test_snapshot_detects_deletion_bytes_and_symlink_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bin").mkdir()
            marker = root / "bin/keep"
            marker.write_bytes(b"original")
            link = root / "passwd"
            link.symlink_to("bin/keep")
            before = _snapshot(root)
            self.assertEqual(before["passwd"], ("symlink", "bin/keep"))
            marker.write_bytes(b"modified")
            self.assertNotEqual(_snapshot(root), before)
            marker.write_bytes(b"original")
            self.assertEqual(_snapshot(root), before)
            link.unlink()
            link.write_bytes(b"original")
            self.assertNotEqual(_snapshot(root), before)
            link.unlink()
            link.symlink_to("bin/keep")
            marker.unlink()
            self.assertNotEqual(_snapshot(root), before)

    def test_export_exec_must_wrap_the_right_app(self) -> None:
        driver = Driver("cli", "/target/flatpak", None, {}, Path("."), [], 1)
        _wrapped(driver, "/target/flatpak run --branch=test org.example.App", "org.example.App")
        for command in ("/bin/true", "flatpak run org.example.Other",
                        "flatpak install org.example.App", "/bin/sh -c org.example.App"):
            with self.subTest(command=command), self.assertRaises(ContractFailure):
                _wrapped(driver, command, "org.example.App")

    def test_supervisor_rejects_unsafe_standalone_execution(self) -> None:
        result = subprocess.run([sys.executable, str(SUPERVISOR), "unused", "unused", "5"],
                                text=True, capture_output=True, timeout=10, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("private session", result.stderr)

    def test_supervisor_detects_group_leakage_and_accepts_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cli = Path(temporary) / "flatpak"
            for isolated in (False, True):
                cli.write_text(
                    f"#!{sys.executable}\nimport os, signal, sys\n"
                    + ("os.setpgid(0, 0)\n" if isolated else "")
                    + "signal.signal(signal.SIGCONT, lambda n, f: None)\n"
                    "operation = sys.argv[-1]\n"
                    "if operation == 'kill': os.kill(0, signal.SIGCONT)\n"
                    "else: os.killpg(0, signal.SIGCONT)\n"
                    "print(operation + ' delivered', flush=True)\n")
                cli.chmod(0o755)
                for operation in ("kill", "killpg"):
                    result = subprocess.run(
                        [sys.executable, str(SUPERVISOR), "10", str(cli), "run", "--user",
                         "org.example.App", "signal-group", operation],
                        text=True, capture_output=True, timeout=15,
                        start_new_session=True, check=False)
                    with self.subTest(isolated=isolated, operation=operation):
                        if isolated:
                            self.assertEqual(result.returncode, 0, result.stderr)
                            self.assertEqual(result.stdout, f"{operation} isolated\n")
                        else:
                            self.assertNotEqual(result.returncode, 0)
                            self.assertIn("host-signals=[", result.stderr)
                            self.assertNotIn("host-signals=[]", result.stderr)

    def test_registered_security_cases_remain_hard_failures(self) -> None:
        from run import expected_scenario_failures_only
        from test_runner import ExpectedFailureGateTests

        behaviors = load_behaviors(Path(__file__).parent)
        selected = {b["id"] for b in behaviors if b.get("handler") == "regression_scenarios:run"}
        self.assertTrue({"sandbox.export-filter", "sandbox.deployment-etc",
                         "sandbox.deployment-export", "sandbox.process-group"} <= selected)
        for identifier in sorted(selected):
            if not identifier.startswith(("sandbox.", "auth.")):
                continue
            report = ExpectedFailureGateTests().report({"failed"})
            report["results"][0]["behavior_id"] = identifier
            self.assertFalse(expected_scenario_failures_only(report, 1), identifier)
        # This changed interaction policy is not an authentication bypass. Keep
        # old stable failures visible under the existing non-security policy.
        report = ExpectedFailureGateTests().report({"failed"})
        report["results"][0]["behavior_id"] = "confirmation.auth-interaction"
        self.assertTrue(expected_scenario_failures_only(report, 1))

    def test_oci_signature_cases_remain_hard_failures(self) -> None:
        from run import expected_scenario_failures_only
        from test_runner import ExpectedFailureGateTests

        selected = {b["id"] for b in load_behaviors(Path(__file__).parent)
                    if b.get("handler") == "oci_signature_scenarios:run"}
        self.assertEqual(selected, {f"oci-signatures.{mode}" for mode in (
            "missing", "untrusted", "tampered", "modify-url", "stale-update")})
        for identifier in selected:
            with self.subTest(identifier=identifier):
                report = ExpectedFailureGateTests().report({"failed"})
                report["results"][0]["behavior_id"] = identifier
                self.assertFalse(expected_scenario_failures_only(report, 1))


class OCIRegistryTests(unittest.TestCase):
    def image(self, directory: Path, payload: str) -> Image:
        blobs = directory / "blobs/sha256"
        blobs.mkdir(parents=True)

        def store(value: object) -> str:
            data = json.dumps(value).encode()
            digest = hashlib.sha256(data).hexdigest()
            (blobs / digest).write_bytes(data)
            return "sha256:" + digest

        config = store({"os": "linux", "architecture": "amd64", "config": {
            "Labels": {"org.flatpak.ref": "app/org.example.App/x86_64/test", "marker": payload}}})
        manifest = store({"config": {"digest": config}, "layers": []})
        (directory / "index.json").write_text(json.dumps({"manifests": [{"digest": manifest}]}))
        return Image.load(directory)

    def test_registry_publication_and_http_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = self.image(root / "A", "A"), self.image(root / "B", "B")
            registry = Registry({"application": first})
            with registry.serving() as oci_url:
                url = oci_url.removeprefix("oci+")

                def index_digest() -> str:
                    with urlopen(url + "/index/static?architecture=amd64", timeout=5) as response:
                        return str(json.load(response)["Results"][0]["Images"][0]["Digest"])

                self.assertEqual(index_digest(), first.digest)
                with urlopen(url + "/v2/application/manifests/latest", timeout=5) as response:
                    self.assertEqual(response.read(), first.blobs[first.digest])
                    self.assertIn("manifest", response.headers["Content-Type"])
                registry.publish("application", second)
                self.assertEqual(index_digest(), second.digest)
                with urlopen(url + "/v2/application/blobs/" + first.digest, timeout=5) as response:
                    self.assertEqual(response.read(), first.blobs[first.digest])
                with self.assertRaises(HTTPError) as raised:
                    urlopen(url + "/v2/application/blobs/../../etc/passwd", timeout=5)
                self.assertEqual(raised.exception.code, 404)
                raised.exception.close()
            self.assertTrue(registry.requests)

    def test_layout_corruption_is_a_fixture_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = self.image(root, "A")
            (root / "blobs/sha256" / image.digest.removeprefix("sha256:")).write_bytes(b"bad")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                Image.load(root)

    def test_lookaside_paths_payload_replacement_and_missing_signatures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = self.image(root / "A", "A"), self.image(root / "B", "B")
            registry = Registry({"application": first})
            path = signature_path("selected", first)
            self.assertEqual(path, f"/selected/application@sha256={first.digest[7:]}/signature-1")
            with registry.serving() as oci_url:
                url = oci_url.removeprefix("oci+")
                with self.assertRaises(HTTPError) as raised:
                    urlopen(url + path, timeout=5)
                self.assertEqual(raised.exception.code, 404)
                raised.exception.close()
                for payload in (b"\x00\xffdamaged", b"replacement-signature"):
                    registry.signatures[path] = payload
                    with urlopen(url + path, timeout=5) as response:
                        self.assertEqual(response.read(), payload)
                        self.assertEqual(response.headers["Content-Type"],
                                         "application/octet-stream")
                # Neither another prefix, another digest, nor signature-2 can
                # accidentally fall back to the published signature.
                for missing in (signature_path("other", first), signature_path("selected", second),
                                path.removesuffix("1") + "2"):
                    with self.subTest(path=missing), self.assertRaises(HTTPError) as raised:
                        urlopen(url + missing, timeout=5)
                    self.assertEqual(raised.exception.code, 404)
                    raised.exception.close()
            self.assertIn(path, registry.requests)

    def test_optional_registry_layouts_are_validated(self) -> None:
        basic = {"oci": "image", "oci_ref": "app/org.example.App/x86_64/test"}
        self.assertNotIn("oci_updates", parse_build_options(basic, "options"))
        layouts = {"app_A": "A", "app_B": "B", "runtime": "runtime"}
        self.assertEqual(parse_build_options({**basic, "oci_updates": layouts}, "options")
                         ["oci_updates"], layouts)
        with self.assertRaises(ValidationError):
            parse_build_options({**basic, "oci_updates": {"app_A": "A"}}, "options")


if __name__ == "__main__":
    unittest.main()
