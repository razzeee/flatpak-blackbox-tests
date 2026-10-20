# SPDX-License-Identifier: LGPL-2.1-or-later
"""Independent mixed-kind AppStream fixture and search option assertions."""

from __future__ import annotations

import gzip
import re
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from cli_management_scenarios import _equal, _refs

if TYPE_CHECKING:
    from fixture_manifest import FixtureManifest
    from run import Driver, RepositoryServer


TERM = "kindfilterquartz"
APP = "org.flatpak.SearchKindApp"
RUNTIME = "org.flatpak.SearchKindRuntime"


def prepare(reference_cli: str, output: Path, arch: str) -> str:
    """Export matching and nonmatching components of each ref kind independently."""
    repo = output / "search-kind-inputs"
    with tempfile.TemporaryDirectory(prefix="search-kind-export-") as temporary:
        for kind, name in (("app", APP), ("runtime", RUNTIME)):
            for matches in (True, False):
                identity = name if matches else name + "Control"
                build = Path(temporary) / identity
                files = build / ("files" if kind == "app" else "usr")
                xml = files / f"share/app-info/xmls/{identity}.xml.gz"
                xml.parent.mkdir(parents=True)
                keyword = TERM if matches else "kindfiltercontrol"
                xml.write_bytes(gzip.compress((
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<components version="0.8" origin="flatpak">'
                    '<component type="desktop">'
                    f"<id>{identity}</id><name>{identity}</name>"
                    f"<summary>Search fixture {keyword}</summary>"
                    '<bundle type="flatpak">'
                    f"{kind}/{identity}/{arch}/test</bundle>"
                    '</component></components>\n').encode(), mtime=0))
                # Deliberately use the same AppStream component type for both:
                # search must select the bundle's ref kind, not component type.
                if kind == "runtime":
                    (build / "files").mkdir()
                (build / "metadata").write_text(
                    f"[{'Application' if kind == 'app' else 'Runtime'}]\nname={identity}\n"
                    + (f"runtime=org.flatpak.SearchPlatform/{arch}/test\n"
                       if kind == "app" else ""))
                if kind == "app":
                    subprocess.run([reference_cli, "build-finish", str(build)], check=True)
                flags = ["--runtime"] if kind == "runtime" else []
                subprocess.run([reference_cli, "build-export", "--disable-sandbox",
                                f"--arch={arch}", *flags, str(repo), str(build), "test"],
                               check=True)
    subprocess.run([reference_cli, "build-update-repo", str(repo)], check=True)
    return str(repo.relative_to(output))


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError, UnsupportedCapability

    if name != "search-kind-filters":
        raise ValueError(f"unknown search kind scenario: {name}")
    # Probe the public interface, not a version: backports may expose it too.
    # A broken help command still fails normally; absence is explicitly unsupported.
    help_text = driver.cli_success("search", "--help")
    missing = [option for option in ("--app", "--runtime")
               if not re.search(rf"(?m)^\s+{option}(?:\s|$)", help_text)]
    if missing:
        raise UnsupportedCapability("search kind filters unavailable: " + ", ".join(missing))
    queries = fixture.get("queries")
    if queries is None or "search_kind_repo" not in queries:
        raise PrerequisiteError("regenerate query fixtures with search kind repository")
    uri = (Path(fixture["directory"]) / queries["search_kind_repo"]).as_uri()
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "search-kinds", uri)
    driver.cli_success("update", "--user", "--appstream", "search-kinds")
    _equal(driver, _refs(driver), set(), "search starts without deployed refs")
    for flags, expected in (((), {APP, RUNTIME}), (("--app",), {APP}),
                            (("--runtime",), {RUNTIME}),
                            (("--app", "--runtime"), {APP, RUNTIME})):
        for term, identities in ((TERM, expected), ("nonexistentkindneedle", set())):
            output = driver.cli_success("search", "--user", "--columns=application,branch",
                                        *flags, term)
            rows = [] if output == "No matches found" else output.splitlines()
            _equal(driver, sorted(rows), sorted(f"{identity}\ttest" for identity in identities),
                   f"search {flags} {term} selects exactly the expected ref kinds")
    _equal(driver, _refs(driver), set(), "kind-filtered AppStream searches deploy no refs")
