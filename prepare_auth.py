# SPDX-License-Identifier: LGPL-2.1-or-later
"""Prepare an independently token-gated runtime with the reference exporter."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shlex
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
    # The candidate contains the independent wire-protocol authenticator, with
    # its own runtime so gio dependencies do not alter the baseline fixture.
    from prepare import copy_dependencies

    authenticator = "org.flatpak.BlackboxAuthenticator"
    authenticator_ref = f"app/{authenticator}/{fixture['arch']}/autoinstall"
    platform = "org.flatpak.BlackboxAuthPlatform"
    runtime_ref = f"runtime/{platform}/{fixture['arch']}/autoinstall"
    binary = output / "authenticator-service"
    flags = subprocess.check_output(["pkg-config", "--cflags", "--libs", "gio-2.0"], text=True)
    subprocess.run(["cc", "-O2", "-Wall", "-Wextra", "-Werror",
                    str(Path(__file__).with_name("fixture-auth-service.c")),
                    "-o", str(binary), *shlex.split(flags)], check=True)
    with tempfile.TemporaryDirectory(prefix="auth-candidate-") as temporary:
        tree = Path(temporary) / "app"
        (tree / "files/bin").mkdir(parents=True)
        shutil.copy2(binary, tree / "files/bin/blackbox-authenticator")
        runtime = Path(temporary) / "runtime"
        shutil.copytree(output.parent / fixture["assets"]["runtime_tree"], runtime, symlinks=True)
        copy_dependencies(binary, runtime)
        (runtime / "metadata").write_text(f"[Runtime]\nname={platform}\n")
        subprocess.run([reference_cli, "build-export", "--disable-sandbox", "--runtime",
                        "--token-type=0", str(repo), str(runtime), "autoinstall"], check=True,
                       stdout=subprocess.DEVNULL)
        (tree / "metadata").write_text(
            f"[Application]\nname={authenticator}\n"
            f"runtime={platform}/{fixture['arch']}/autoinstall\n"
            "command=blackbox-authenticator\n[Context]\nshared=network;\nsockets=session-bus;\n"
            f"[Session Bus Policy]\n{authenticator}=own\n")
        subprocess.run([reference_cli, "build-finish", str(tree)], check=True,
                       stdout=subprocess.DEVNULL)
        subprocess.run([reference_cli, "build-export", "--disable-sandbox", "--token-type=0",
                        str(repo), str(tree), "autoinstall"], check=True,
                       stdout=subprocess.DEVNULL)
    authenticator_commit = subprocess.check_output(
        ["ostree", f"--repo={repo}", "rev-parse", authenticator_ref], text=True).strip()
    runtime_commit = subprocess.check_output(
        ["ostree", f"--repo={repo}", "rev-parse", runtime_ref], text=True).strip()
    return {"directory": output.name, "ref": ref, "commit": commit,
             "payloads": payloads, "authenticator_ref": authenticator_ref,
             "authenticator_commit": authenticator_commit,
             "authenticator_runtime_ref": runtime_ref,
             "authenticator_runtime_commit": runtime_commit,
             "authenticator_binary": str(binary.relative_to(output.parent))}


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
    for asset in fixture["assets"].values():
        shutil.copytree(args.baseline / asset, args.output / asset, symlinks=True)
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
