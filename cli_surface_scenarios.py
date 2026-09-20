# SPDX-License-Identifier: LGPL-2.1-or-later
"""Focused CLI option assertions with contrasting inputs and public results."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from build_scenarios import _install_runtime, _metadata, _parse, _tree
from fixture_manifest import FixtureManifest
from sandbox_scenarios import _background

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def _descriptor(driver: Driver, arguments: list[str], trailing: list[str], value: str) -> str:
    with tempfile.TemporaryFile(dir=driver.root) as data:
        data.write(f"BLACKBOX_DESCRIPTOR={value}\0BLACKBOX_DESCRIPTOR_EMPTY=\0".encode())
        data.seek(0)
        with _background(driver, *arguments, f"--env-fd={data.fileno()}", *trailing,
                         pass_fds=(data.fileno(),)) as process:
            stdout, stderr = process.communicate(timeout=driver.timeout)
            driver.check(process.returncode == 0, f"descriptor command failed: {stderr}")
            return stdout


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    if name == "options-config-list":
        for language, extra in (("de;fr", "es"), ("ja", "pt;nl")):
            driver.cli_success("config", "--user", "--set", "languages", language)
            driver.cli_success("config", "--user", "--set", "extra-languages", extra)
            output = driver.cli_success("config", "--user", "--list")
            fields = {key: value.split(" (default:", 1)[0].strip()
                      for key, value in (line.split(":", 1) for line in output.splitlines())}
            driver.check(fields.get("languages") == language and
                         fields.get("extra-languages") == extra,
                         f"listed configuration follows both independent changes: {output}")
        return
    command = name.removeprefix("options-").removesuffix("-env-fd")
    if command not in {"build", "build-finish", "override"}:
        raise ValueError(f"unknown CLI option scenario: {name}")
    tree: Path | None = None
    if command == "build":
        repository.version = "A"
        _install_runtime(driver, fixture, url)
        tree = _tree(driver, fixture)
    for index, value in enumerate(("first=value with spaces", "second=changed value")):
        if command == "build-finish":
            tree = _tree(driver, fixture)
            tree = tree.rename(driver.root / f"finish-input-{index}")
            _descriptor(driver, [command], [str(tree)], value)
            metadata = _metadata(tree)
        elif command == "override":
            app = "org.flatpak.DescriptorSubject"
            other = "org.flatpak.DescriptorControl"
            driver.cli_success("override", "--user", "--env=BLACKBOX_DESCRIPTOR=control", other)
            _descriptor(driver, [command, "--user"], [app], value)
            metadata = _parse(driver.cli_success("override", "--user", "--show", app))
            control = _parse(driver.cli_success("override", "--user", "--show", other))
            driver.check(control.get("Environment", "BLACKBOX_DESCRIPTOR", fallback=None)
                         == "control",
                         "descriptor override is scoped to selected app")
        else:
            assert tree is not None
            output = _descriptor(driver, [command],
                                 [str(tree), "/usr/bin/blackbox-probe", "env",
                                  "BLACKBOX_DESCRIPTOR"], value)
            driver.check(output == value + "\n", "build command reads descriptor value")
            output = _descriptor(driver, [command],
                                 [str(tree), "/usr/bin/blackbox-probe", "env",
                                  "BLACKBOX_DESCRIPTOR_EMPTY"], value)
            driver.check(output == "\n", "build command preserves an empty descriptor value")
            driver.check(not _metadata(tree).has_option("Environment", "BLACKBOX_DESCRIPTOR"),
                         "build environment does not rewrite build metadata")
            continue
        driver.check(metadata.has_section("Environment"), "descriptor creates environment metadata")
        driver.check(dict(metadata.items("Environment")) == {
            "BLACKBOX_DESCRIPTOR": value, "BLACKBOX_DESCRIPTOR_EMPTY": ""},
            "descriptor imports both exact values into public metadata")
