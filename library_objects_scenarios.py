# SPDX-License-Identifier: LGPL-2.1-or-later
"""Public object contracts with literal fixtures and isolated user installations."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from json_validation import json_value

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
    elif name == "objects-latest-commit":
        app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
        first, second = fixture["commits"]["A"], fixture["commits"]["B"]
        driver.check(first != second, "latest-commit control requires distinct fixture commits")
        repository.version = "A"
        driver.success("remote", url)
        driver.success("install", app)
        driver.success(name, app, first, first)
        repository.version = "B"
        driver.cli_success("update", "--user", "--noninteractive", "--no-deploy", app)
        driver.success(name, app, first, second)
        driver.cli_success("update", "--user", "--noninteractive", "--no-pull", app)
        driver.success(name, app, second, second)
        return
    elif name == "objects-transaction-reinstall":
        app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
        repository.version = "A"
        driver.success("remote", url)
        driver.success("install", app)
        arguments = [app, fixture["commits"]["A"]]
    elif name == "objects-transaction-pruning":
        from lifecycle_extra_scenarios import run as lifecycle_run

        lifecycle_run(driver, repository, url, fixture, "lifex-transaction-pruning")
        return
    elif name == "objects-transaction-deltas":
        from run import PrerequisiteError, RepositoryServer

        if shutil.which("ostree") is None:
            raise PrerequisiteError("OSTree fixture tool required to prepare static delta")
        app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
        first, second = fixture["commits"]["A"], fixture["commits"]["B"]
        source = driver.root / "delta-repositories"
        source.mkdir()
        for version in ("A", "B"):
            shutil.copytree(Path(fixture["directory"]) / version, source / version)
        delta = source / "B"
        for arguments in (
            ["static-delta", "generate", f"--from={first}", f"--to={second}"],
            ["summary", "--update"],
        ):
            result = driver.external_call(["ostree", f"--repo={delta}", *arguments], "setup")
            driver.check(result.returncode == 0,
                         f"prepare independent static delta: {result.stderr}")
        (delta / "summary.idx").unlink(missing_ok=True)
        server = RepositoryServer(source)
        with server.serving() as server_url:
            driver.success("remote", server_url)
            driver.success("install", app)
            for disabled in (False, True, False):
                server.version = "B"
                before = len(server.requests)
                driver.success("objects-transaction-update-option", app, second,
                               "disable-static-deltas", str(disabled).lower())
                requests = server.requests[before:]
                delta_requests = [item for item in requests if item["path"].startswith("/deltas/")]
                payload_requests = [item for item in requests if item["path"].endswith(".filez")]
                driver.check(bool(payload_requests) == disabled,
                             f"static-delta setting controls loose payload requests: {requests}")
                driver.check(bool(delta_requests) != disabled,
                             f"static-delta setting controls delta requests: {requests}")
                driver.evidence.append({"observation": "transaction-static-delta-selection",
                                        "data": json_value({"disable_static_deltas": disabled,
                                                            "requests": requests})})
                server.version = "A"
                driver.cli_success("update", "--user", "--noninteractive", f"--commit={first}", app)
        return
    elif name == "objects-transaction-arch":
        queries = fixture.get("queries")
        if queries is None:
            from run import PrerequisiteError
            raise PrerequisiteError("prepared multi-architecture query repository required")
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture",
                           (Path(fixture["directory"]) / queries["versions"]["A"]["repo"]).as_uri())
        driver.check(queries["foreign_arch"] != fixture["arch"], "architecture controls differ")
        for arch in (fixture["arch"], queries["foreign_arch"], fixture["arch"]):
            ref = f"app/{queries['second']}/{arch}/test"
            driver.check(ref in queries["versions"]["A"]["refs"], "expected architecture exists")
            driver.success(name, queries["second"], arch, ref)
        return
    elif name == "objects-appstream-timestamp":
        queries = fixture.get("queries")
        if queries is None:
            from run import PrerequisiteError
            raise PrerequisiteError("prepared query AppStream data required")
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture",
                           (Path(fixture["directory"]) / queries["versions"]["A"]["repo"]).as_uri())
        arguments = [fixture["arch"]]
    elif name == "objects-remote-metadata":
        from run import PrerequisiteError

        if shutil.which("ostree") is None:
            raise PrerequisiteError("OSTree fixture tool required to publish independent metadata")
        source = driver.root / "metadata-repository"
        shutil.copytree(Path(fixture["directory"]) / "A", source)
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture", source.as_uri())
        # This is a copy of the independent fixture, not the target's store.
        # Publish a plain OSTree summary so Flatpak's old summary index cannot
        # hide the independently supplied metadata.
        (source / "summary.idx").unlink(missing_ok=True)
        for title in ("Independent metadata A", "Independent metadata B"):
            result = driver.external_call(
                ["ostree", f"--repo={source}", "summary", "--update",
                 f"--add-metadata=xa.title='{title}'"], "setup")
            driver.check(result.returncode == 0, f"publish fixture metadata: {result.stderr}")
            driver.success(name, title)
        return
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
