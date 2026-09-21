# SPDX-License-Identifier: LGPL-2.1-or-later
"""Preinstall transaction options using public vendor definitions and exact refs."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from install_option_scenarios import _state

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    del repository, url
    contracts = fixture.get("contracts")
    configured = driver.env.get("BLACKBOX_PREINSTALL_DIR")
    if contracts is None or configured is None:
        raise PrerequisiteError("independent refs and isolated vendor definitions required")
    directory = Path(configured)
    driver.check(directory.is_absolute() and directory.resolve().is_relative_to(driver.root),
                 "vendor definitions must stay inside the isolated case directory")
    directory.mkdir(parents=True, exist_ok=True)
    refs, commits = contracts["refs"], contracts["commits"]["A"]
    app = refs["one"]
    source = Path(fixture["directory"]) / contracts["repos"]["A"]
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture", source.as_uri())
    definition = directory / "options.preinstall"
    definition.write_text(f"[Flatpak Preinstall {app.split('/')[1]}]\nBranch=test\n")
    base = {app, refs["platform"], refs["extension"], refs["shared"]}

    def expected(selected: set[str]) -> None:
        _state(driver, {ref: commits[ref] for ref in selected})

    def remove() -> None:
        # Vendor removal does not establish a manual opt-out and allows the next
        # variant to start with the same actionable definition and no deployments.
        definition.write_text(
            f"[Flatpak Preinstall {app.split('/')[1]}]\nBranch=test\nInstall=false\n")
        driver.cli_success("preinstall", "--user", "-y")
        if driver.cli_success("list", "--user", "--all", "--columns=ref"):
            driver.cli_success("uninstall", "--user", "--noninteractive", "--all")
        expected(set())
        definition.write_text(f"[Flatpak Preinstall {app.split('/')[1]}]\nBranch=test\n")

    if name == "preinstall-options-includes":
        for sdk, debug in ((False, False), (True, False), (False, True), (True, True)):
            options = []
            selected = base.copy()
            if sdk:
                options.append("--include-sdk")
                selected.add(refs["sdk"])
            if debug:
                options.append("--include-debug")
                selected.update((refs["one_debug"], refs["platform_debug"]))
                if sdk:
                    selected.add(refs["sdk_debug"])
            driver.cli_success("preinstall", "--user", "--noninteractive", *options)
            expected(selected)
            remove()
    elif name == "preinstall-options-dependencies":
        for option, selected in (("--no-deps", {app, refs["shared"]}),
                                 ("--no-related", {app, refs["platform"]})):
            driver.cli_success("preinstall", "--user", "--noninteractive", option)
            expected(selected)
            remove()
        driver.cli_success("preinstall", "--user", "--noninteractive")
        expected(base)
    elif name == "preinstall-options-confirmation":
        for option in ("--assumeyes", "--noninteractive"):
            control = driver.cli_call("preinstall", "--user")
            expected(set())
            driver.check(control.returncode != 0, "preinstall must refuse without confirmation")
            result = driver.cli_call("preinstall", "--user", option)
            driver.check(result.returncode == 0, f"automatic preinstall: {result.stderr}")
            driver.check("[Y/n]" not in result.stdout and "[y/n]" not in result.stdout,
                         "automatic preinstall must not leave an unanswered prompt")
            expected(base)
            remove()
    elif name == "preinstall-options-no-pull":
        control = driver.cli_call("preinstall", "--user", "--noninteractive", "--no-pull")
        expected(set())
        driver.check(control.returncode == 0 or bool(control.stderr),
                     "uncached no-pull must either find no local candidates or explain rejection")
        driver.cli_success("preinstall", "--user", "--noninteractive")
        expected(base)
    elif name == "preinstall-options-reinstall":
        driver.cli_success("preinstall", "--user", "--noninteractive")
        expected(base)
        location = Path(driver.cli_success("info", "--user", "--show-location", app))
        marker = location / "files/contract-marker"
        driver.check(marker.read_text() == "one:A\n", "original deployed marker")
        # Replace the public payload inode rather than editing a possibly shared
        # object in place. Reinstallation must restore independently known bytes.
        marker.unlink()
        marker.write_text("locally damaged deployment\n")
        driver.cli_success("preinstall", "--user", "--noninteractive")
        driver.check(marker.read_text() == "locally damaged deployment\n",
                     "ordinary synchronization must leave an already-installed deployment alone")
        driver.cli_success("preinstall", "--user", "--noninteractive", "--reinstall")
        expected(base)
        repaired = Path(driver.cli_success("info", "--user", "--show-location", app))
        driver.check((repaired / "files/contract-marker").read_text() == "one:A\n",
                     "explicit reinstallation must restore independent payload bytes")
    else:
        raise ValueError(f"unknown preinstall option scenario: {name}")
