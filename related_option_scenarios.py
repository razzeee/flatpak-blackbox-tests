# SPDX-License-Identifier: LGPL-2.1-or-later
"""Contrast related-ref processing with and without CLI suppression options."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    queries = fixture.get("queries")
    if queries is None or "selection_repo" not in queries:
        raise PrerequisiteError("independent selection and locale fixtures required")
    app = f"app/org.flatpak.Selection/{fixture['arch']}/test"
    locale = f"runtime/org.flatpak.Selection.Locale/{fixture['arch']}/test"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    expected = {app: queries["selection_commits"][app],
                locale: queries["selection_commits"][locale], runtime: fixture["runtime_commit"]}
    source = Path(fixture["directory"]) / queries["selection_repo"]
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "selection", source.as_uri())
    driver.cli_success("config", "--user", "--set", "languages", "de")

    def refs(wanted: set[str]) -> None:
        output = driver.cli_success("list", "--user", "--all", "--columns=ref").splitlines()
        short = {ref.split("/", 1)[1] for ref in wanted}
        driver.check(len(output) == len(short) and set(output) == short,
                     f"exact installed refs: expected {sorted(short)}, got {output}")
        for ref in sorted(wanted):
            driver.query(ref, expected[ref])

    def install(*options: str) -> None:
        driver.cli_success("install", "--user", "--noninteractive", *options, "selection", app)

    def uninstall(*options: str) -> None:
        driver.cli_success("uninstall", "--user", "--noninteractive", *options, app)

    if name == "related-options-install":
        install("--no-related")
        refs({app, runtime})
        uninstall()
        refs({runtime})
        install()
        refs({app, runtime, locale})
    elif name == "related-options-update":
        install("--no-related")
        refs({app, runtime})
        driver.cli_success("update", "--user", "--noninteractive", "--no-related", app)
        refs({app, runtime})
        driver.cli_success("update", "--user", "--noninteractive", app)
        refs({app, runtime, locale})
    elif name == "related-options-uninstall":
        install()
        refs({app, runtime, locale})
        uninstall("--no-related")
        refs({runtime, locale})
        install()
        refs({app, runtime, locale})
        uninstall()
        refs({runtime})
    else:
        raise ValueError(f"unknown related option scenario: {name}")
