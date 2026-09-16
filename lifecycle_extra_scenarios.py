# SPDX-License-Identifier: LGPL-2.1-or-later
"""Additional public lifecycle contracts using independent exported artifacts."""

from __future__ import annotations

import configparser
import os
import selectors
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureLifecycleExtra, FixtureManifest

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError, RepositoryServer
    from sandbox_scenarios import _background

    root = Path(fixture["directory"])
    arch, branch = fixture["arch"], fixture["branch"]
    app = f"app/{fixture['app']}/{arch}/{branch}"
    runtime = f"runtime/{fixture['runtime']}/{arch}/{branch}"
    user = Path(driver.env.get("FLATPAK_USER_DIR",
                               str(Path(driver.env["XDG_DATA_HOME"]) / "flatpak")))
    values: dict[str, str] = {"ref": app, "commit": fixture["commits"]["A"]}

    def call(group: str, action: str = "check") -> None:
        path = driver.root / "lifecycle.ini"
        path.write_text("[lifecycle]\n" + "".join(
            f"{key}={value}\n" for key, value in values.items()))
        driver.success(f"lifex-{group}", str(path), action)

    def remote(path: Path, initial: bool = True) -> None:
        if initial:
            driver.cli_success("remote-add", "--user", "--no-gpg-verify",
                               "lifecycle", path.as_uri())
        else:
            driver.cli_success("remote-modify", "--user", f"--url={path.as_uri()}", "lifecycle")

    def install(*refs: str) -> None:
        driver.cli_success("install", "--user", "--noninteractive", "--no-related",
                           "lifecycle", *refs)

    def extra() -> FixtureLifecycleExtra:
        result = fixture.get("lifecycle_extra")
        if not isinstance(result, dict):
            raise PrerequisiteError("prepare_lifecycle_extra.py supplemental inputs required")
        return result

    if name == "lifex-runtime-instance":
        remote(root / "A")
        install(runtime)
        with tempfile.TemporaryFile(dir=driver.root) as descriptor:
            fd = descriptor.fileno()
            with _background(driver, "run", "--user", "--command=blackbox-probe",
                             f"--instance-id-fd={fd}", runtime, "hold", "120",
                             pass_fds=(fd,)) as process:
                record = driver.evidence[-1]
                assert process.stdout is not None
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    driver.check(bool(selector.select(15)), "runtime probe did not become ready")
                    ready = process.stdout.readline()
                record["stdout"] = ready
                driver.check(ready == "ready\n", "runtime probe readiness differs")
                descriptor.seek(0)
                instance = descriptor.read().decode().strip()
                driver.check(bool(instance), "launch did not report an instance ID")
                values.update(instance=instance, runtime=runtime,
                              runtime_commit=fixture["runtime_commit"])
                call("instance")
                driver.cli_success("kill", instance)
                process.wait(timeout=15)
        return
    if name in {"lifex-direct-bundle", "lifex-bundle-errors"}:
        queries = fixture.get("queries")
        if not isinstance(queries, dict):
            raise PrerequisiteError("prepared query bundles required")
        ref = f"app/{queries['app']}/{arch}/test"
        values.update(ref=ref, commit=queries["versions"]["A"]["refs"][ref]["commit"])
        remote(root / "A")
        install(runtime)
        if name == "lifex-direct-bundle":
            values["bundle"] = str(root / queries["bundle_plain"])
            call("bundle", "direct")
        else:
            malformed = driver.root / "malformed.flatpak"
            malformed.write_bytes(b"This is not an OSTree static delta.\n")
            for path in (malformed, driver.root / "absent.flatpak"):
                values["bundle"] = str(path)
                call("bundle", "invalid")
            driver.check(driver.cli_success("info", "--user", "--show-commit", runtime).strip()
                         == fixture["runtime_commit"], "bundle errors changed installed runtime")
        return
    if name == "lifex-signed-bundle":
        inputs = extra()
        remote(root / "A")
        install(runtime)
        values.update(bundle=str(root / inputs["signed_bundle"]),
                      key=str(root / fixture["build"]["public_key"]),
                      commit=fixture["commits"]["B"])
        call("bundle", "embedded-key")
        driver.cli_success("uninstall", "--user", "--noninteractive", app)
        # Remove the first import's trusted remote before the explicit-key import.
        origins = driver.cli_success("remotes", "--user", "--columns=name").splitlines()
        for origin in origins:
            if origin != "lifecycle":
                driver.cli_success("remote-delete", "--user", origin)
        call("bundle", "explicit-key")
        return
    if name == "lifex-image":
        inputs = extra()
        remote(root / "A")
        install(runtime)
        for version, image, payload in (
            ("A", inputs["image_A"], inputs["payload_A"]),
            ("B", inputs["image_B"], inputs["payload_B"]),
        ):
            values[f"image_{version}"] = "oci:" + str(root / image)
            values[f"payload_{version}"] = str(root / payload)
        call("image")
        return
    if name == "lifex-sideload-image":
        inputs = extra()
        remote(root / "A")
        install(runtime)
        empty = driver.root / "empty-registry"
        (empty / "A").mkdir(parents=True)
        server = RepositoryServer(empty)
        with server.serving() as server_url:
            driver.cli_success("remote-add", "--user", "--no-gpg-verify",
                               "lifecycle-oci", "oci+" + server_url)
            values.update(sideload="oci:" + str(root / inputs["image_A"]),
                          payload_A=str(root / inputs["payload_A"]))
            call("sideload", "image")
            driver.evidence[-1]["sideload_image_network_observation"] = {
                "requests": list(server.requests), "remote_contains_images": False}
        return
    if name in {"lifex-sideload-query", "lifex-sideload-query-native", "lifex-sideload-install"}:
        inputs = extra()
        build = fixture["build"]
        server = RepositoryServer(root / Path(build["usb_repo"]).parent)
        server.version = Path(build["usb_repo"]).name
        with server.serving() as server_url:
            driver.cli_success("remote-add", "--user",
                               f"--gpg-import={root / build['public_key']}",
                               f"--collection-id={build['collection_id']}",
                               "lifecycle", server_url)
            values.update(commit=build["usb_commits"]["app"],
                          sideload=str(root / inputs["sideload"]))
            if "query" in name:
                directory = user / "sideload-repos"
                directory.mkdir(parents=True, exist_ok=True)
                sideload = (inputs["sideload_native"] if name.endswith("native")
                            else inputs["sideload"])
                (directory / "fixture").symlink_to(root / sideload, target_is_directory=True)
                available = driver.cli_success("remote-ls", "--user", "--columns=ref", "lifecycle")
                driver.check(set(available.splitlines()) == {app, runtime},
                             "remote source must advertise both app and remote-only runtime")
                call("sideload", "query")
            else:
                install(runtime)
                before = len(server.requests)
                server.fail_payloads = True
                call("sideload", "install")
                requests = server.requests[before:]
                driver.check(not any(item["path"].endswith(".filez") for item in requests),
                             "sideload installation requested remote payload")
                driver.evidence[-1]["sideload_network_observation"] = {
                    "requests": requests,
                }
        return
    if name == "lifex-unused-pinned":
        inputs = extra()
        queries = fixture.get("queries")
        foreign = fixture.get("build_options", {})
        if queries is None or "policy_extensions" not in queries or "arch" not in foreign:
            raise PrerequisiteError("independent policy and alternate-architecture inputs required")
        if "usage_repo" not in inputs:
            raise PrerequisiteError(
                "distinct SDK usage inputs from prepare_lifecycle_extra required")
        remote(root / inputs["usage_repo"])
        main = inputs["usage_app"]
        sdk = inputs["usage_sdk"]
        extension = f"runtime/{queries['extension']}/{arch}/test"
        driver.check(len({runtime, sdk, extension}) == 3,
                     "runtime, SDK and extension must have distinct identities")
        install(main, sdk, extension)
        driver.cli_success("pin", "--user", "--remove", sdk)
        driver.cli_success("pin", "--user", "--remove", extension)
        values.update(usage_app=main, usage_sdk=sdk,
                      usage_app_commit=inputs["usage_app_commit"],
                      usage_sdk_commit=inputs["usage_sdk_commit"],
                      usage_metadata=str(root / inputs["usage_metadata"]),
                      usage_runtime=runtime)
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "policy",
                           (root / queries["policy_repo"]).as_uri())
        unused, pinned = [entry["ref"] for entry in queries["policy_extensions"]]
        driver.cli_success("install", "--user", "--noninteractive", "--no-related",
                           "policy", unused, pinned)
        driver.cli_success("pin", "--user", "--remove", unused)
        foreign_ref = f"runtime/{fixture['runtime']}/{foreign['arch']}/{branch}"
        driver.cli_success("install", "--user", "--noninteractive", "--bundle",
                           str(root / inputs["foreign_bundle"]))
        driver.cli_success("pin", "--user", foreign_ref)
        for selected, expected_unused, expected_pinned in (
            ("", unused, f"{pinned};{foreign_ref}"), (arch, unused, pinned),
            (foreign["arch"], "", foreign_ref), ("not-an-installed-arch", "", "")
        ):
            values.update(arch=selected, unused=expected_unused, pinned=expected_pinned)
            call("pinned")
        return
    if name == "lifex-monitor":
        remote(root / "A")
        install(runtime)
        call("monitor", "install")
        remote(root / "B", initial=False)
        values["commit"] = fixture["commits"]["B"]
        call("monitor", "update")
        call("monitor", "uninstall")
        return
    if name == "lifex-force-uninstall":
        remote(root / "A")
        for force in (False, True):
            install(app)
            location = driver.cli_success("info", "--user", "--show-location", app).strip()
            fd = os.open(location, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with _background(driver, "run", "--user", app, "hold", "120") as process:
                    record = driver.evidence[-1]
                    assert process.stdout is not None
                    with selectors.DefaultSelector() as selector:
                        selector.register(process.stdout, selectors.EVENT_READ)
                        driver.check(bool(selector.select(15)), "app did not become ready")
                        ready = process.stdout.readline()
                    record["stdout"] = ready
                    driver.check(ready == "ready\n", "app probe readiness differs")
                    call("force", "force" if force else "normal")
                    try:
                        os.stat("files/bin/blackbox-probe", dir_fd=fd)
                        retained = True
                    except FileNotFoundError:
                        retained = False
                    driver.check(retained != force,
                                 "force setting did not control retention of running app files")
                    driver.cli_success("kill", fixture["app"])
                    process.wait(timeout=15)
            finally:
                os.close(fd)
        return
    if name == "lifex-appdata":
        queries = fixture.get("queries")
        if not isinstance(queries, dict):
            raise PrerequisiteError("prepared query AppStream inputs required")
        remote(root / queries["versions"]["A"]["repo"])
        for identity, action in ((queries["app"], "rating"), (queries["second"], "missing-rating")):
            values["ref"] = f"app/{identity}/{arch}/test"
            install(values["ref"])
            call("metadata", action)
        return
    if name == "lifex-eol":
        tx = fixture.get("extras", {}).get("transactions")
        if not isinstance(tx, dict):
            raise PrerequisiteError("prepared transaction EOL inputs required")
        values["ref"] = f"app/{tx['apps'][0]}/{arch}/{branch}"
        for index, version in enumerate(("A", "EOL", "REBASE")):
            remote(root / tx["directory"] / version, initial=index == 0)
            values.update(reason="" if version == "A" else tx["eol_reason"],
                          rebase=(f"app/{tx['apps'][1]}/{arch}/{branch}"
                                  if version == "REBASE" else ""))
            if index == 0:
                install(values["ref"])
            else:
                # Direct update avoids transaction EOL policy choices as setup.
                values["commit"] = tx["commits"][version][values["ref"]]
                call("direct", "update")
            call("metadata", "eol")
        return
    if name in {"lifex-local-ref", "lifex-prune"}:
        queries = fixture.get("queries")
        if not isinstance(queries, dict):
            raise PrerequisiteError("prepared independent multi-app query inputs required")
        refs = queries["versions"]["A"]["refs"]
        remote(root / queries["versions"]["A"]["repo"])
        deployed = f"app/{queries['app']}/{arch}/test"
        pulled = f"app/{queries['second']}/{arch}/test"
        install(deployed)
        values.update(ref=deployed, commit=refs[deployed]["commit"])
        call("cleanup", "protected")
        values.update(ref=pulled, commit=refs[pulled]["commit"])
        call("direct", "pull")
        # Positive control: this input can be deployed without another pull.
        call("direct", "local")
        call("direct", "uninstall")
        call("direct", "pull")
        call("cleanup", "remove" if name == "lifex-local-ref" else "clean")
        call("direct", "local-missing")
        if name == "lifex-prune":
            call("cleanup", "prune")
            call("direct", "local-missing")
        # These public outcomes do not establish orphaned-object retention or
        # deletion. The full cleanup obligations deliberately remain unmapped.
        driver.check(driver.cli_success("info", "--user", "--show-commit", deployed).strip()
                     == refs[deployed]["commit"], "cleanup changed deployed app")
        driver.check(driver.cli_success("info", "--user", "--show-commit", runtime).strip()
                     == fixture["runtime_commit"], "cleanup changed runtime")
        return
    if name == "lifex-deferred-triggers":
        inputs = extra()
        remote(root / "A")
        install(runtime)
        values["ref"] = f"app/{inputs['trigger_app']}/{arch}/{branch}"
        cache = user / "exports/share/applications/mimeinfo.cache"

        def associations() -> set[str]:
            if not cache.exists():
                return set()
            config = configparser.ConfigParser(interpolation=None)
            config.read(cache)
            return {key for key, value in config.items("MIME Cache")
                    if inputs["trigger_app"] + ".desktop" in value.split(";")}

        driver.check(not associations(), "fresh app unexpectedly in MIME cache")
        for version, action in (("A", "install"), ("B", "update")):
            remote(root / inputs["triggers"][version]["repo"], initial=False)
            values["commit"] = inputs["triggers"][version]["commit"]
            previous_associations = associations()
            call("direct", action)
            driver.check(associations() == previous_associations,
                         "NO_TRIGGERS refreshed MIME cache early")
            call("triggers")
            driver.check(associations() == {f"application/x-lifecycle-{version.lower()}"},
                         "deferred trigger did not refresh exported MIME associations")
        call("direct", "uninstall")
        driver.check(associations() == {"application/x-lifecycle-b"},
                     "NO_TRIGGERS uninstall refreshed MIME cache early")
        call("triggers")
        driver.check(not associations(), "uninstall trigger retained removed app association")
        return
    raise AssertionError(f"unhandled lifecycle scenario: {name}")
