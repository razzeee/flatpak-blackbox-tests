# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reuse full public-result contracts for separately reported option equivalence.

These checks do not establish a distinguishable effect of the injected options.
Diagnostics may change. The ordinary results still have to satisfy the original
independent assertions, and no effect-based interface credit is requested.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from fixture_manifest import FixtureManifest

if TYPE_CHECKING:
    import subprocess

    from run import Driver, RepositoryServer


CONTRACTS = {
    "permissions": ("permission_scenarios", "run", "permissions-selection"),
    "permission-show": ("permission_scenarios", "run", "permissions-show"),
    "permission-set": ("permission_scenarios", "run", "permissions-data"),
    "permission-remove": ("permission_scenarios", "run", "permissions-remove-app"),
    "permission-reset": ("permission_scenarios", "run", "permissions-reset-app"),
    "document-export": ("document_scenarios", "run", "documents-write"),
    "documents": ("document_scenarios", "run", "documents-filter"),
    "document-info": ("document_scenarios", "run", "documents-info"),
    "document-unexport": ("document_scenarios", "run", "documents-revoke"),
    "ps": ("sandbox_scenarios", "run", "sandbox-process"),
    "enter": ("parent_process_scenarios", "run", "parent-process-options"),
    "kill": ("sandbox_scenarios", "run", "sandbox-process"),
    "info": ("run", "scenario", "lifecycle"),
    "repo": ("build_scenarios", "run", "build-repo-inspect"),
    "build-init": ("build_scenarios", "run", "build-init-metadata"),
    "build-bundle": ("build_scenarios", "run", "build-bundle-origin"),
    "build-sign": ("build_scenarios", "run", "build-sign-app"),
    "build-finish": ("build_scenarios", "run", "build-finish-metadata"),
}


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import Driver as RunnerDriver

    command = name.removeprefix("equivalent-options-")
    options: tuple[str, ...] = ("--verbose", "--ostree-verbose")
    lookaside_start = len(repository.requests)
    if command == "build-bundle-gpg-home":
        command = "build-bundle"
        module, function, scenario = CONTRACTS[command]
        home = driver.root / "unused-gpg-home"
        home.mkdir(mode=0o700)
        options = (f"--gpg-homedir={home}",)
    elif command == "build-update-repo-jobs":
        command = "build-update-repo"
        module, function, scenario = "build_scenarios", "run", "build-repo-metadata"
        options = ("--static-delta-jobs=1",)
    elif command in {"remote-add-signatures", "remote-modify-signatures"}:
        command = command.removesuffix("-signatures")
        module, function, scenario = (
            "remote_option_scenarios", "run", "remote-options-default-branch")
        options = (f"--signature-lookaside={url}/unused-signatures",)
    elif command == "preinstall-system":
        command = "preinstall"
        module, function, scenario = "maintenance_scenarios", "run", "maintenance-preinstall-sync"
        options = ("--system",)
    elif command == "document-read":
        command = "document-export"
        module, function, scenario = "document_scenarios", "run", "documents-read"
        options = ("--allow-read",)
    else:
        if command not in CONTRACTS:
            raise ValueError(f"unknown equivalent option scenario: {name}")
        module, function, scenario = CONTRACTS[command]
        if command in {"info", "repo", "build-init", "build-bundle", "build-sign"}:
            options = ("--verbose",)
        elif command == "build-finish":
            options = ("--ostree-verbose",)

    class EquivalentDriver(RunnerDriver):
        calls = 0

        def external_call(self, argv: list[str],
                          interface: str) -> subprocess.CompletedProcess[str]:
            inner: list[str] | None = None
            if interface == "cli":
                for offset in range(len(argv) - 1):
                    if argv[offset:offset + 2] == [self.cli, command]:
                        argv = [*argv[:offset + 2], *options, *argv[offset + 2:]]
                        inner = argv[offset:]
                        self.calls += 1
                        break
            result = super().external_call(argv, interface)
            if inner is not None:
                self.evidence[-1]["cli_argv"] = inner
            return result

    selected = EquivalentDriver(driver.kind, driver.cli, driver.client, driver.env,
                                driver.root, driver.evidence, driver.timeout)
    handler = cast("Callable[[Driver, RepositoryServer, str, FixtureManifest, str], None]",
                   getattr(importlib.import_module(module), function))
    handler(selected, repository, url, fixture, scenario)
    if name.endswith("-signatures"):
        driver.check(len(repository.requests) == lookaside_start,
                     "native OSTree operations must not fetch OCI lookaside signatures")
    driver.check(selected.calls > 0, "equivalence contract must invoke the selected command")
    driver.evidence.append({"observation": "default/no-op option equivalence", "data": {
        "command": command, "options": list(options), "ordinary_contract": scenario,
        "flagged_invocations": selected.calls, "option_specific_effect_established": False,
    }})
