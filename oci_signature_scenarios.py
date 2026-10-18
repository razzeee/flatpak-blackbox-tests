# SPDX-License-Identifier: LGPL-2.1-or-later
"""OCI lookaside selection and trust checks using independently signed payloads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from build_scenarios import _key_home
from fixture_manifest import FixtureManifest
from install_option_scenarios import _state
from oci_registry import Image, Registry

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def signature_path(prefix: str, image: Image) -> str:
    return f"/{prefix}/application@{image.digest.replace(':', '=')}/signature-1"


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    layouts = fixture.get("build_options", {}).get("oci_updates")
    if layouts is None or "build" not in fixture:
        raise PrerequisiteError("independent OCI revisions and disposable signing keys required")
    mode = name.removeprefix("oci-signatures-")
    if mode not in {"missing", "untrusted", "tampered", "modify-url", "stale-update"}:
        raise ValueError(f"unknown OCI signature scenario: {name}")
    root = Path(fixture["directory"])
    images = {label: Image.load(root / layouts[f"app_{label}"]) for label in ("A", "B")}
    registry = Registry({"application": images["A"]})
    home = _key_home(driver, fixture)
    public = root / fixture["build"]["public_key"]
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    expected = {runtime: fixture["runtime_commit"]}

    def setup(*args: str) -> str:
        result = driver.external_call(list(args), "setup")
        driver.check(result.returncode == 0, f"independent signature setup: {result.stderr}")
        return result.stdout.strip()

    try:
        # Native runtime input keeps app trust failures independent of dependency
        # ordering. No target-generated image or signature is used as an oracle.
        repository.version = "A"
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "dependency", url)
        driver.cli_success("install", "--user", "--noninteractive", "dependency", runtime)
        _state(driver, expected)
        with registry.serving() as registry_url:
            def sign(image: Image, key: str, label: str) -> bytes:
                payload = driver.root / f"{label}.json"
                payload.write_text(json.dumps({"critical": {
                    "type": "atomic container signature",
                    "image": {"docker-manifest-digest": image.digest},
                    "identity": {"docker-reference":
                                 f"{registry_url.removeprefix('oci+http://')}/application:latest"},
                }, "optional": {}}))
                signed = driver.root / f"{label}.sig"
                setup("gpg", "--homedir", str(home), "--batch", "--pinentry-mode", "loopback",
                      "--passphrase", "", "--local-user", key, "--output", str(signed),
                      "--sign", str(payload))
                return signed.read_bytes()

            trusted = sign(images["A"], fixture["build"]["key_id"], "trusted-A")
            good_path = signature_path("trusted", images["A"])
            selected_path = signature_path("selected", images["A"])
            registry.signatures[good_path] = trusted
            if mode == "untrusted":
                setup("gpg", "--homedir", str(home), "--batch", "--pinentry-mode", "loopback",
                      "--passphrase", "", "--quick-generate-key",
                      "Untrusted OCI fixture <untrusted@example.invalid>", "rsa2048", "sign", "0")
                registry.signatures[selected_path] = sign(
                    images["A"], "untrusted@example.invalid", "untrusted-A")
            elif mode == "tampered":
                # Damage the signed message, not the registry image or digest.
                registry.signatures[selected_path] = trusted[:len(trusted) // 2]
            elif mode == "stale-update":
                registry.signatures[selected_path] = trusted

            lookaside = registry_url.removeprefix("oci+")
            driver.cli_success("remote-add", "--user", f"--gpg-import={public}",
                               f"--signature-lookaside={lookaside}/selected", "oci", registry_url)

            def reject(operation: str) -> None:
                start = len(registry.requests)
                remote = ("oci",) if operation == "install" else ()
                result = driver.cli_call(operation, "--user", "--noninteractive", "--no-deps",
                                         *remote, app)
                driver.check(result.returncode > 0 and any(
                    token in result.stderr.lower() for token in ("signature", "gpg", "public key")),
                    f"OCI trust failure must reject deployment: {result.stderr}")
                _state(driver, expected)
                wanted = signature_path("selected", registry.images["application"])
                driver.check(wanted in registry.requests[start:],
                             f"trust rejection must fetch the selected image's signature: {wanted}")

            def install(version: str, operation: str = "install") -> None:
                remote = ("oci",) if operation == "install" else ()
                driver.cli_success(operation, "--user", "--noninteractive", "--no-deps",
                                   *remote, app)
                expected[app] = driver.cli_success("info", "--user", "--show-commit", app)
                _state(driver, expected)
                digest = driver.cli_success("remote-info", "--user", "--show-commit", "oci", app)
                driver.check(digest == images[version].digest.removeprefix("sha256:"),
                             "remote image identity matches the independent signed revision")
                driver.check(driver.success("run", app) == version,
                             f"signed OCI revision {version} executes independent expected bytes")

            if mode == "stale-update":
                install("A")
                registry.publish("application", images["B"])
                stale_path = signature_path("selected", images["B"])
                registry.signatures[stale_path] = trusted
                reject("update")
                driver.check(driver.success("run", app) == "A",
                             "rejected stale signature preserves the runnable previous deployment")
                registry.signatures[stale_path] = sign(
                    images["B"], fixture["build"]["key_id"], "trusted-B")
                install("B", "update")
            else:
                reject("install")
                start = len(registry.requests)
                if mode == "modify-url":
                    driver.cli_success("remote-modify", "--user",
                                       f"--signature-lookaside={lookaside}/trusted", "oci")
                else:
                    registry.signatures[selected_path] = trusted
                install("A")
                requests = registry.requests[start:]
                wanted = good_path if mode == "modify-url" else selected_path
                driver.check(wanted in requests,
                             "successful install fetches the selected signature")
                if mode == "modify-url":
                    driver.check(not any(path.startswith("/selected/") for path in requests),
                                 "modified lookaside replaces the old URL")
    finally:
        driver.evidence.append({"observation": "oci-signature-requests",
                                "data": list(registry.requests)})
        setup("gpgconf", "--homedir", str(home), "--kill", "gpg-agent")
