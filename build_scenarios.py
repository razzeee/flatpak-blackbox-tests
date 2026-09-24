# SPDX-License-Identifier: LGPL-2.1-or-later
"""Build CLI contracts against public build trees and distribution repositories."""

from __future__ import annotations

import base64
import configparser
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from json_validation import json_value

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


class Metadata(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


def _parse(text: str) -> configparser.ConfigParser:
    from run import ContractFailure

    result = Metadata(interpolation=None)
    try:
        result.read_string(text)
    except configparser.Error as error:
        raise ContractFailure(f"invalid public metadata: {error}") from error
    return result


def _metadata(tree: Path) -> configparser.ConfigParser:
    return _parse((tree / "metadata").read_text())


def _list(meta: configparser.ConfigParser, group: str, key: str) -> set[str]:
    return set(filter(None, meta.get(group, key, fallback="").split(";")))


def _ostree(driver: Driver, repo: Path, *args: str) -> str:
    from run import execute

    if args and args[0] == "checkout":
        # A mutable build input must never share inodes with a reference object's
        # uncompressed cache. Also leave immutable fixture repositories untouched.
        args = ("checkout", "--force-copy", "--disable-cache", *args[1:])
    result = execute(["ostree", f"--repo={repo}", *args], driver.env, driver.root,
                     driver.evidence, driver.timeout)
    driver.check(result.returncode == 0, f"public repository inspection failed: {result.stderr}")
    return result.stdout.strip()


def _ref(fixture: FixtureManifest, runtime: bool = False, branch: str | None = None) -> str:
    kind = "runtime" if runtime else "app"
    identity = fixture["runtime"] if runtime else fixture["app"]
    return f"{kind}/{identity}/{fixture['arch']}/{branch or fixture['branch']}"


def _copy_repo(driver: Driver, fixture: FixtureManifest, version: str = "A") -> Path:
    destination = driver.root / "distribution"
    shutil.copytree(Path(fixture["directory"]) / version, destination)
    return destination


def _tree(driver: Driver, fixture: FixtureManifest, *, finished: bool = False,
          runtime: bool = False) -> Path:
    tree = driver.root / "build-tree"
    # Checkout is independent input construction from a reference-created public repo.
    _ostree(driver, Path(fixture["directory"]) / "A", "checkout", "--user-mode",
            _ref(fixture, runtime), str(tree))
    if runtime:
        (tree / "files").rename(tree / "usr")
        (tree / "files").mkdir()
    if not finished and (tree / "export").exists():
        shutil.rmtree(tree / "export")
    (tree / "var").mkdir(exist_ok=True)
    return tree


def _install_runtime(driver: Driver, fixture: FixtureManifest, url: str) -> None:
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "build-fixture", url)
    driver.cli_success("install", "--user", "--noninteractive", "build-fixture",
                       _ref(fixture, True))


def _key_home(driver: Driver, fixture: FixtureManifest) -> Path:
    from run import PrerequisiteError

    if "build" not in fixture:
        raise PrerequisiteError("prepare_build.prepare must supply disposable signing material")
    home = driver.root / "gpg"
    shutil.copytree(Path(fixture["directory"]) / fixture["build"]["gpg_home"], home)
    home.chmod(0o700)
    return home


def _verify_signature(driver: Driver, fixture: FixtureManifest, repo: Path, ref: str) -> None:
    public = Path(fixture["directory"]) / fixture["build"]["public_key"]
    _ostree(driver, repo, "remote", "add", f"--gpg-import={public}",
            "independent-verifier", repo.as_uri())
    verification = _ostree(driver, repo, "show", "--gpg-verify-remote=independent-verifier", ref)
    driver.check("Good signature" in verification, "public-key signature verification failed")


def _finish(driver: Driver, fixture: FixtureManifest, name: str) -> None:
    if name == "build-finish-inheritance":
        from run import PrerequisiteError

        if "inheritance_tree" not in fixture.get("build", {}):
            raise PrerequisiteError("prepare_build must supply independently initialized tree")
        source = Path(fixture["directory"]) / fixture["build"]["inheritance_tree"]
        permissions_repo = Path(fixture["directory"]) / fixture["build"]["permissions_repo"]
        _install_runtime(driver, fixture, str(permissions_repo))
        for inherit in (True, False):
            destination = driver.root / ("inherit" if inherit else "no-inherit")
            shutil.copytree(source, destination, symlinks=True)
            arguments = [] if inherit else ["--no-inherit-permissions"]
            driver.cli_success("build-finish", *arguments, str(destination))
            driver.evidence.append({
                "observation": "public-build-metadata",
                "data": (destination / "metadata").read_text(),
            })
            metadata = _metadata(destination)
            driver.check(("network" in _list(metadata, "Context", "shared")) == inherit,
                         f"runtime network inheritance differs with inherit={inherit}")
        return
    tree = _tree(driver, fixture)
    if name == "build-finish-invalid":
        empty = driver.root / "uninitialized"
        empty.mkdir()
        result = driver.cli_call("build-finish", str(empty))
        driver.check(result.returncode != 0 and bool(result.stderr),
                     "uninitialized build-finish must fail with a diagnostic")
        # A separately constructed finalized input avoids using finish as its own setup.
        (tree / "export").mkdir()
        result = driver.cli_call("build-finish", str(tree))
        driver.check(result.returncode != 0 and bool(result.stderr),
                     "already-finalized build-finish must fail with a diagnostic")
        return
    options: list[str] = []
    if name == "build-finish-context":
        options = ["--share=network", "--unshare=ipc", "--socket=wayland", "--nosocket=x11",
                   "--device=dri", "--nodevice=kvm", "--allow=devel", "--disallow=multiarch",
                   "--filesystem=xdg-download:ro", "--filesystem=~/created:create",
                   "--nofilesystem=home", "--persist=.blackbox", "--env=BB_VALUE=two=parts",
                   "--unset-env=BB_REMOVE", "--own-name=org.example.Own",
                   "--talk-name=org.example.Talk", "--system-own-name=org.example.SystemOwn",
                   "--system-talk-name=org.example.SystemTalk"]
    elif name == "build-finish-metadata":
        with (tree / "metadata").open("a") as stream:
            stream.write("\n[Extension org.example.Remove]\ndirectory=old\n")
        options = ["--command=chosen-command", "--require-version=1.12.0",
                   "--runtime=org.example.Platform", "--sdk=org.example.Sdk",
                   "--metadata=Build Test=enabled", "--metadata=Build Test=disabled=false",
                   "--metadata=Build Test=text=literal=value",
                   "--extension=org.example.Extension=directory=extensions/test",
                   "--extension=org.example.Extension=no-autodownload=true",
                   "--extension=org.example.Extension=autodelete=false",
                   "--remove-extension=org.example.Remove"]
    elif name == "build-finish-policy":
        with (tree / "metadata").open("a") as stream:
            stream.write("\n[Policy test]\nvalues=old;keep;\n")
        options = ["--add-policy=test.values=new", "--remove-policy=test.values=old"]
    elif name == "build-finish-usb":
        query_file = driver.root / "usb-list"
        query_file.write_text("# ignored comment\nvnd:1234\n!vnd:2345\n")
        options = ["--usb=vnd:0123+dev:4567", "--nousb=cls:03:*",
                   "--usb-list=vnd:3456;!vnd:4567", f"--usb-list-file={query_file}"]
    elif name == "build-finish-conditional":
        options = ["--share-if=network:has-wayland", "--socket-if=x11:!has-wayland",
                   "--device-if=input:has-input-device", "--allow-if=devel:false"]
    elif name == "build-finish-extra-data":
        options = [f"--extra-data=payload:{'a' * 64}:23:47:https://example.invalid/payload"]
    elif name == "build-finish-extension-priority":
        with (tree / "metadata").open("a") as stream:
            stream.write("\n[ExtensionOf]\nref=app/org.example.Base/x86_64/test\npriority=0\n")
        options = ["--extension-priority=42"]
    elif name in ("build-finish-exports", "build-finish-no-exports"):
        app = fixture["app"]
        entries = {
            f"share/applications/{app}.desktop":
                "[Desktop Entry]\nType=Application\nName=Blackbox\nExec=blackbox-probe\n"
                f"Icon={app}\n",
            f"share/dbus-1/services/{app}.service":
                f"[D-BUS Service]\nName={app}\nExec=/app/bin/blackbox-probe\n",
            f"share/icons/hicolor/scalable/apps/{app}.svg":
                '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
                '<rect width="64" height="64" fill="red"/></svg>\n',
            f"share/metainfo/{app}.metainfo.xml":
                f'<component type="desktop-application"><id>{app}</id><name>Blackbox</name>'
                '<summary>Build fixture</summary><metadata_license>CC0-1.0</metadata_license>'
                '<project_license>MIT</project_license></component>\n',
        }
        for relative, content in entries.items():
            path = tree / "files" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        if name == "build-finish-no-exports":
            options = ["--no-exports"]
    driver.cli_success("build-finish", *options, str(tree))
    driver.evidence.append({"observation": "public-build-metadata",
                            "data": (tree / "metadata").read_text()})
    meta = _metadata(tree)
    if name == "build-finish-context":
        for key, expected in {
            "shared": {"network", "!ipc"}, "sockets": {"wayland", "!x11"},
            "devices": {"dri", "!kvm"}, "features": {"devel", "!multiarch"},
            "filesystems": {"xdg-download:ro", "~/created:create", "!home"},
            "persistent": {".blackbox"}, "unset-environment": {"BB_REMOVE"},
        }.items():
            driver.check(_list(meta, "Context", key) == expected,
                         f"Context {key}: expected {expected}, got {_list(meta, 'Context', key)}")
        driver.check(meta.get("Environment", "BB_VALUE", fallback=None) == "two=parts",
                     "environment value changed")
        for group, values in {
            "Session Bus Policy": {"org.example.Own": "own", "org.example.Talk": "talk"},
            "System Bus Policy": {"org.example.SystemOwn": "own", "org.example.SystemTalk": "talk"},
        }.items():
            for key, value in values.items():
                driver.check(meta.get(group, key, fallback=None) == value,
                             f"{group} {key} must be {value}")
    elif name == "build-finish-metadata":
        for key, expected_value in {
            "command": "chosen-command", "required-flatpak": "1.12.0",
            "runtime": f"org.example.Platform/{fixture['arch']}/{fixture['branch']}",
            "sdk": f"org.example.Sdk/{fixture['arch']}/{fixture['branch']}",
        }.items():
            driver.check(meta.get("Application", key, fallback=None) == expected_value,
                         f"Application {key} differs")
        driver.check(meta.getboolean("Build Test", "enabled", fallback=None) is True,
                     "implicit metadata boolean not true")
        driver.check(meta.getboolean("Build Test", "disabled", fallback=None) is False,
                     "explicit false not preserved")
        driver.check(meta.get("Build Test", "text", fallback=None) == "literal=value",
                     "generic string differs")
        group = "Extension org.example.Extension"
        driver.check(meta.get(group, "directory", fallback=None) == "extensions/test",
                     "extension directory differs")
        driver.check(meta.getboolean(group, "no-autodownload", fallback=None) is True,
                     "extension true differs")
        driver.check(meta.getboolean(group, "autodelete", fallback=None) is False,
                     "extension false differs")
        driver.check("Extension org.example.Remove" not in meta, "removed extension remains")
    elif name == "build-finish-policy":
        driver.check(_list(meta, "Policy test", "values") == {"keep", "new", "!old"},
                     "generic policy addition/removal was not recorded")
    elif name == "build-finish-usb":
        driver.check(_list(meta, "USB Devices", "enumerable-devices") ==
                     {"vnd:0123+dev:4567", "vnd:1234", "vnd:3456"}, "USB allow queries differ")
        driver.check(_list(meta, "USB Devices", "hidden-devices") ==
                     {"cls:03:*", "vnd:2345", "vnd:4567"}, "USB deny queries differ")
    elif name == "build-finish-conditional":
        for key, value in {"shared": "network:has-wayland", "sockets": "x11:!has-wayland",
                           "devices": "input:has-input-device", "features": "devel:false"}.items():
            driver.check(_list(meta, "Context", key) == {value.split(":")[0], f"if:{value}"},
                         f"conditional {key} differs: {_list(meta, 'Context', key)}")
    elif name == "build-finish-extra-data":
        group = "Extra Data"
        driver.check(meta.has_section(group), "extra-data metadata section absent")
        uris = [key for key in meta[group] if key.startswith("uri")]
        driver.check(len(uris) == 1, "expected exactly one extra-data URI")
        suffix = uris[0][3:]
        for key, expected_text in {"name": "payload", "checksum": "a" * 64,
                                   "uri": "https://example.invalid/payload"}.items():
            driver.check(meta[group][key + suffix] == expected_text, f"extra data {key} differs")
        driver.check(meta.getint(group, "size" + suffix) == 23, "extra data download size differs")
        driver.check(meta.getint(group, "installed-size" + suffix) == 47,
                     "extra data install size differs")
    elif name == "build-finish-extension-priority":
        driver.check(meta.getint("ExtensionOf", "priority") == 42, "extension priority differs")
    elif name in ("build-finish-exports", "build-finish-no-exports"):
        for relative in entries:
            driver.check((tree / "export" / relative).is_file() == (name == "build-finish-exports"),
                         f"export selection differs for {relative}")


def _export(driver: Driver, fixture: FixtureManifest, name: str) -> None:
    runtime = name == "build-export-runtime"
    tree = _tree(driver, fixture, finished=True)
    repo = driver.root / "exported"
    (tree / "ignored-private-build-file").write_text("not distributable")
    options = ["--disable-sandbox", f"--arch={fixture['arch']}"]
    if runtime:
        # Application metadata makes --runtime, rather than metadata inference,
        # responsible for selecting both the ref kind and the payload directory.
        (tree / "usr").mkdir()
        (tree / "usr/marker").write_text("runtime marker")
        (tree / "files/marker").write_text("app marker")
        (tree / "files/app-only").write_text("not runtime content")
        control = driver.root / "app-export-control"
        driver.cli_success("build-export", *options, str(control), str(tree), fixture["branch"])
        observed = driver.root / "observed-app-control"
        _ostree(driver, control, "checkout", "--user-mode", _ref(fixture), str(observed))
        driver.check((observed / "files/marker").read_text() == "app marker" and
                     (observed / "files/app-only").is_file(),
                     "export without --runtime must select files")
        runtime_ref = _ref(fixture).replace("app/", "runtime/", 1)
        driver.check(runtime_ref not in _ostree(driver, control, "refs").splitlines(),
                     "export without --runtime created a runtime ref")
        options += ["--runtime"]
    elif name == "build-export-options":
        (tree / "files/keep.txt").write_text("included")
        (tree / "files/drop.txt").write_text("excluded")
        options += ["--subject=Build subject", "--body=Build body",
                    "--timestamp=2020-01-02T03:04:05Z",
                    "--exclude=*.txt", "--include=keep.txt", "--collection-id=org.example.Build",
                    "--end-of-life=Retired fixture", "--no-update-summary"]
    elif name == "build-export-alternate":
        (tree / "alternate").mkdir()
        (tree / "alternate/marker").write_text("alternate payload")
        (tree / "alternate.metadata").write_text((tree / "metadata").read_text().replace(
            "command=blackbox-probe", "command=alternate-command"))
        options += ["--files=alternate", "--metadata=alternate.metadata"]
    elif name == "build-export-signed":
        home = _key_home(driver, fixture)
        options += [f"--gpg-homedir={home}", f"--gpg-sign={fixture['build']['key_id']}",
                    "--end-of-life-rebase=org.example.Successor", "--update-appstream"]
    driver.cli_success("build-export", *options, str(repo), str(tree), fixture["branch"])
    ref = runtime_ref if runtime else _ref(fixture)
    checkout = driver.root / "observed-export"
    _ostree(driver, repo, "checkout", "--user-mode", ref, str(checkout))
    driver.check((checkout / "metadata").is_file(), "export must contain metadata")
    driver.check(not (checkout / "ignored-private-build-file").exists(), "build-only file exported")
    driver.check(not (checkout / "var").exists(), "build var directory exported")
    if runtime:
        driver.check((checkout / "files/marker").read_text() == "runtime marker",
                     "runtime export did not select usr contents")
        driver.check(not (checkout / "files/app-only").exists(), "app content leaked into runtime")
        driver.check(_ref(fixture) not in _ostree(driver, repo, "refs").splitlines(),
                     "runtime export created an app ref")
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "exported-runtime", str(repo))
        driver.cli_success("install", "--user", "--noninteractive", "exported-runtime", ref)
        driver.check(driver.cli_success("info", "--user", "--show-commit", ref) ==
                     _ostree(driver, repo, "rev-parse", ref), "installed export commit differs")
        location = Path(driver.cli_success("info", "--user", "--show-location", ref))
        driver.check((location / "files/marker").read_text() == "runtime marker" and
                     not (location / "files/app-only").exists(),
                     "installed runtime does not contain only the selected payload")
    elif name == "build-export-alternate":
        driver.check((checkout / "files/marker").is_file() and
                     (checkout / "files/marker").read_text() == "alternate payload",
                     "alternate files not selected")
        driver.check(not (checkout / "files/bin/blackbox-probe").exists(), "default files leaked")
        driver.check(_metadata(checkout)["Application"]["command"] == "alternate-command",
                     "alternate metadata not selected")
    else:
        driver.check((checkout / "files/bin/blackbox-probe").read_bytes() ==
                     (tree / "files/bin/blackbox-probe").read_bytes(), "app bytes differ")
        driver.check((checkout / "export").is_dir(), "export subtree missing")
    if name == "build-export-options":
        driver.check((checkout / "files/keep.txt").is_file() and
                     (checkout / "files/keep.txt").read_text() == "included", "include lost")
        driver.check(not (checkout / "files/drop.txt").exists(), "exclude ignored")
        shown = _ostree(driver, repo, "show", ref)
        for text in ("Build subject", "Build body", "2020-01-02 03:04:05"):
            driver.check(text in shown, f"commit missing {text}: {shown}")
        driver.check("Retired fixture" in _ostree(driver, repo, "show",
                     "--print-metadata-key=ostree.endoflife", ref), "EOL message differs")
        driver.check(_ostree(driver, repo, "config", "get", "core.collection-id") ==
                     "org.example.Build", "collection ID differs")
        driver.check(not (repo / "summary").exists(), "--no-update-summary created summary")
    elif name == "build-export-signed":
        _verify_signature(driver, fixture, repo, ref)
        rebase = _ostree(driver, repo, "show", "--print-metadata-key=ostree.endoflife-rebase", ref)
        driver.check(rebase.strip("'") ==
                     f"app/org.example.Successor/{fixture['arch']}/{fixture['branch']}",
                     "export rebase destination differs")
        driver.check(f"appstream2/{fixture['arch']}" in _ostree(driver, repo, "refs").splitlines(),
                     "export did not update AppStream branch")


def _init(driver: Driver, fixture: FixtureManifest, url: str, name: str) -> None:
    _install_runtime(driver, fixture, url)
    tree = driver.root / "initialized"
    options = [f"--arch={fixture['arch']}"]
    if name == "build-init-options":
        options += ["--writable-sdk", "--sdk-dir=custom-sdk", "--tag=first", "--tag=second",
                    "--extension=org.example.Tools=directory=tools"]
    elif name == "build-init-metadata":
        options += ["--tag=first", "--tag=second",
                    "--extension=org.example.Tools=directory=tools"]
    elif name == "build-init-base":
        driver.cli_success("install", "--user", "--noninteractive", "build-fixture", _ref(fixture))
        options += [f"--base={fixture['app']}", f"--base-version={fixture['branch']}"]
    args = [str(tree), "org.example.Build", fixture["runtime"], fixture["runtime"],
            fixture["branch"]]
    if name == "build-init-existing":
        independent = _tree(driver, fixture)
        args[0] = str(independent)
        before = (independent / "metadata").read_bytes()
        result = driver.cli_call("build-init", *args)
        driver.check(result.returncode != 0 and bool(result.stderr), "reinitialization must fail")
        driver.check((independent / "metadata").read_bytes() == before,
                     "failed init changed metadata")
        return
    driver.cli_success("build-init", *options, *args)
    meta = _metadata(tree)
    driver.check(meta["Application"]["name"] == "org.example.Build", "build app name differs")
    for key in ("runtime", "sdk"):
        driver.check(meta["Application"][key] ==
                     f"{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}",
                     f"{key} differs")
    driver.check((tree / "files").is_dir() and (tree / "var").is_dir(), "build layout missing")
    if name == "build-init-layout":
        driver.check(not list((tree / "files").iterdir()), "initial files must be empty")
        driver.check({path.name for path in (tree / "var").iterdir()} == {"tmp", "run"},
                     "initial var must contain only tmp and run")
        temporary = tree / "var/tmp"
        driver.check(temporary.is_dir() and not temporary.is_symlink() and
                     not list(temporary.iterdir()), "initial var/tmp must be an empty directory")
        run = tree / "var/run"
        driver.check(run.is_symlink() and run.readlink() == Path("/run"),
                     "initial var/run must be a symlink to /run")
    elif name == "build-init-options":
        driver.check((tree / "custom-sdk/bin/ldconfig").is_file(), "custom writable SDK absent")
        driver.check(_list(meta, "Application", "tags") == {"first", "second"}, "tags differ")
        driver.check(meta.get("Extension org.example.Tools", "directory", fallback=None) == "tools",
                     "extension differs")
        (tree / "custom-sdk/unwanted").write_text("remove on update")
        driver.cli_success("build-init", "--update", *options, *args)
        driver.check(not (tree / "custom-sdk/unwanted").exists(), "--update did not refresh SDK")
    elif name == "build-init-base":
        source = driver.root / "base-checkout"
        _ostree(driver, Path(fixture["directory"]) / "A", "checkout", "--user-mode",
                _ref(fixture), str(source))
        driver.check((tree / "files/bin/blackbox-probe").read_bytes() ==
                     (source / "files/bin/blackbox-probe").read_bytes(), "base bytes differ")
    elif name == "build-init-metadata":
        driver.check(_list(meta, "Application", "tags") == {"first", "second"}, "tags differ")
        driver.check(meta.get("Extension org.example.Tools", "directory", fallback=None) == "tools",
                     "extension directory differs")


def _bundle(driver: Driver, fixture: FixtureManifest, url: str, name: str) -> None:
    root = Path(fixture["directory"])
    bundle = driver.root / "result.flatpak"
    runtime = name == "build-bundle-runtime"
    if name == "build-import":
        if "build" not in fixture:
            from run import PrerequisiteError
            raise PrerequisiteError("prepare_build.prepare must supply the independent bundle")
        bundle = root / fixture["build"]["bundle"]
    else:
        options = [f"--arch={fixture['arch']}"]
        if runtime:
            options += ["--runtime"]
        if name == "build-bundle-origin":
            options += [f"--repo-url={url}"]
        driver.cli_success("build-bundle", *options, str(root / "A"), str(bundle),
                           fixture["runtime" if runtime else "app"], fixture["branch"])
        driver.check(bundle.is_file() and bundle.stat().st_size > 0, "bundle missing or empty")
    if name == "build-import":
        destination = driver.root / "imported"
        _ostree(driver, destination, "init", "--mode=archive")
        driver.cli_success("build-import-bundle", str(destination), str(bundle))
        driver.check(_ostree(driver, destination, "rev-parse", _ref(fixture)) ==
                     fixture["commits"]["A"], "imported app commit differs")
        _ostree(driver, destination, "fsck")
    else:
        if not runtime:
            _install_runtime(driver, fixture, url)
        driver.cli_success("install", "--user", "--noninteractive", "--bundle", str(bundle))
        commit = driver.cli_success("info", "--user", "--show-commit", _ref(fixture, runtime))
        driver.check(commit == (fixture["runtime_commit"] if runtime else fixture["commits"]["A"]),
                     "bundle installed wrong commit")
        if name == "build-bundle-origin":
            origin = driver.cli_success("info", "--user", "--show-origin", _ref(fixture))
            remotes = driver.cli_success("remotes", "--user", "--columns=name,url")
            driver.check([origin, url] in [line.split("\t") for line in remotes.splitlines()],
                         "bundle update origin URL differs")


def _signing(driver: Driver, fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    if "build" not in fixture:
        raise PrerequisiteError("prepare_build.prepare must supply disposable signing material")
    inputs = fixture["build"]
    root = Path(fixture["directory"])
    home = _key_home(driver, fixture)
    runtime = name == "build-sign-runtime"
    ref = _ref(fixture, runtime)
    if name.startswith("build-sign"):
        repo = _copy_repo(driver, fixture)
        original = _ostree(driver, repo, "rev-parse", ref)
        options = ["--runtime"] if runtime else []
        driver.cli_success("build-sign", *options, f"--gpg-homedir={home}",
                           f"--gpg-sign={inputs['key_id']}", str(repo),
                           fixture["runtime" if runtime else "app"], fixture["branch"])
        driver.check(_ostree(driver, repo, "rev-parse", ref) == original,
                     "signing must not change the commit checksum")
        _verify_signature(driver, fixture, repo, ref)
        return
    source = root / inputs["signed_repo"]
    repo = driver.root / "promoted"
    _ostree(driver, repo, "init", "--mode=archive")
    destination = _ref(fixture, branch="promoted")
    driver.cli_success("build-commit-from", f"--src-repo={source}", f"--src-ref={ref}",
                       "--subject=Promoted subject", "--body=Promoted body",
                       "--timestamp=2020-01-02T03:04:05Z", "--no-update-summary",
                       str(repo), destination)
    source_tree = driver.root / "source-tree"
    destination_tree = driver.root / "destination-tree"
    _ostree(driver, source, "checkout", "--user-mode", ref, str(source_tree))
    _ostree(driver, repo, "checkout", "--user-mode", destination, str(destination_tree))
    driver.check(_digest_tree(source_tree) == _digest_tree(destination_tree),
                 "promoted commit contents differ from source")
    shown = _ostree(driver, repo, "show", destination)
    driver.check("Parent:" not in shown, "source history was imported")
    for text in ("Promoted subject", "Promoted body", "2020-01-02 03:04:05"):
        driver.check(text in shown, f"promoted commit missing {text}")
    driver.check(not (repo / "summary").exists(), "summary updated despite option")
    commit = _ostree(driver, repo, "rev-parse", destination)
    driver.check(not (repo / "objects" / commit[:2] / f"{commit[2:]}.commitmeta").exists(),
                 "source detached signatures were imported")


def _digest_tree(tree: Path) -> dict[str, str]:
    return {str(path.relative_to(tree)): (f"symlink:{path.readlink()}" if path.is_symlink()
            else hashlib.sha256(path.read_bytes()).hexdigest())
            for path in tree.rglob("*") if path.is_file() or path.is_symlink()}


def _repository(driver: Driver, fixture: FixtureManifest, name: str) -> None:
    repo = _copy_repo(driver, fixture, "B")
    ref = _ref(fixture)
    if name == "build-repo-deltas":
        driver.check(_ostree(driver, repo, "static-delta", "list") in ("", "(No static deltas)"),
                     "independent fixture must start without static deltas")
        driver.cli_success("build-update-repo", "--generate-static-deltas",
                           f"--static-delta-ignore-ref={fixture['runtime']}", str(repo))
        deltas = _ostree(driver, repo, "static-delta", "list").splitlines()
        driver.check(any(fixture["commits"]["B"] in item for item in deltas),
                     "no delta targets current app commit")
        driver.check(not any(fixture["runtime_commit"] in item for item in deltas),
                     "ignored runtime acquired a delta")
        return
    if name == "build-repo-inspect":
        branches = driver.cli_success("repo", "--branches", str(repo))
        driver.check(ref in branches and _ref(fixture, True) in branches, "repo branches missing")
        meta = _parse(driver.cli_success("repo", f"--metadata={ref}", str(repo)))
        driver.check(meta["Application"]["name"] == fixture["app"], "repo metadata app differs")
        commits = driver.cli_success("repo", f"--commits={ref}", str(repo))
        driver.check(fixture["commits"]["B"] in commits, "repo commits missing head")
        combined = driver.cli_success("repo", "--info", "--branches", str(repo))
        driver.check("Repo mode: archive-z2" in combined and ref in combined,
                     "--info must add repository mode alongside explicitly selected branches")
        return
    if name == "build-repo-prune":
        history = driver.root / "history-repository"
        shutil.copytree(repo, history)
        # Drop the app ref independently; runtime remains rooted. Both snapshots are public inputs.
        _ostree(driver, repo, "refs", "--delete", ref)
        before = {path.relative_to(repo) for path in (repo / "objects").rglob("*")
                  if path.is_file()}
        driver.cli_success("build-update-repo", "--prune", "--prune-depth=0", str(repo))
        after = {path.relative_to(repo) for path in (repo / "objects").rglob("*") if path.is_file()}
        driver.check(bool(before - after), "prune removed no unreachable objects")
        driver.check(_ostree(driver, repo, "rev-parse", _ref(fixture, True)) ==
                     fixture["runtime_commit"], "prune damaged reachable runtime")
        _ostree(driver, repo, "fsck")
        parent = fixture["commits"]["A"]
        parent_object = history / "objects" / parent[:2] / f"{parent[2:]}.commit"
        driver.check(parent_object.is_file(), "reference B history must contain A")
        driver.cli_success("build-update-repo", "--prune", "--prune-depth=0", str(history))
        driver.check(not parent_object.exists(), "depth zero retained the old app commit")
        driver.check(_ostree(driver, history, "rev-parse", ref) == fixture["commits"]["B"],
                     "depth pruning changed current app ref")
        _ostree(driver, history, "fsck")
        return
    (repo / "summary").unlink(missing_ok=True)
    options = ["--title=Build repository", "--comment=Build comment",
               "--description=Build description", "--homepage=https://example.invalid/home",
               "--icon=https://example.invalid/icon", "--default-branch=stable"]
    driver.cli_success("build-update-repo", *options, str(repo))
    driver.check((repo / "summary").is_file(), "repository summary not generated")
    driver.cli_success("remote-add", "--user", "--no-gpg-verify", "export-observer", str(repo))
    refs = driver.cli_success("remote-ls", "--user", "--columns=ref", "export-observer")
    driver.check({ref, _ref(fixture, True)} <= set(refs.splitlines()), "summary refs missing")
    info = driver.cli_success("repo", "--info", str(repo))
    for text in ("Build repository", "Build comment", "Build description",
                 "https://example.invalid/home", "https://example.invalid/icon", "stable"):
        driver.check(text in info, f"repository info missing option value {text}")


def _usb(driver: Driver, fixture: FixtureManifest) -> None:
    from run import Driver, PrerequisiteError

    if "usb_repo" not in fixture.get("build", {}):
        raise PrerequisiteError("prepare_build must supply signed collection-ID repository")
    inputs = fixture["build"]
    source = Path(fixture["directory"]) / inputs["usb_repo"]
    key = Path(fixture["directory"]) / inputs["public_key"]
    collection = inputs["collection_id"]
    driver.cli_success("remote-add", "--user", f"--collection-id={collection}",
                       f"--gpg-import={key}", "usb-origin", str(source))
    driver.cli_success("install", "--user", "--noninteractive", "usb-origin", _ref(fixture))
    mount = driver.root / "usb-mount"
    mount.mkdir()
    driver.cli_success("create-usb", "--user", "--app", "--destination-repo=payload",
                       str(mount), fixture["app"])
    exported = mount / "payload"
    driver.check(exported.is_dir(), "custom USB repository missing")
    links = list((mount / ".ostree/repos.d").iterdir())
    driver.check(any(path.is_symlink() and path.resolve() == exported for path in links),
                 "USB discovery symlink does not resolve to selected destination")
    _ostree(driver, exported, "fsck")
    # A fresh public user installation makes cached source objects unavailable.
    environment = {**driver.env, "FLATPAK_USER_DIR": str(driver.root / "offline-user")}
    destination = Driver("cli", driver.cli, None, environment, driver.root,
                         driver.evidence, driver.timeout)
    destination.cli_success("remote-add", "--user", f"--collection-id={collection}",
                            f"--gpg-import={key}", "usb-origin", str(source))
    destination.cli_success("remote-modify", "--user",
                            "--url=file:///blackbox-intentionally-unavailable", "usb-origin")
    driver.check(destination.cli_success("list", "--user", "--columns=ref") == "",
                 "offline destination is not empty")
    destination.cli_success("install", "--user", "--noninteractive",
                            f"--sideload-repo={exported}", "usb-origin", _ref(fixture))
    for runtime, kind in ((False, "app"), (True, "runtime")):
        commit = destination.cli_success("info", "--user", "--show-commit", _ref(fixture, runtime))
        driver.check(commit == inputs["usb_commits"][kind], f"offline {kind} commit differs")


def _build(driver: Driver, fixture: FixtureManifest, url: str, name: str) -> None:
    from run import PrerequisiteError

    if "assets" not in fixture:
        raise PrerequisiteError("build execution needs parent fixture's file/env capable probe")
    _install_runtime(driver, fixture, url)
    tree = _tree(driver, fixture)
    probe = "/usr/bin/blackbox-probe"
    if name == "build-artifacts":
        for mount, relative in (("app", "files"), ("var/lib", "var/lib"), ("var/tmp", "var/tmp")):
            payload = f"persistent {mount} artifact"
            driver.cli_success("build", str(tree), probe, "write", f"/{mount}/artifact", payload)
            driver.check((tree / relative / "artifact").is_file(),
                         f"documented /{mount} write is absent from build {relative}/artifact")
            driver.check((tree / relative / "artifact").read_text() == payload,
                         f"{mount} write did not reach public build tree")
            output = driver.cli_success("build", str(tree), probe, "read", f"/{mount}/artifact")
            driver.check(output == payload, f"{mount} artifact did not survive a second command")
        driver.cli_success("build", str(tree), probe, "write", "/var/artifact", "transient")
        driver.check(not (tree / "var/artifact").exists(),
                     "nonpersistent /var write reached the build tree")
        result = driver.cli_call("build", str(tree), probe, "read", "/var/artifact")
        driver.check(result.returncode != 0, "/var artifact survived a second command")
    elif name in ("build-readonly", "build-readonly-app"):
        destinations = [("app", "files", True)]
        if name == "build-readonly":
            destinations.extend((("var/lib", "var/lib", False), ("var/tmp", "var/tmp", False)))
        for mount, relative, readonly in destinations:
            path = tree / relative / "artifact"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("original")
            observed = driver.cli_success("build", "--readonly", str(tree), probe,
                                          "read", f"/{mount}/artifact")
            driver.check(observed == "original", f"readonly control cannot read {mount} artifact")
            result = driver.cli_call("build", "--readonly", str(tree), probe,
                                     "write", f"/{mount}/artifact", "changed")
            if readonly:
                driver.check(result.returncode != 0, f"readonly {mount} unexpectedly writable")
                driver.check(path.read_text() == "original", f"readonly {mount} changed")
            else:
                driver.check(result.returncode == 0,
                             f"--readonly unexpectedly blocked {mount} write")
                driver.check(path.read_text() == "changed",
                             f"--readonly {mount} write did not persist")
    elif name == "build-command-options":
        mounted_input = driver.root / "mounted-input"
        mounted_input.mkdir()
        (mounted_input / "marker").write_text("bound marker")
        options = [f"--bind-mount=/build-input={mounted_input}", "--build-dir=/build-input"]
        driver.check(driver.cli_success("build", *options, str(tree), probe,
                                        "read", "marker") == "bound marker",
                     "bind mount and build working directory did not select marker")
        driver.check(driver.cli_success("build", "--env=BB_BUILD=option value", str(tree),
                                        probe, "env", "BB_BUILD") == "option value",
                     "build environment option value differs")
    elif name == "build-runtime-selection":
        metadata = (tree / "metadata").read_text()
        metadata = metadata.replace(f"sdk={fixture['runtime']}", "sdk=org.example.MissingSDK")
        (tree / "metadata").write_text(metadata)
        failed = driver.cli_call("build", str(tree), probe)
        driver.check(failed.returncode != 0 and "org.example.MissingSDK" in failed.stderr,
                     "default build did not select missing SDK")
        driver.check(driver.cli_success("build", "--runtime", str(tree), probe) == "A",
                     "--runtime did not select the available non-devel runtime")


def _commit_options(driver: Driver, fixture: FixtureManifest, name: str) -> None:
    source = Path(fixture["directory"]) / "B"
    ref = _ref(fixture)
    if name == "build-option-force":
        for force in (False, True):
            repo = driver.root / f"force-{force}"
            shutil.copytree(source, repo)
            args = ["--force"] if force else []
            driver.cli_success("build-commit-from", *args, f"--src-ref={ref}",
                               "--timestamp=2020-02-03T04:05:06Z",
                               str(repo), ref)
            actual = _ostree(driver, repo, "rev-parse", ref)
            driver.check((actual != fixture["commits"]["B"]) == force,
                         "force must create a commit for unchanged content, unlike control")
        return
    if name == "build-option-untrusted":
        source = _copy_repo(driver, fixture, "B")
        listing = _ostree(driver, source, "ls", "--checksum", ref, "/files/bin/blackbox-probe")
        checksums = re.findall(r"\b[0-9a-f]{64}\b", listing)
        driver.check(len(checksums) == 1, "expected one payload checksum from public tree listing")
        checksum = checksums[0]
        payload = source / "objects" / checksum[:2] / f"{checksum[2:]}.filez"
        replacement = next(path for path in (source / "objects").rglob("*.filez")
                           if path != payload)
        payload.write_bytes(replacement.read_bytes())
        for untrusted in (False, True):
            repo = driver.root / f"trust-{untrusted}"
            _ostree(driver, repo, "init", "--mode=archive")
            args = ["--untrusted"] if untrusted else []
            result = driver.cli_call("build-commit-from", *args, f"--src-repo={source}",
                                     str(repo), ref)
            driver.check((result.returncode != 0) == untrusted,
                         f"only untrusted pull must reject corrupted payload: {result.stderr}")
            if untrusted:
                driver.check("checksum" in result.stderr.lower(), "unrelated untrusted rejection")
        return
    repo = driver.root / "promoted-options"
    _ostree(driver, repo, "init", "--mode=archive")
    home = _key_home(driver, fixture)
    driver.cli_success("build-commit-from", f"--src-repo={source}",
                       "--extra-collection-id=org.example.Extra", "--subset=qa",
                       "--end-of-life=Retired promotion",
                       f"--end-of-life-rebase={fixture['app']}=org.example.Successor",
                       f"--gpg-homedir={home}", f"--gpg-sign={fixture['build']['key_id']}",
                       "--update-appstream", str(repo), ref)
    _verify_signature(driver, fixture, repo, ref)
    for key, value in {"xa.subsets": "qa", "ostree.endoflife": "Retired promotion",
                        "ostree.endoflife-rebase":
                        f"app/org.example.Successor/{fixture['arch']}/{fixture['branch']}"}.items():
        actual_value = _ostree(driver, repo, "show", f"--print-metadata-key={key}", ref)
        driver.check(value in actual_value, f"promoted {key} differs: {actual_value}")
    raw = _ostree(driver, repo, "show", "--raw", ref)
    driver.check(f"('org.example.Extra', '{ref}')" in raw, "extra collection/ref binding absent")
    driver.check(f"appstream2/{fixture['arch']}" in _ostree(driver, repo, "refs").splitlines(),
                 "promotion did not create AppStream branch")


def _import_options(driver: Driver, fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    root = Path(fixture["directory"])
    repo = driver.root / "import-options"
    _ostree(driver, repo, "init", "--mode=archive")
    ref = _ref(fixture)
    if name == "build-option-import-oci":
        if "build_options" not in fixture:
            raise PrerequisiteError("prepare_build.prepare_options must supply reference OCI image")
        ref = fixture["build_options"]["oci_ref"]
        image = root / fixture["build_options"]["oci"]
        driver.cli_success("build-import-bundle", "--oci", f"--ref={ref}", str(repo), str(image))
        driver.check(ref in _ostree(driver, repo, "refs").splitlines(), "OCI ref override ignored")
        driver.check(_ref(fixture) not in _ostree(driver, repo, "refs").splitlines(),
                     "original OCI ref unexpectedly imported")
        checkout = driver.root / "imported-oci"
        _ostree(driver, repo, "checkout", "--user-mode", ref, str(checkout))
        original = driver.root / "original-oci"
        _ostree(driver, root / "B", "checkout", "--user-mode", _ref(fixture), str(original))
        driver.check((checkout / "files/bin/blackbox-probe").read_bytes() ==
                     (original / "files/bin/blackbox-probe").read_bytes(), "OCI payload differs")
        return
    home = _key_home(driver, fixture)
    driver.cli_success("build-import-bundle", "--no-update-summary", "--update-appstream",
                       f"--gpg-homedir={home}", f"--gpg-sign={fixture['build']['key_id']}",
                       str(repo), str(root / fixture["build"]["bundle"]))
    driver.check(not (repo / "summary").exists(), "import updated summary despite suppression")
    driver.check(f"appstream2/{fixture['arch']}" in _ostree(driver, repo, "refs").splitlines(),
                 "import did not generate AppStream branch")
    _verify_signature(driver, fixture, repo, ref)


def _image_options(driver: Driver, fixture: FixtureManifest, name: str) -> None:
    source = Path(fixture["directory"]) / "B"
    if name == "build-option-delta-bundle":
        bundle = driver.root / "delta.flatpak"
        driver.cli_success("build-bundle", f"--from-commit={fixture['commits']['A']}",
                           str(source), str(bundle), fixture["app"], fixture["branch"])
        from run import execute

        empty = driver.root / "without-base"
        _ostree(driver, empty, "init", "--mode=archive")
        command = ["ostree", f"--repo={empty}", "static-delta", "apply-offline", str(bundle)]
        result = execute(command,
                         driver.env, driver.root, driver.evidence, driver.timeout)
        driver.check(result.returncode != 0 and fixture["commits"]["A"] in result.stderr,
                     f"delta must require exact A base: {result.stderr}")
        destination = _copy_repo(driver, fixture, "A")
        _ostree(driver, destination, "static-delta", "apply-offline", str(bundle))
        _ostree(driver, destination, "show", fixture["commits"]["B"])
        return
    image = driver.root / "image"
    driver.cli_success("build-bundle", "--oci", "--oci-layer-compress=zstd", str(source),
                       str(image), fixture["app"], fixture["branch"])
    driver.check(image.is_dir(), "OCI export must produce an image layout directory")
    layout = json.loads((image / "oci-layout").read_text())
    driver.check(layout["imageLayoutVersion"] == "1.0.0", "OCI layout version differs")
    index = json.loads((image / "index.json").read_text())

    def blob(digest: str) -> Path:
        algorithm, checksum = digest.split(":")
        driver.check(algorithm == "sha256", "unexpected OCI digest algorithm")
        path = image / "blobs" / algorithm / checksum
        driver.check(hashlib.sha256(path.read_bytes()).hexdigest() == checksum,
                     "OCI blob content differs from descriptor digest")
        return path

    manifest = json.loads(blob(index["manifests"][0]["digest"]).read_text())
    driver.check(bool(manifest["layers"]), "OCI image contains no layers")
    for layer in manifest["layers"]:
        driver.check(layer["mediaType"].endswith("+zstd"), "nondefault zstd media type absent")
        driver.check(blob(layer["digest"]).read_bytes().startswith(bytes.fromhex("28b52ffd")),
                     "OCI layer lacks zstd frame magic")


def _architecture_options(driver: Driver, fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError

    inputs = fixture.get("build_options", {})
    if "arch" not in inputs:
        raise PrerequisiteError("prepare_options must supply a nondefault supported architecture")
    arch = inputs["arch"]
    driver.check(arch != fixture["arch"], "architecture oracle must differ from native default")
    source = Path(fixture["directory"]) / inputs["arch_repo"]
    foreign = f"app/{fixture['app']}/{arch}/{fixture['branch']}"
    if name == "build-option-arch-bundle":
        bundle = driver.root / "foreign.flatpak"
        driver.cli_success("build-bundle", f"--arch={arch}", str(source), str(bundle),
                           fixture["app"], fixture["branch"])
        target = driver.root / "bundle-inspector"
        _ostree(driver, target, "init", "--mode=archive")
        _ostree(driver, target, "static-delta", "apply-offline", str(bundle))
        _ostree(driver, target, "show", inputs["arch_commits"]["app"])
    elif name == "build-option-arch-sign":
        repo = driver.root / "arch-signatures"
        shutil.copytree(source, repo)
        home = _key_home(driver, fixture)
        driver.cli_success("build-sign", f"--arch={arch}", f"--gpg-homedir={home}",
                           f"--gpg-sign={fixture['build']['key_id']}", str(repo),
                           fixture["app"], fixture["branch"])
        _verify_signature(driver, fixture, repo, foreign)
    elif name == "build-option-arch-export":
        # Runtime metadata has no app runtime architecture to override the explicit selection.
        tree = _tree(driver, fixture, runtime=True, finished=True)
        repo = driver.root / "foreign-export"
        driver.cli_success("build-export", "--runtime", "--disable-sandbox", f"--arch={arch}",
                           str(repo), str(tree), fixture["branch"])
        refs = _ostree(driver, repo, "refs").splitlines()
        driver.check(f"runtime/{fixture['runtime']}/{arch}/{fixture['branch']}" in refs and
                     _ref(fixture, True) not in refs,
                     "export used native rather than requested arch")
    else:
        legacy = driver.root / "legacy-architectures"
        shutil.copytree(source, legacy)
        (legacy / "summary.idx").unlink(missing_ok=True)
        _ostree(driver, legacy, "summary", "--update")
        source = legacy
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "architectures", str(source))
        driver.cli_success("install", "--user", "--noninteractive", "architectures",
                           _ref(fixture, True))
        driver.cli_success("install", "--user", "--noninteractive", f"--arch={arch}",
                           "architectures",
                           f"runtime/{fixture['runtime']}/{arch}/{fixture['branch']}")
        tree = driver.root / "foreign-init"
        driver.cli_success("build-init", f"--arch={arch}", str(tree), fixture["app"],
                           fixture["runtime"], fixture["runtime"], fixture["branch"])
        for key in ("runtime", "sdk"):
            driver.check(_metadata(tree)["Application"][key] ==
                         f"{fixture['runtime']}/{arch}/{fixture['branch']}",
                         "init used native rather than requested architecture")


def _build_more_options(driver: Driver, fixture: FixtureManifest, url: str, name: str) -> None:
    _install_runtime(driver, fixture, url)
    tree = _tree(driver, fixture)
    probe = "/usr/bin/blackbox-probe"
    if name == "build-option-sdk-dir":
        sdk = driver.root / "sdk-checkout"
        _ostree(driver, Path(fixture["directory"]) / "A", "checkout", "--user-mode",
                _ref(fixture, True), str(sdk))
        shutil.copytree(sdk / "files", tree / "selected-sdk", symlinks=True)
        (tree / "selected-sdk/selection").write_text("custom SDK marker")
        driver.check(driver.cli_call("build", str(tree), probe, "read", "/usr/selection").returncode
                     != 0, "default SDK unexpectedly has custom marker")
        driver.check(driver.cli_success("build", "--sdk-dir=selected-sdk", str(tree), probe,
                                        "read", "/usr/selection") == "custom SDK marker",
                     "SDK directory option ignored")
    elif name == "build-option-metadata":
        alternate = tree / "alternate.metadata"
        alternate.write_bytes((tree / "metadata").read_bytes())
        text = (tree / "metadata").read_text().replace(f"sdk={fixture['runtime']}",
                                                     "sdk=org.example.MissingSDK")
        (tree / "metadata").write_text(text)
        driver.check(driver.cli_call("build", str(tree), probe).returncode != 0,
                     "default metadata unexpectedly selects usable SDK")
        driver.check(driver.cli_success("build", "--metadata=alternate.metadata",
                                        str(tree), probe) == "A",
                     "alternate metadata not selected")
    elif name == "build-option-unset-env":
        setting = "--env=BB_REMOVE_BUILD=inherited sentinel"
        driver.check(driver.cli_success("build", setting, str(tree), probe,
                                        "env", "BB_REMOVE_BUILD") == "inherited sentinel",
                     "environment control missing")
        result = driver.cli_call("build", setting, "--unset-env=BB_REMOVE_BUILD", str(tree),
                                 probe, "env", "BB_REMOVE_BUILD")
        driver.check(result.returncode == 1 and result.stdout == "", "unset environment survived")
    elif name == "build-option-filesystem":
        directory = driver.root / "host-input"
        directory.mkdir()
        (directory / "marker").write_text("host marker")
        args = [str(tree), probe, "read", str(directory / "marker")]
        driver.check(driver.cli_call("build", *args).returncode != 0,
                     "host marker unexpectedly readable without filesystem grant")
        grant = f"--filesystem={directory}:ro"
        driver.check(driver.cli_success("build", grant, *args) == "host marker", "grant ignored")
        denied = driver.cli_call("build", grant, f"--nofilesystem={directory}", *args)
        driver.check(denied.returncode != 0, "filesystem denial did not override grant")


def _summary_options(driver: Driver, fixture: FixtureManifest, name: str) -> None:
    repo = _copy_repo(driver, fixture)
    collection = "org.example.SelectedCollection"
    if name == "build-option-collection":
        driver.cli_success("build-update-repo", f"--collection-id={collection}", str(repo))
        driver.check(_ostree(driver, repo, "config", "get", "core.collection-id") == collection,
                     "requested repository collection ID not stored")
        return
    if name in ("build-option-deploy-collection", "build-option-deploy-sideload"):
        _ostree(driver, repo, "config", "set", "core.collection-id", collection)
        sideload = name.endswith("sideload")
        flag = "--deploy-sideload-collection-id" if sideload else "--deploy-collection-id"
        key = "xa.deploy-collection-id" if sideload else "ostree.deploy-collection-id"
        driver.cli_success("build-update-repo", flag, str(repo))
        keys = _ostree(driver, repo, "summary", "--list-metadata-keys").splitlines()
        driver.check(key in keys, f"deployment key missing; available summary keys: {keys}")
        driver.check(_ostree(driver, repo, "summary", f"--print-metadata-key={key}").strip("'") ==
                     collection, "summary does not advertise requested collection rollout")
        return
    home = _key_home(driver, fixture)
    public = Path(fixture["directory"]) / fixture["build"]["public_key"]
    driver.cli_success("build-update-repo", f"--gpg-homedir={home}",
                       f"--gpg-sign={fixture['build']['key_id']}", f"--gpg-import={public}",
                       str(repo))
    inspector = driver.root / "summary-inspector"
    _ostree(driver, inspector, "init", "--mode=archive")
    _ostree(driver, inspector, "remote", "add", "--set=gpg-verify-summary=true",
            f"--gpg-import={public}", "signed", repo.as_uri())
    shown = _ostree(driver, inspector, "remote", "summary", "signed")
    driver.check(_ref(fixture) in shown, "verified signed summary lacks app ref")
    key_value = _ostree(driver, repo, "summary", "--print-metadata-key=xa.gpg-keys")
    key_bytes = bytes(int(value, 16) for value in re.findall(r"0x([0-9a-f]{2})", key_value))
    driver.check(key_bytes == public.read_bytes(), "advertised GPG material differs from import")


def _runtime_repo_bundle(driver: Driver, fixture: FixtureManifest) -> None:
    from run import RepositoryServer

    served = driver.root / "served"
    served.mkdir()
    inputs = fixture["build"]
    root = Path(fixture["directory"])
    shutil.copytree(root / inputs["usb_repo"], served / "runtime-repository")
    key = base64.b64encode((root / inputs["public_key"]).read_bytes()).decode("ascii")
    server = RepositoryServer(driver.root)
    server.version = "served"
    with server.serving() as address:
        (served / "runtime.flatpakrepo").write_text(
            f"[Flatpak Repo]\nTitle=Runtime supplier\nUrl={address}/runtime-repository\n"
            f"GPGKey={key}\n")
        bundle = driver.root / "runtime-location.flatpak"
        driver.cli_success("build-bundle", f"--runtime-repo={address}/runtime.flatpakrepo",
                           str(Path(fixture["directory"]) / "A"), str(bundle),
                           fixture["app"], fixture["branch"])
        result = driver.cli_call("install", "--user", "--assumeyes", "--bundle", str(bundle))
        driver.evidence.append({"observation": "runtime-repository-requests",
                                "data": json_value(server.requests)})
        driver.check(result.returncode == 0,
                     f"bundle dependency installation failed: {result.stderr}")
        driver.check(driver.cli_success("info", "--user", "--show-commit", _ref(fixture, True)) ==
                     inputs["usb_commits"]["runtime"],
                     "runtime descriptor did not provide dependency")
        driver.check(any(request["path"] == "/runtime.flatpakrepo" for request in server.requests),
                     "embedded runtime repository descriptor was not requested")


def _export_subset(driver: Driver, fixture: FixtureManifest) -> None:
    tree = _tree(driver, fixture, finished=True)
    repo = driver.root / "subset-export"
    driver.cli_success("build-export", "--disable-sandbox", "--subset=qa", str(repo),
                       str(tree), fixture["branch"])
    subset = _ostree(driver, repo, "show", "--print-metadata-key=xa.subsets", _ref(fixture))
    driver.check(subset == "['qa']", f"export subset differs: {subset}")


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    """Dispatch isolated cases; setup only consumes independent reference fixtures."""
    repository.version = "A"
    if name in ("build-option-force", "build-option-untrusted", "build-option-promotion"):
        _commit_options(driver, fixture, name)
    elif name.startswith("build-option-import-"):
        _import_options(driver, fixture, name)
    elif name in ("build-option-oci", "build-option-delta-bundle"):
        _image_options(driver, fixture, name)
    elif name.startswith("build-option-arch-"):
        _architecture_options(driver, fixture, name)
    elif name in ("build-option-summary-sign", "build-option-collection",
                  "build-option-deploy-collection", "build-option-deploy-sideload"):
        _summary_options(driver, fixture, name)
    elif name == "build-option-runtime-repo":
        _runtime_repo_bundle(driver, fixture)
    elif name == "build-option-export-subset":
        _export_subset(driver, fixture)
    elif name.startswith("build-option-"):
        _build_more_options(driver, fixture, url, name)
    elif name.startswith("build-finish-"):
        _finish(driver, fixture, name)
    elif name.startswith("build-export-"):
        _export(driver, fixture, name)
    elif name.startswith("build-init-"):
        _init(driver, fixture, url, name)
    elif name.startswith("build-bundle-") or name == "build-import":
        _bundle(driver, fixture, url, name)
    elif name.startswith("build-sign") or name == "build-commit-from":
        _signing(driver, fixture, name)
    elif name.startswith("build-repo-"):
        _repository(driver, fixture, name)
    elif name == "build-create-usb":
        _usb(driver, fixture)
    elif name in ("build-artifacts", "build-readonly", "build-readonly-app",
                  "build-command-options", "build-runtime-selection"):
        _build(driver, fixture, url, name)
    else:
        raise ValueError(f"unknown build scenario {name}")
