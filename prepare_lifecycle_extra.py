# SPDX-License-Identifier: LGPL-2.1-or-later
"""Add lifecycle inputs to an existing rich fixture, before target execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from fixture_manifest import (
    FixtureLifecycleExtra,
    FixtureManifest,
    FixtureTrigger,
    load_fixture,
    parse_fixture,
    parse_lifecycle_extra,
)


def prepare(flatpak: str, output: Path, fixture: FixtureManifest) -> FixtureLifecycleExtra:
    root = output / "lifecycle-extra"
    root.mkdir()

    def command(*args: str) -> str:
        return subprocess.check_output(args, text=True).strip()

    build = fixture["build"]
    app = fixture["app"]
    arch, branch = fixture["arch"], fixture["branch"]
    ref = f"app/{app}/{arch}/{branch}"
    result: dict[str, object] = {"reference_version": command(flatpak, "--version")}
    foreign = fixture.get("build_options", {})
    if "arch" in foreign:
        foreign_bundle = root / "foreign-runtime.flatpak"
        command(flatpak, "build-bundle", "--runtime", f"--arch={foreign['arch']}",
                str(output / foreign["arch_repo"]), str(foreign_bundle), fixture["runtime"], branch)
        result["foreign_bundle"] = str(foreign_bundle.relative_to(output))
    for version in ("A", "B"):
        image = root / f"image-{version}"
        command(flatpak, "build-bundle", "--oci", str(output / version),
                str(image), app, branch)
        result[f"image_{version}"] = str(image.relative_to(output))
        payload = root / f"payload-{version}"
        payload.write_bytes(subprocess.check_output([
            "ostree", f"--repo={output / version}", "cat", ref,
            "/files/bin/blackbox-probe"]))
        result[f"payload_{version}"] = str(payload.relative_to(output))
    signed_bundle = root / "signed.flatpak"
    command(flatpak, "build-bundle", f"--gpg-keys={output / build['public_key']}",
            str(output / build["signed_repo"]), str(signed_bundle), app, branch)
    result["signed_bundle"] = str(signed_bundle.relative_to(output))
    sideload = root / "sideload"
    command("ostree", f"--repo={sideload}", "init", "--mode=bare-user",
            f"--collection-id={build['collection_id']}")
    command("ostree", f"--repo={sideload}", "pull-local",
            str(output / build["usb_repo"]), ref)
    command(flatpak, "build-update-repo", str(sideload))
    result["sideload_native"] = str(sideload.relative_to(output))
    command("ostree", f"--repo={output / build['usb_repo']}", "create-usb",
            "--destination-repo=usb", str(root), build["collection_id"], ref)
    result["sideload"] = str((root / "usb").relative_to(output))
    result.update(prepare_sideload_update(flatpak, output, fixture))

    # Keep SDK usage distinguishable from the app's runtime and extension usage.
    queries = fixture["queries"]
    usage_repo = root / "usage-repo"
    shutil.copytree(output / queries["versions"]["A"]["repo"], usage_repo, symlinks=True)
    usage_app = f"app/{queries['app']}/{arch}/test"
    usage_sdk = f"runtime/org.flatpak.LifecycleSDK/{arch}/test"
    sdk_tree = root / "usage-sdk-tree"
    (sdk_tree / "usr").mkdir(parents=True)
    (sdk_tree / "files").mkdir()
    (sdk_tree / "usr/sdk-payload").write_text("Independent lifecycle SDK fixture\n")
    (sdk_tree / "metadata").write_text("[Runtime]\nname=org.flatpak.LifecycleSDK\n")
    command(flatpak, "build-export", "--disable-sandbox", "--runtime", f"--arch={arch}",
            str(usage_repo), str(sdk_tree), "test")
    usage_tree = root / "usage-app-tree"
    command("ostree", f"--repo={usage_repo}", "checkout", "--user-mode",
            "--force-copy", "--disable-cache", usage_app, str(usage_tree))
    metadata = (usage_tree / "metadata").read_text()
    old_sdk = f"sdk={fixture['runtime']}/{arch}/{branch}\n"
    if metadata.count(old_sdk) != 1:
        raise ValueError("query app must declare exactly the expected original SDK")
    metadata = metadata.replace(old_sdk, f"sdk={usage_sdk.removeprefix('runtime/')}\n")
    (usage_tree / "metadata").write_text(metadata)
    command(flatpak, "build-export", "--disable-sandbox", f"--arch={arch}",
            str(usage_repo), str(usage_tree), "test")
    command(flatpak, "build-update-repo", str(usage_repo))
    expected_metadata = root / "usage-metadata"
    expected_metadata.write_bytes(subprocess.check_output([
        "ostree", f"--repo={usage_repo}", "cat", usage_app, "/metadata"]))
    result.update(
        usage_repo=str(usage_repo.relative_to(output)), usage_app=usage_app,
        usage_sdk=usage_sdk, usage_metadata=str(expected_metadata.relative_to(output)),
        usage_app_commit=command("ostree", f"--repo={usage_repo}", "rev-parse", usage_app),
        usage_sdk_commit=command("ostree", f"--repo={usage_repo}", "rev-parse", usage_sdk))
    shutil.rmtree(sdk_tree)
    shutil.rmtree(usage_tree)

    # Desktop MIME associations give run_triggers an observable public output.
    trigger_app = "org.flatpak.LifecycleExtra"
    trigger_ref = f"app/{trigger_app}/{arch}/{branch}"
    triggers: dict[str, FixtureTrigger] = {}
    result.update(trigger_app=trigger_app, triggers=triggers)
    for version in ("A", "B"):
        tree = root / f"trigger-tree-{version}"
        command("ostree", f"--repo={output / version}", "checkout", "--user-mode",
                "--force-copy", "--disable-cache", ref, str(tree))
        metadata = (tree / "metadata").read_text().replace(app, trigger_app)
        (tree / "metadata").write_text(metadata)
        shutil.rmtree(tree / "export", ignore_errors=True)
        desktop = tree / f"files/share/applications/{trigger_app}.desktop"
        desktop.parent.mkdir(parents=True, exist_ok=True)
        desktop.write_text("[Desktop Entry]\nType=Application\n"
                           f"Name=Lifecycle {version}\nExec=blackbox-probe\n"
                           f"MimeType=application/x-lifecycle-{version.lower()};\n")
        command(flatpak, "build-finish", str(tree))
        repo = root / f"triggers-{version}"
        command(flatpak, "build-export", "--disable-sandbox", str(repo), str(tree), branch)
        triggers[version] = {
            "repo": str(repo.relative_to(output)),
            "commit": command("ostree", f"--repo={repo}", "rev-parse", trigger_ref)}
        shutil.rmtree(tree)
    return parse_lifecycle_extra(result, "fixture.lifecycle_extra")


def prepare_sideload_update(flatpak: str, output: Path,
                            fixture: FixtureManifest) -> dict[str, str]:
    """Export signed B content and its app-only offline source independently."""
    build = fixture["build"]
    root = output / "sideload-update"
    root.mkdir()
    repo = root / "source"
    shutil.copytree(output / build["usb_repo"], repo, symlinks=True)
    ref = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"

    def command(*args: str) -> str:
        return subprocess.check_output(args, text=True).strip()

    with tempfile.TemporaryDirectory(prefix="sideload-signing-") as temporary:
        home = Path(temporary) / "gpg"
        shutil.copytree(output / build["gpg_home"], home)
        try:
            command(flatpak, "build-commit-from", f"--src-repo={output / 'B'}",
                    f"--src-ref={ref}", f"--gpg-homedir={home}",
                    f"--gpg-sign={build['key_id']}", str(repo), ref)
            command(flatpak, "build-update-repo", "--deploy-collection-id",
                    f"--gpg-homedir={home}", f"--gpg-sign={build['key_id']}", str(repo))
        finally:
            command("gpgconf", "--homedir", str(home), "--kill", "gpg-agent")
    commit = command("ostree", f"--repo={repo}", "rev-parse", ref)
    if commit == build["usb_commits"]["app"]:
        raise RuntimeError("sideload update must produce a distinct app commit")
    command("ostree", f"--repo={repo}", "create-usb", "--destination-repo=offline",
            str(root), build["collection_id"], ref)
    return {"sideload_update_repo": str(repo.relative_to(output)),
            "sideload_update": str((root / "offline").relative_to(output)),
            "sideload_update_commit": commit}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--flatpak", default="flatpak")
    args = parser.parse_args()
    fixture = load_fixture(args.baseline / "fixture.json")
    shutil.copytree(args.baseline, args.output, symlinks=True)
    (args.output / "fixture.json").unlink()
    fixture["lifecycle_extra"] = prepare(args.flatpak, args.output, fixture)
    fixture["sha256"] = {
        path.relative_to(args.output).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(args.output.rglob("*"))
        if path.is_file() and path != args.output / "fixture.json"
    }
    (args.output / "fixture.json").write_text(json.dumps(parse_fixture(fixture), indent=2) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
