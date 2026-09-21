# SPDX-License-Identifier: LGPL-2.1-or-later
"""Build initialization checked against independent SDK and extension payloads."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from build_scenarios import _metadata
from fixture_manifest import FixtureManifest

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    del repository, url
    contracts = fixture.get("contracts")
    if contracts is None:
        raise PrerequisiteError("independent SDK, base and extension contract inputs required")
    refs = contracts["refs"]
    source = Path(fixture["directory"]) / contracts["repos"]["A"]
    if name in {"init-options-sdk-extension", "init-options-base-extension"}:
        alias = "shared" if name == "init-options-base-extension" else "extension"
        commit = contracts["commits"]["A"][refs[alias]]
        payload = driver.external_call([
            "ostree", f"--repo={source}", "cat", commit, "/files/contract-marker",
        ], "setup")
        if payload.returncode != 0 or payload.stdout != f"{alias}:A\n":
            raise PrerequisiteError("reprepare contract fixtures with exported extension payloads")
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture", source.as_uri())
    for alias in ("platform", "extension", "one", "shared"):
        driver.cli_success("install", "--user", "--noninteractive", "fixture", refs[alias])
        driver.query(refs[alias], contracts["commits"]["A"][refs[alias]])
    sdk = refs["platform"].removeprefix("runtime/")
    identity = "org.flatpak.Initialized"
    options: tuple[str, ...]

    def initialize(label: str, *options: str) -> Path:
        tree = driver.root / f"initialized-{label}"
        driver.cli_success("build-init", *options, str(tree), identity, sdk, sdk, "test")
        return tree

    def marker(tree: Path, path: str, expected: str) -> None:
        payload = tree / path
        driver.check(payload.is_file() and payload.read_text() == expected + "\n",
                     f"initialized {path} must contain the independent {expected} payload")

    if name == "init-options-type":
        for kind in ("app", "runtime", "extension"):
            tree = initialize(kind, f"--type={kind}")
            metadata = _metadata(tree)
            group = "Application" if kind == "app" else "Runtime"
            driver.check(metadata.get(group, "name") == identity,
                         f"{kind} build metadata must use {group}")
            driver.check(metadata.has_section("Application") == (kind == "app"),
                         "non-app types must not retain app metadata")
            driver.check(metadata.has_section("ExtensionOf") == (kind == "extension"),
                         "only extension builds declare their parent")
            if kind == "runtime":
                marker(tree, "usr/contract-marker", "platform:A")
            else:
                driver.check(not (tree / "usr/contract-marker").exists(),
                             "ordinary app/extension initialization does not copy the SDK")
            if kind == "extension":
                driver.check(metadata.get("ExtensionOf", "ref") == refs["platform"],
                             "extension parent is the selected runtime ref")
        rejected = driver.cli_call("build-init", "--type=invalid", str(driver.root / "invalid"),
                                   identity, sdk, sdk)
        driver.check(rejected.returncode != 0 and not (driver.root / "invalid/metadata").exists(),
                     "unknown build type must not produce an initialized tree")
    elif name == "init-options-extension-tag":
        for index, tag in enumerate((None, "first", "second")):
            options = () if tag is None else (f"--extension-tag={tag}",)
            tree = initialize(f"tag-{index}", "--type=extension", *options)
            metadata = _metadata(tree)
            driver.check(metadata.get("ExtensionOf", "tag", fallback=None) == tag,
                         "extension initialization must preserve the selected mount-point tag")
            driver.check(metadata.get("ExtensionOf", "ref") == refs["platform"],
                         "tag changes must preserve the parent ref")
    elif name == "init-options-var":
        control = initialize("empty-var")
        driver.check(not (control / "var/contract-marker").exists(), "ordinary var has no marker")
        tree = initialize("populated-var", f"--var={refs['platform'].split('/')[1]}")
        marker(tree, "var/contract-marker", "platform:A")
        driver.check(not (tree / "files/contract-marker").exists(),
                     "var input must not replace application payloads")
    elif name in {"init-options-sdk-extension", "init-options-base-extension"}:
        base = name == "init-options-base-extension"
        alias = "shared" if base else "extension"
        path = ("files/share/contract/contract-marker" if base else
                "usr/share/contract-platform/contract-marker")
        options = ((f"--base={refs['one'].split('/')[1]}", "--base-version=test")
                   if base else ("--writable-sdk",))
        control = initialize("without-extension", *options)
        driver.check(not (control / path).exists(), "installed extension is not copied implicitly")
        flag = "--base-extension" if base else "--sdk-extension"
        tree = initialize("with-extension", *options, f"{flag}={refs[alias].split('/')[1]}")
        marker(tree, path, f"{alias}:A")
        marker(tree, "files/contract-marker" if base else "usr/contract-marker",
               "one:A" if base else "platform:A")
    else:
        raise ValueError(f"unknown initialization scenario: {name}")
