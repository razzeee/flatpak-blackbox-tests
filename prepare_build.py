# SPDX-License-Identifier: LGPL-2.1-or-later
"""Independent distribution inputs and disposable signing material for build cases."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from fixture_manifest import (
    FixtureBuildEntries,
    FixtureManifest,
    parse_build,
    parse_build_options,
)


def prepare(reference_cli: str, output: Path, fixture: FixtureManifest) -> FixtureBuildEntries:
    """Return a build entry to merge into fixture.json; all paths are relative to output."""
    root = output / "build-inputs"
    root.mkdir()
    home = root / "gpg"
    home.mkdir(mode=0o700)

    def command(*args: str) -> str:
        return subprocess.check_output(args, text=True, env={**os.environ, "LC_ALL": "C"})

    command("gpg", "--homedir", str(home), "--batch", "--pinentry-mode", "loopback",
            "--passphrase", "", "--quick-generate-key",
            "Blackbox disposable fixture <blackbox@example.invalid>", "rsa2048", "sign", "0")
    listing = command("gpg", "--homedir", str(home), "--with-colons", "--list-secret-keys")
    fingerprint = next(line.split(":")[9] for line in listing.splitlines()
                       if line.startswith("fpr:"))
    public = root / "public.gpg"
    subprocess.run(["gpg", "--homedir", str(home), "--batch", "--output", str(public),
                    "--export", fingerprint], check=True)
    signed = root / "signed"
    shutil.copytree(output / "B", signed)
    for kind, identity in (("app", fixture["app"]), ("runtime", fixture["runtime"])):
        args = ["--runtime"] if kind == "runtime" else []
        command(reference_cli, "build-sign", *args, f"--gpg-homedir={home}",
                f"--gpg-sign={fingerprint}", str(signed), identity, fixture["branch"])
    bundle = root / "app.flatpak"
    command(reference_cli, "build-bundle", str(output / "A"), str(bundle),
            fixture["app"], fixture["branch"])
    collection = "org.example.Blackbox.Build"
    usb_repo = root / "usb-source"
    command("ostree", f"--repo={usb_repo}", "init", "--mode=archive",
            f"--collection-id={collection}")
    usb_commits: dict[str, str] = {}
    for kind, identity in (("app", fixture["app"]), ("runtime", fixture["runtime"])):
        ref = f"{kind}/{identity}/{fixture['arch']}/{fixture['branch']}"
        command(reference_cli, "build-commit-from", f"--src-repo={output / 'A'}",
                f"--src-ref={ref}", f"--gpg-homedir={home}", f"--gpg-sign={fingerprint}",
                str(usb_repo), ref)
        usb_commits[kind] = command("ostree", f"--repo={usb_repo}", "rev-parse", ref).strip()
    command(reference_cli, "build-update-repo", "--deploy-collection-id",
            f"--gpg-homedir={home}", f"--gpg-sign={fingerprint}", str(usb_repo))
    permission_runtime = root / "permission-runtime"
    runtime_ref = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    command("ostree", f"--repo={output / 'A'}", "checkout", "--user-mode",
            "--force-copy", "--disable-cache",
            runtime_ref, str(permission_runtime))
    (permission_runtime / "files").rename(permission_runtime / "usr")
    (permission_runtime / "files").mkdir()
    with (permission_runtime / "metadata").open("a") as stream:
        stream.write("\n[Context]\nshared=network;\n[Environment]\nBB_INHERITED=runtime value\n")
    permissions_repo = root / "permissions-repo"
    command(reference_cli, "build-export", "--disable-sandbox", "--runtime",
            str(permissions_repo), str(permission_runtime), fixture["branch"])
    isolated_home = root / "init-home"
    isolated_home.mkdir(mode=0o700)
    environment = {**os.environ, "LC_ALL": "C", "HOME": str(isolated_home),
                   "FLATPAK_USER_DIR": str(isolated_home / "installation"),
                   "XDG_DATA_HOME": str(isolated_home / "data"),
                   "XDG_CONFIG_HOME": str(isolated_home / "config"),
                   "XDG_CACHE_HOME": str(isolated_home / "cache")}
    initialized = root / "inheritance-tree"
    for args in (["remote-add", "--user", "--no-gpg-verify", "permissions", str(permissions_repo)],
                 ["install", "--user", "--noninteractive", "permissions", runtime_ref],
                 ["build-init", str(initialized), fixture["app"], fixture["runtime"],
                  fixture["runtime"], fixture["branch"]]):
        subprocess.run([reference_cli, *args], env=environment, check=True, capture_output=True)
    shutil.rmtree(isolated_home)
    shutil.rmtree(permission_runtime)
    # Stop the agent so fixture hashing does not include transient sockets.
    command("gpgconf", "--homedir", str(home), "--kill", "gpg-agent")
    result: FixtureBuildEntries = {"build": parse_build({"gpg_home": str(home.relative_to(output)),
                      "public_key": str(public.relative_to(output)),
                      "key_id": fingerprint, "signed_repo": str(signed.relative_to(output)),
                      "bundle": str(bundle.relative_to(output)),
                      "usb_repo": str(usb_repo.relative_to(output)),
                      "collection_id": collection, "usb_commits": usb_commits,
                      "inheritance_tree": str(initialized.relative_to(output)),
                      "permissions_repo": str(permissions_repo.relative_to(output))},
                      "fixture.build")}
    result.update(prepare_options(reference_cli, output, fixture))
    return result


def prepare_options(reference_cli: str, output: Path,
                    fixture: FixtureManifest) -> FixtureBuildEntries:
    """Independent OCI and nondefault-architecture inputs, also callable on basic fixtures."""
    root = output / "build-options"
    root.mkdir()

    def command(*args: str) -> str:
        return subprocess.check_output(args, text=True, env={**os.environ, "LC_ALL": "C"}).strip()

    image = root / "reference-oci"
    command(reference_cli, "build-bundle", "--oci", str(output / "A"), str(image),
            fixture["app"], fixture["branch"])
    alternate_source = root / "oci-source"
    shutil.copytree(output / "B", alternate_source)
    oci_ref = f"app/{fixture['app']}/{fixture['arch']}/oci-selected"
    command("ostree", f"--repo={alternate_source}", "refs", f"--create={oci_ref}",
            fixture["commits"]["B"])
    command(reference_cli, "build-bundle", "--oci", str(alternate_source), str(image),
            fixture["app"], "oci-selected")
    supported = command(reference_cli, "--supported-arches").split()
    alternate = next((arch for arch in supported if arch != fixture["arch"]), None)
    options: dict[str, object] = {"oci": str(image.relative_to(output)), "oci_ref": oci_ref}
    if alternate is not None:
        repo = root / "architectures"
        shutil.copytree(output / "A", repo)
        commits: dict[str, str] = {}
        for kind, identity in (("app", fixture["app"]), ("runtime", fixture["runtime"])):
            ref = f"{kind}/{identity}/{fixture['arch']}/{fixture['branch']}"
            tree = root / f"alternate-{kind}"
            command("ostree", f"--repo={output / 'A'}", "checkout", "--force-copy",
                    "--disable-cache", "--user-mode", ref, str(tree))
            metadata = (tree / "metadata").read_text().replace(
                f"/{fixture['arch']}/", f"/{alternate}/")
            (tree / "metadata").write_text(metadata)
            extra = ["--runtime"] if kind == "runtime" else []
            if kind == "runtime":
                (tree / "files").rename(tree / "usr")
                (tree / "files").mkdir()
            command(reference_cli, "build-export", "--disable-sandbox", f"--arch={alternate}",
                    *extra, str(repo), str(tree), fixture["branch"])
            foreign_ref = f"{kind}/{identity}/{alternate}/{fixture['branch']}"
            commits[kind] = command("ostree", f"--repo={repo}", "rev-parse", foreign_ref)
        options.update(arch=alternate, arch_repo=str(repo.relative_to(output)),
                       arch_commits=commits)
        command(reference_cli, "build-update-repo", str(repo))
    return {"build_options": parse_build_options(options, "fixture.build_options")}
