# SPDX-License-Identifier: LGPL-2.1-or-later
"""Remote metadata, subset and redirect options with independent summary inputs."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from build_scenarios import _ostree
from fixture_manifest import FixtureManifest
from install_option_scenarios import _state

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError, RepositoryServer

    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    root = Path(fixture["directory"])
    if name in {"remote-metadata-subset-add", "remote-metadata-subset-modify"}:
        adding = name.endswith("-add")
        options = ("--subset=blackbox-missing-subset",) if adding else ()
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", *options, "fixture", url)
        if not adding:
            rows = driver.cli_success("remote-ls", "--user", "--columns=ref", "fixture")
            driver.check(set(rows.splitlines()) == {app, runtime}, "ordinary remote ref set")
            driver.cli_success("remote-modify", "--user", "--subset=blackbox-missing-subset",
                               "fixture")
        driver.check(driver.cli_success("remotes", "--user", "--columns=subset") ==
                     "blackbox-missing-subset", "the configured subset must be publicly queryable")
        rejected = driver.cli_call("install", "--user", "--noninteractive", "fixture", app)
        driver.check(rejected.returncode != 0, "an absent subset must not fall back to all refs")
        _state(driver, {})
        driver.cli_success("remote-modify", "--user", "--subset=", "fixture")
        driver.cli_success("install", "--user", "--noninteractive", "fixture", app)
        _state(driver, {app: fixture["commits"]["A"], runtime: fixture["runtime_commit"]})
        return
    if name == "remote-metadata-collection":
        build = fixture.get("build")
        if build is None:
            raise PrerequisiteError("independently signed collection repository required")
        source = root / build["usb_repo"]
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture", source.as_uri())
        for collection in ("org.blackbox.SelectedCollection", build["collection_id"]):
            driver.cli_success("remote-modify", "--user", f"--collection-id={collection}",
                               "fixture")
            selected = driver.cli_success("remotes", "--user", "--columns=collection")
            driver.check(selected == collection,
                         "the explicitly selected collection identity must persist")
        driver.cli_success("remote-modify", "--user", "--gpg-verify",
                           f"--gpg-import={root / build['public_key']}", "fixture")
        driver.cli_success("install", "--user", "--noninteractive", "fixture", app)
        _state(driver, {app: build["usb_commits"]["app"], runtime: build["usb_commits"]["runtime"]})
        return

    sources = driver.root / "metadata-sources"
    sources.mkdir()
    for version in ("A", "B"):
        shutil.copytree(root / version, sources / version, symlinks=True)
        # Use the public OSTree summary format as an independent producer. Remove
        # the optional Flatpak index from these disposable copies so consumers
        # read the newly published ordinary summary instead of the old index.
        (sources / version / "summary.idx").unlink(missing_ok=True)
    server = RepositoryServer(sources)
    def record_requests() -> None:
        repository.requests.extend(server.requests)

    with server.serving(on_cleanup=record_requests) as source_url:
        if name == "remote-metadata-update":
            for version in ("A", "B"):
                _ostree(driver, sources / version, "summary", "--update",
                        f"--add-metadata=xa.title='Independent title {version}'",
                        f"--add-metadata=xa.comment='Independent comment {version}'")
            driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture", source_url)
            columns = "--columns=title,comment"
            driver.check(driver.cli_success("remotes", "--user", columns) ==
                         "Independent title A\tIndependent comment A", "initial summary metadata")
            server.version = "B"
            driver.cli_success("remote-modify", "--user", "fixture")
            driver.check(driver.cli_success("remotes", "--user", columns) ==
                         "Independent title A\tIndependent comment A", "ordinary modify retains A")
            driver.cli_success("remote-modify", "--user", "--update-metadata", "fixture")
            driver.check(driver.cli_success("remotes", "--user", columns) ==
                         "Independent title B\tIndependent comment B", "explicit refresh reads B")
            _state(driver, {})
            return

        destination = (root / "B").as_uri()
        if name == "remote-metadata-build-redirect":
            driver.cli_success("build-update-repo", f"--redirect-url={destination}",
                               str(sources / "A"))
        elif name in {"remote-metadata-add-no-redirect", "remote-metadata-modify-no-redirect",
                      "remote-metadata-follow-redirect"}:
            _ostree(driver, sources / "A", "summary", "--update",
                    f"--add-metadata=xa.redirect-url='{destination}'")
        else:
            raise ValueError(f"unknown remote metadata scenario: {name}")
        if name == "remote-metadata-add-no-redirect":
            driver.cli_success("remote-add", "--user", "--no-gpg-verify", "--no-follow-redirect",
                               "fixture", source_url)
            expected_url, version = source_url, "A"
        elif name == "remote-metadata-modify-no-redirect":
            # Start before publishing the redirect so addition cannot already
            # follow it. The later update must respect persisted opt-out.
            plain = sources / "plain"
            shutil.copytree(root / "A", plain, symlinks=True)
            server.version = "plain"
            driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture", source_url)
            driver.cli_success("remote-modify", "--user", "--no-follow-redirect", "fixture")
            server.version = "A"
            driver.cli_success("remote-modify", "--user", "--update-metadata", "fixture")
            expected_url, version = source_url, "A"
        elif name == "remote-metadata-follow-redirect":
            # An explicitly set URL opts out of summary redirects, providing a
            # public control for the later explicit follow-redirect transition.
            plain = sources / "plain"
            shutil.copytree(root / "A", plain, symlinks=True)
            server.version = "plain"
            driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture", source_url)
            driver.cli_success("remote-modify", "--user", f"--url={source_url}", "fixture")
            server.version = "A"
            driver.cli_success("remote-modify", "--user", "--update-metadata", "fixture")
            driver.check(driver.cli_success("remotes", "--user", "--columns=url") == source_url,
                         "an explicitly configured URL must initially prevent redirection")
            driver.cli_success("remote-modify", "--user", "--follow-redirect", "--update-metadata",
                               "fixture")
            expected_url, version = destination, "B"
        else:
            driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture", source_url)
            expected_url, version = destination, "B"
        driver.check(driver.cli_success("remotes", "--user", "--columns=url") == expected_url,
                     "remote URL must follow the selected redirect policy")
        driver.cli_success("install", "--user", "--noninteractive", "fixture", app)
        _state(driver, {app: fixture["commits"][version], runtime: fixture["runtime_commit"]})
