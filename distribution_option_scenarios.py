# SPDX-License-Identifier: LGPL-2.1-or-later
"""CLI image and sideload inputs validated through payloads and network faults."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fixture_manifest import FixtureManifest
from install_option_scenarios import _state

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    from run import PrerequisiteError, RepositoryServer

    inputs = fixture.get("lifecycle_extra")
    if inputs is None:
        raise PrerequisiteError("independent image and sideload inputs required")
    root = Path(fixture["directory"])
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    if name == "distribution-options-image":
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "fixture", url)
        driver.cli_success("install", "--user", "--noninteractive", "fixture", runtime)
        # Valid OCI prefixes are auto-detected. Force image parsing on an
        # unsupported transport to distinguish --image from an ignored flag.
        invalid = "unsupported:/blackbox-image"
        control = driver.cli_call("install", "--user", "--noninteractive", invalid)
        forced = driver.cli_call("install", "--user", "--noninteractive", "--image", invalid)
        driver.check(control.returncode > 0 and forced.returncode > 0 and
                     forced.stderr != control.stderr and
                     any(word in forced.stderr.lower() for word in ("image", "transport")),
                     f"explicit image parsing must identify invalid image input: {forced.stderr}")
        _state(driver, {runtime: fixture["runtime_commit"]})
        origin = ""
        for version, image_path, payload in (("A", inputs["image_A"], inputs["payload_A"]),
                                             ("B", inputs["image_B"], inputs["payload_B"])):
            reinstall = ("--reinstall",) if version == "B" else ()
            driver.cli_success("install", "--user", "--noninteractive", "--image", *reinstall,
                               "oci:" + str(root / image_path))
            rows = driver.cli_success("list", "--user", "--all", "--columns=ref").splitlines()
            expected = {ref.split("/", 1)[1] for ref in (app, runtime)}
            driver.check(len(rows) == 2 and set(rows) == expected, "exact image deployment refs")
            driver.query(runtime, fixture["runtime_commit"])
            driver.check(driver.cli_success("info", "--user", "--show-ref", app) == app,
                         "image must deploy the independently named app ref")
            location = Path(driver.cli_success("info", "--user", "--show-location", app))
            driver.check((location / "files/bin/blackbox-probe").read_bytes() ==
                         (root / payload).read_bytes(), f"image {version} payload matches fixture")
            current = driver.cli_success("info", "--user", "--show-origin", app)
            driver.check(bool(current) and (not origin or current == origin),
                         "image replacement preserves its origin")
            origin = current
        return

    if name not in {"distribution-options-sideload-install",
                    "distribution-options-sideload-update"}:
        raise ValueError(f"unknown distribution option scenario: {name}")
    build = fixture.get("build")
    if build is None:
        raise PrerequisiteError("signed collection repository and public key required")
    updating = name.endswith("-update")
    if updating and "sideload_update_repo" not in inputs:
        raise PrerequisiteError("independent signed sideload update input required")
    sources = driver.root / "sources"
    sources.mkdir()
    (sources / "A").symlink_to(root / build["usb_repo"], target_is_directory=True)
    if updating:
        (sources / "B").symlink_to(root / inputs["sideload_update_repo"], target_is_directory=True)
        driver.check((root / inputs["payload_A"]).read_bytes() !=
                     (root / inputs["payload_B"]).read_bytes(),
                     "sideload update needs independently changed executable bytes")
    server = RepositoryServer(sources)
    try:
        with server.serving() as source_url:
            driver.cli_success("remote-add", "--user", f"--gpg-import={root / build['public_key']}",
                               f"--collection-id={build['collection_id']}", "fixture", source_url)
            driver.cli_success("install", "--user", "--noninteractive", "fixture",
                               app if updating else runtime)
            before_state = {runtime: build["usb_commits"]["runtime"]}
            if updating:
                before_state[app] = build["usb_commits"]["app"]
                server.version = "B"
            _state(driver, before_state)
            command = "update" if updating else "install"
            trailing = (app,) if updating else ("fixture", app)
            sideload = inputs["sideload_update"] if updating else inputs["sideload"]
            commit = inputs["sideload_update_commit"] if updating else build["usb_commits"]["app"]
            server.fail_payloads = True
            start = len(server.requests)
            control = driver.cli_call(command, "--user", "--noninteractive", *trailing)
            _state(driver, before_state)
            driver.check(control.returncode > 0 and
                         any(request["blocked"] for request in server.requests[start:]),
                         "without a sideload source the required payload download must fail")
            start = len(server.requests)
            driver.cli_success(command, "--user", "--noninteractive",
                               f"--sideload-repo={root / sideload}", *trailing)
            _state(driver, {app: commit, runtime: build["usb_commits"]["runtime"]})
            driver.check(not any(request["path"].endswith(".filez")
                                 for request in server.requests[start:]),
                         "sideload source must avoid remote payload downloads")
    finally:
        repository.requests.extend(server.requests)
