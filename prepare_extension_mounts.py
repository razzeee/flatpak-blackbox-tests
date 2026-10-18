# SPDX-License-Identifier: LGPL-2.1-or-later
"""Export extension data and separate repository inventories before target execution."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from fixture_manifest import FixtureExtensionMounts, FixtureManifest


def prepare(reference_cli: str, output: Path, fixture: FixtureManifest) -> FixtureExtensionMounts:
    root = output / "extension-mounts"
    root.mkdir()
    arch = fixture["arch"]
    app = f"app/org.flatpak.ExtensionMount/{arch}/test"
    extension = f"runtime/org.flatpak.ExtensionMount.Data/{arch}/test"
    runtime = f"{fixture['runtime']}/{arch}/{fixture['branch']}"
    app_repo, combined_repo, extension_repo = (root / name for name in
                                               ("app", "combined", "extension"))

    def command(*args: str) -> str:
        return subprocess.check_output(args, text=True).strip()

    def export(repo: Path, tree: Path, ref: str) -> str:
        kind, _, _, branch = ref.split("/")
        flags = ["--runtime"] if kind == "runtime" else []
        command(reference_cli, "build-export", "--disable-sandbox", f"--arch={arch}",
                *flags, str(repo), str(tree), branch)
        return command("ostree", f"--repo={repo}", "rev-parse", ref)

    result: FixtureExtensionMounts = {
        "app": app, "extension": extension,
        "app_repo": str(app_repo.relative_to(output)),
        "combined_repo": str(combined_repo.relative_to(output)),
        "extension_repo": str(extension_repo.relative_to(output)),
        "app_commit": "", "runtime_commit": "", "combined_commit": "", "separate_commit": "",
        "combined_marker": "extension-mount:combined-repository",
        "separate_marker": "extension-mount:separate-repository",
    }
    with tempfile.TemporaryDirectory(prefix="extension-mount-export-") as temporary:
        work = Path(temporary)
        tree = work / "app"
        shutil.copytree(output / fixture["assets"]["app_tree"], tree, symlinks=True)
        (tree / "files/data").mkdir()
        (tree / "metadata").write_text(
            f"[Application]\nname={app.split('/')[1]}\nruntime={runtime}\nsdk={runtime}\n"
            "command=blackbox-probe\n"
            f"[Extension {extension.split('/')[1]}]\ndirectory=data\nversion=test\n"
            "no-autodownload=true\nautodelete=true\n")
        result["runtime_commit"] = export(
            app_repo, output / fixture["assets"]["runtime_tree"], f"runtime/{runtime}")
        result["app_commit"] = export(app_repo, tree, app)
        command(reference_cli, "build-update-repo", str(app_repo))
        shutil.copytree(app_repo, combined_repo)
        for repo, marker, key in (
            (combined_repo, result["combined_marker"], "combined_commit"),
            (extension_repo, result["separate_marker"], "separate_commit"),
        ):
            ext_tree = work / repo.name
            (ext_tree / "usr").mkdir(parents=True)
            (ext_tree / "files").mkdir()
            # Extensions with ExtensionOf export files/, unlike a standalone runtime's usr/.
            (ext_tree / "files/marker").write_text(marker + "\n")
            (ext_tree / "metadata").write_text(
                f"[Runtime]\nname={extension.split('/')[1]}\n[ExtensionOf]\nref={app}\n")
            commit = export(repo, ext_tree, extension)
            exported = command("ostree", f"--repo={repo}", "cat", extension, "/files/marker")
            if exported != marker:
                raise RuntimeError(f"extension marker export mismatch: {exported!r}")
            if key == "combined_commit":
                result["combined_commit"] = commit
            else:
                result["separate_commit"] = commit
            command(reference_cli, "build-update-repo", str(repo))
    return result
