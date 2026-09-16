# SPDX-License-Identifier: LGPL-2.1-or-later
"""Public object contracts with literal fixtures and isolated user installations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    """C assertions fail the individual contract group through the driver."""
    arguments: list[str] = []
    user_path = Path(driver.env.get(
        "FLATPAK_USER_DIR", str(Path(driver.env["XDG_DATA_HOME"]) / "flatpak")))
    if name == "objects-arches":
        arguments = [str(fixture["arch"])]
    elif name == "objects-installation-identity":
        arguments = [str(user_path)]
    elif name == "objects-custom-path":
        app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
        runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
        repository.version = "A"
        driver.success("remote", url)
        driver.success("install", app)
        arguments = [str(driver.root / "custom-user"), app, runtime]
    elif name == "objects-overrides":
        driver.cli_success(
            "override", "--user", "--env=BLACKBOX_OBJECTS=objects-value",
            "--env=BLACKBOX_OBJECTS_SECOND=two words=three", "org.example.Objects")
        driver.cli_success(
            "override", "--user", "--env=BLACKBOX_OBJECTS=other-app-value",
            "org.example.OtherObjects")
    elif name in {
        "objects-remote-description", "objects-remote-policy",
        "objects-remote-verification", "objects-remote-branch",
        "objects-remote-filter", "objects-remote-clear-filter",
    }:
        path = driver.root / "objects.filter"
        path.write_text("allow app/org.example.*/*/*\n")
        arguments = [str(path)]
    driver.success(name, *arguments)
