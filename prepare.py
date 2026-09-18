# SPDX-License-Identifier: LGPL-2.1-or-later
"""Prepare immutable fixtures with reference tooling, separately from test execution."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import prepare_auth
import prepare_build
import prepare_lifecycle_extra
import prepare_queries
import prepare_transactions
from fixture_manifest import FixtureManifest, parse_fixture

APP = "org.flatpak.Blackbox"
RUNTIME = "org.flatpak.BlackboxPlatform"
BRANCH = "test"


def copy_dependencies(binary: Path, runtime: Path) -> None:
    dependencies = subprocess.run(["ldd", str(binary)], text=True, capture_output=True,
                                  env={**os.environ, "LC_ALL": "C"}, check=False)
    diagnostic = dependencies.stdout + dependencies.stderr
    if "not found" in diagnostic or (
        dependencies.returncode and "statically linked" not in diagnostic
        and "not a dynamic executable" not in diagnostic
    ):
        raise RuntimeError(f"cannot inspect {binary} dependencies: {diagnostic}")
    for line in dependencies.stdout.splitlines():
        for word in line.split():
            if word.startswith("/"):
                shutil.copy2(word, runtime / "usr/lib" / Path(word).name)


def copy_ldconfig(runtime: Path) -> None:
    """Install the cache builder at the location used by Flatpak's sandbox PATH."""
    # Debian/Ubuntu's ldconfig is a dpkg-trigger shell wrapper. The fixture
    # needs the underlying executable, without the host's shell or dpkg.
    search_path = os.defpath + ":/usr/sbin:/sbin"
    ldconfig = (shutil.which("ldconfig.real", path=search_path)
                or shutil.which("ldconfig", path=search_path))
    if ldconfig is None:
        raise RuntimeError("fixture preparation requires ldconfig")
    with Path(ldconfig).open("rb") as executable:
        if executable.read(4) != b"\x7fELF":
            raise RuntimeError(f"fixture preparation requires an ELF ldconfig: {ldconfig}")
    shutil.copy2(ldconfig, runtime / "usr/bin/ldconfig")
    # Some hosts ship a dynamically linked ldconfig rather than a static one.
    copy_dependencies(Path(ldconfig), runtime)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new fixture directory")
    parser.add_argument("--flatpak", default="flatpak", help="reference executable")
    parser.add_argument("--cc", default="cc", help="native C compiler")
    parser.add_argument("--basic", action="store_true", help="omit supplemental workflow fixtures")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)

    def command(*argv: str) -> str:
        return subprocess.check_output(argv, text=True).strip()

    arch = command(args.flatpak, "--default-arch")
    commits: dict[str, str] = {}
    runtime_commit = ""
    with tempfile.TemporaryDirectory(prefix="blackbox-prepare-") as temporary:
        work = Path(temporary)
        runtime = work / "runtime"
        (runtime / "usr/bin").mkdir(parents=True)
        (runtime / "usr/lib").mkdir()
        (runtime / "files").mkdir()
        (runtime / "metadata").write_text(f"[Runtime]\nname={RUNTIME}\n")
        copy_ldconfig(runtime)
        (runtime / "usr/lib64").symlink_to("lib")
        (runtime / "usr/lib32").symlink_to("lib")
        command(args.cc, "-O2", '-DVERSION="A"',
                str(Path(__file__).with_name("fixture-app.c")),
                "-o", str(runtime / "usr/bin/blackbox-probe"))
        copy_dependencies(runtime / "usr/bin/blackbox-probe", runtime)
        app = work / "app"
        (app / "files/bin").mkdir(parents=True)
        (app / "metadata").write_text(
            f"[Application]\nname={APP}\nruntime={RUNTIME}/{arch}/{BRANCH}\n"
            f"sdk={RUNTIME}/{arch}/{BRANCH}\ncommand=blackbox-probe\n"
        )
        for version in ("A", "B"):
            repo = output / version
            command(args.cc, "-O2", f'-DVERSION="{version}"',
                    str(Path(__file__).with_name("fixture-app.c")),
                    "-o", str(app / "files/bin/blackbox-probe"))
            if version == "A":
                copy_dependencies(app / "files/bin/blackbox-probe", runtime)
                command(args.flatpak, "build-finish", str(app))
                command(args.flatpak, "build-export", "--disable-sandbox", "--runtime",
                        str(repo), str(runtime), BRANCH)
                runtime_commit = command("ostree", f"--repo={repo}", "rev-parse",
                                         f"runtime/{RUNTIME}/{arch}/{BRANCH}")
            else:
                shutil.copytree(output / "A", repo)
            command(args.flatpak, "build-export", "--disable-sandbox",
                    str(repo), str(app), BRANCH)
            command(args.flatpak, "build-update-repo", str(repo))
            commits[version] = command(
                "ostree", f"--repo={repo}", "rev-parse", f"app/{APP}/{arch}/{BRANCH}"
            )
            if version == "A":
                (output / "assets").mkdir()
                shutil.copytree(app, output / "assets/app-tree", symlinks=True)
        assets = output / "assets"
        shutil.copytree(runtime, assets / "runtime-tree", symlinks=True)
    fixture: FixtureManifest = {
        "schema": 1, "arch": arch, "app": APP, "runtime": RUNTIME, "branch": BRANCH,
        "commits": commits, "runtime_commit": runtime_commit,
        "reference_version": command(args.flatpak, "--version"),
        "compiler": command(args.cc, "--version"),
        "assets": {"runtime_tree": "assets/runtime-tree", "app_tree": "assets/app-tree"},
        "sha256": {},
    }
    if not args.basic:
        build_inputs = prepare_build.prepare(args.flatpak, output, fixture)
        if "build" in build_inputs:
            fixture["build"] = build_inputs["build"]
        if "build_options" in build_inputs:
            fixture["build_options"] = build_inputs["build_options"]
        fixture["queries"] = prepare_queries.prepare(args.flatpak, output, fixture)["queries"]
        transaction_fixture: FixtureManifest = {**fixture, "directory": str(output)}
        transactions = prepare_transactions.prepare(
            args.flatpak, output / "transactions", transaction_fixture,
        )
        fixture["extras"] = {"transactions": transactions}
        fixture["contracts"] = prepare_transactions.prepare_contracts(args.flatpak, output, fixture)
        fixture["extras"]["auth"] = prepare_auth.prepare(args.flatpak, output / "auth", fixture)
        fixture["lifecycle_extra"] = prepare_lifecycle_extra.prepare(args.flatpak, output, fixture)
    fixture["sizes"] = prepare_transactions.prepare_sizes(output, fixture)
    hashes = {
        str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.rglob("*")) if path.is_file()
    }
    fixture["sha256"] = hashes
    (output / "fixture.json").write_text(json.dumps(parse_fixture(fixture), indent=2) + "\n")
    print(output)


if __name__ == "__main__":
    main()
