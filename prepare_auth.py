# SPDX-License-Identifier: LGPL-2.1-or-later
"""Prepare an independently token-gated runtime with the reference exporter."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import subprocess
import tempfile
from pathlib import Path

from fixture_manifest import FixtureAuth, FixtureManifest, load_fixture, parse_fixture


def prepare(reference_cli: str, output: Path,
            fixture: FixtureManifest) -> FixtureAuth:
    """Return extras.auth with paths relative to the assembled fixture root."""
    output.mkdir(parents=True, exist_ok=False)
    name = "org.flatpak.BlackboxAuth"
    ref = f"runtime/{name}/{fixture['arch']}/{fixture['branch']}"
    repo = output / "repo"
    with tempfile.TemporaryDirectory(prefix="auth-export-") as temporary:
        build = Path(temporary)
        (build / "usr").mkdir()
        (build / "files").mkdir()
        (build / "usr/protected").write_bytes(random.Random(174).randbytes(65536))
        (build / "metadata").write_text(f"[Runtime]\nname={name}\n")
        subprocess.run([reference_cli, "build-export", "--runtime", "--token-type=2",
                        "--disable-sandbox", str(repo), str(build), fixture["branch"]],
                       check=True)
    commit = subprocess.check_output(
        ["ostree", f"--repo={repo}", "rev-parse", ref], text=True).strip()
    payloads = sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*.filez"))
    return {"directory": output.name, "ref": ref, "commit": commit,
            "payloads": payloads}


def main() -> None:
    """Assemble a small standalone fixture directory for focused auth runs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--flatpak", default="/usr/bin/flatpak")
    args = parser.parse_args()
    fixture = load_fixture(args.baseline / "fixture.json")
    args.output.mkdir(parents=True, exist_ok=False)
    for version in ("A", "B"):
        shutil.copytree(args.baseline / version, args.output / version)
    fixture["extras"] = {"auth": prepare(args.flatpak, args.output / "auth", fixture)}
    checksums = {}
    for path in sorted(args.output.rglob("*")):
        if path.is_file():
            relative = path.relative_to(args.output).as_posix()
            checksums[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    fixture["sha256"] = checksums
    (args.output / "fixture.json").write_text(json.dumps(parse_fixture(fixture), indent=2) + "\n")


if __name__ == "__main__":
    main()
