# SPDX-License-Identifier: LGPL-2.1-or-later
"""Prepare supplemental transaction fixtures using reference repository exporters."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import subprocess
import tempfile
from pathlib import Path

from fixture_manifest import (
    FixtureContracts,
    FixtureManifest,
    FixtureSize,
    FixtureTransactions,
    load_fixture,
    parse_fixture,
    parse_size,
)


def prepare_contracts(reference_cli: str, output: Path,
                      fixture: FixtureManifest) -> FixtureContracts:
    """Runnable apps, distinct SDK/debug refs, and isolated dependency updates."""
    root = output / "contracts"
    root.mkdir()
    arch = fixture["arch"]
    names = {"one": "org.flatpak.ContractOne", "two": "org.flatpak.ContractTwo",
             "platform": "org.flatpak.ContractPlatform", "sdk": "org.flatpak.ContractSdk",
             "extension": "org.flatpak.ContractPlatform.Extra",
             "shared": "org.flatpak.ContractOne.Shared"}
    names.update({f"{alias}_debug": names[alias] + ".Debug"
                  for alias in ("one", "two", "platform", "sdk")})
    refs = {alias: f"{'app' if alias in ('one', 'two') else 'runtime'}/{name}/{arch}/test"
            for alias, name in names.items()}

    def command(*args: str) -> str:
        return subprocess.check_output(args, text=True).strip()

    repos: dict[str, str] = {}
    commits: dict[str, dict[str, str]] = {}
    with tempfile.TemporaryDirectory(prefix="contract-export-") as temporary:
        work = Path(temporary)
        for version in ("A", "RUNTIME", "EXTENSION", "APP"):
            repo = root / version
            if version != "A":
                shutil.copytree(root / "A", repo)
            for alias, name in names.items():
                if version != "A" and alias != {"RUNTIME": "platform",
                                                "EXTENSION": "shared", "APP": "two"}[version]:
                    continue
                build = work / f"{version}-{alias}"
                is_app = alias in ("one", "two")
                if is_app or alias in ("platform", "sdk"):
                    asset = (fixture["assets"]["app_tree"] if is_app else
                             fixture["assets"]["runtime_tree"])
                    shutil.copytree(output / asset, build, symlinks=True)
                else:
                    (build / "files").mkdir(parents=True)
                    (build / "usr").mkdir()
                if is_app:
                    metadata = (f"[Application]\nname={name}\n"
                                f"runtime={names['platform']}/{arch}/test\n"
                                f"sdk={names['sdk']}/{arch}/test\ncommand=blackbox-probe\n")
                    metadata += (f"[Extension {names['shared']}]\ndirectory=share/contract\n"
                                 "version=test\n")
                    (build / "files/share/contract").mkdir(parents=True, exist_ok=True)
                else:
                    metadata = f"[Runtime]\nname={name}\n"
                if alias == "platform":
                    metadata += (f"[Extension {names['extension']}]\n"
                                 "directory=share/contract-platform\nversion=test\n")
                    (build / "usr/share/contract-platform").mkdir(parents=True)
                if alias in ("one", "two", "platform", "sdk"):
                    metadata += (f"[Extension {name}.Debug]\ndirectory=lib/debug\n"
                                 "version=test\nno-autodownload=true\nautodelete=true\n")
                else:
                    parent = ("platform" if alias == "extension" else "one" if alias == "shared"
                              else alias.removesuffix("_debug"))
                    metadata += f"[ExtensionOf]\nref={refs[parent]}\n"
                (build / "metadata").write_text(metadata)
                payload = build / ("files" if is_app else "usr") / "contract-marker"
                payload.write_text(f"{alias}:{version}\n")
                flags = [] if is_app else ["--runtime"]
                command(reference_cli, "build-export", "--disable-sandbox", f"--arch={arch}",
                        *flags, str(repo), str(build), "test")
            command(reference_cli, "build-update-repo", str(repo))
            repos[version] = str(repo.relative_to(output))
            commits[version] = {ref: command("ostree", f"--repo={repo}", "rev-parse", ref)
                                for ref in refs.values()}
    return {"repos": repos, "refs": refs, "commits": commits}


def prepare(reference_cli: str, output: Path, fixture: FixtureManifest) -> FixtureTransactions:
    """Return extras['transactions']; output is a new supplemental directory.

    fixture['directory'] identifies the baseline containing A and B. Repositories
    are independent copies. The output directory is a child of the assembled
    fixture root; returned paths are relative to that root. Exports never run
    as part of a target scenario.
    """
    output.mkdir(parents=True, exist_ok=False)
    baseline = Path(fixture["directory"])
    arch, branch = fixture["arch"], fixture["branch"]
    runtime = f"{fixture['runtime']}/{arch}/{branch}"
    apps = ["org.flatpak.TransactionFirst", "org.flatpak.TransactionSecond"]
    commits: dict[str, dict[str, str]] = {}
    payloads: dict[str, dict[str, list[str]]] = {}
    metadata: dict[str, str] = {}

    def command(*args: str) -> str:
        return subprocess.check_output(args, text=True).strip()

    with tempfile.TemporaryDirectory(prefix="transaction-export-") as temporary:
        work = Path(temporary)
        for version in ("A", "B", "EOL", "REBASE"):
            repo = output / version
            shutil.copytree(baseline / "A" if version == "A" else output / "A", repo)
            commits[version] = {}
            payloads[version] = {}
            for index, app in enumerate(apps):
                build = work / f"{version}-{index}"
                (build / "files/bin").mkdir(parents=True)
                contents = (f"[Application]\nname={app}\nruntime={runtime}\n"
                            f"sdk={runtime}\ncommand=probe\n")
                if version != "A":
                    contents += "[Context]\nshared=network;\n"
                (build / "metadata").write_text(contents)
                metadata[f"{version}:{app}"] = contents
                (build / "files/bin/probe").write_bytes(
                    random.Random(f"{version}:{app}").randbytes(1024 * 1024))
                (build / "files/bin/probe").chmod(0o755)
                command(reference_cli, "build-finish", str(build))
                before = {path.relative_to(repo).as_posix() for path in repo.rglob("*.filez")}
                flags: list[str] = []
                if index == 0 and version in ("EOL", "REBASE"):
                    flags.append("--end-of-life=Transaction fixture retired")
                    if version == "REBASE":
                        flags.append(f"--end-of-life-rebase={apps[1]}")
                command(reference_cli, "build-export", "--disable-sandbox", *flags,
                        str(repo), str(build), branch)
                ref = f"app/{app}/{arch}/{branch}"
                commits[version][ref] = command("ostree", f"--repo={repo}", "rev-parse", ref)
                after = {path.relative_to(repo).as_posix() for path in repo.rglob("*.filez")}
                payloads[version][ref] = sorted(after - before)
            command(reference_cli, "build-update-repo", str(repo))
    return {"directory": output.name, "apps": apps, "commits": commits,
            "payloads": payloads, "metadata": metadata,
            "eol_reason": "Transaction fixture retired"}


def prepare_sizes(directory: Path, fixture: FixtureManifest) -> dict[str, dict[str, FixtureSize]]:
    """Read immutable baseline commit sizes with reference ostree during preparation."""
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    result: dict[str, dict[str, FixtureSize]] = {}
    for version in ("A", "B"):
        result[version] = {}
        for ref, commit in ((app, fixture["commits"][version]),
                            (runtime, fixture["runtime_commit"])):
            values: dict[str, int] = {}
            for key in ("installed", "download"):
                raw = subprocess.check_output([
                    "ostree", f"--repo={directory / version}", "show",
                    f"--print-metadata-key=xa.{key}-size", commit,
                ], text=True)
                # ostree show renders these well-known keys in host byte order.
                values[key] = int(raw.split()[-1])
            result[version][ref] = parse_size(values, f"fixture.sizes.{version}.{ref}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--flatpak", default="flatpak")
    args = parser.parse_args()
    fixture = load_fixture(args.baseline / "fixture.json")
    fixture["directory"] = str(args.baseline.resolve())
    args.output.mkdir(parents=True, exist_ok=False)
    for version in ("A", "B"):
        shutil.copytree(args.baseline / version, args.output / version)
    fixture["sizes"] = prepare_sizes(args.output, fixture)
    extras = prepare(args.flatpak, args.output / "transactions", fixture)
    fixture.pop("directory")
    fixture.setdefault("extras", {})["transactions"] = extras
    fixture["sha256"] = {
        path.relative_to(args.output).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(args.output.rglob("*")) if path.is_file()
    }
    (args.output / "fixture.json").write_text(json.dumps(parse_fixture(fixture), indent=2) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
