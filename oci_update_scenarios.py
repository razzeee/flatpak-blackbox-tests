# SPDX-License-Identifier: LGPL-2.1-or-later
"""OCI image identities must not be confused with their imported commit IDs."""

from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from oci_registry import Image, Registry

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    del repository, url
    layouts = fixture.get("build_options", {}).get("oci_updates")
    if layouts is None:
        raise PrerequisiteError("reprepare build options with independent OCI registry revisions")
    images = {label: Image.load(Path(fixture["directory"]) / path)
              for label, path in layouts.items()}
    registry = Registry({"application": images["app_A"], "platform": images["runtime"]})
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"

    def updates(remote: str) -> set[str]:
        return set(driver.cli_success("remote-ls", "--user", "--updates", "--columns=ref",
                                      remote).splitlines())

    with registry.serving() as registry_url:
        try:
            driver.cli_success("remote-add", "--user", "--no-gpg-verify", "oci", registry_url)
            available = set(driver.cli_success("remote-ls", "--user", "--columns=ref",
                                                "oci").splitlines())
            driver.check(available == {app, runtime}, "registry advertises independent app/runtime")
            driver.cli_success("install", "--user", "--noninteractive", "oci", app)
            old = driver.cli_success("info", "--user", "--show-commit", app)
            digest = driver.cli_success("remote-info", "--user", "--show-commit", "oci", app)
            driver.check(digest == images["app_A"].digest.removeprefix("sha256:") and old != digest,
                         "remote image identity differs from the imported commit identity")
            driver.check(driver.success("run", app) == "A", "OCI A deploys independent app A")
            driver.check(updates("oci") == set(), "just-installed OCI images have no updates")
            # A same-ref remote must not report updates for another origin's app.
            driver.cli_success("remote-add", "--user", "--no-gpg-verify", "other", registry_url)
            registry.publish("application", images["app_B"])
            driver.check(updates("other") == set(), "OCI updates respect installed origin")
            driver.check(updates("oci") == {app}, "only the published app B is an update")
            driver.cli_success("update", "--user", "--noninteractive", app)
            new = driver.cli_success("info", "--user", "--show-commit", app)
            driver.check(new != old, "OCI update changes the deployed commit")
            driver.check(driver.success("run", app) == "B", "OCI update executes independent B")
            driver.check(updates("oci") == set(), "applied OCI update disappears from listing")
        finally:
            driver.evidence.append({"observation": "oci-registry-requests",
                                    "data": list(registry.requests)})
