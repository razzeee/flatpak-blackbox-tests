# SPDX-License-Identifier: LGPL-2.1-or-later
"""Real transactions against an independent public-wire authenticator."""

from __future__ import annotations

import shlex
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from fixture_manifest import FixtureManifest
from json_validation import json_value
from report_schema import EvidenceRecord

if TYPE_CHECKING:
    from run import Driver, RepositoryServer


@contextmanager
def protected_server(driver: Driver, directory: Path,
                     payloads: list[str]) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Gate repository payloads on the independently issued bearer token."""
    requests: list[dict[str, Any]] = []

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self) -> None:
            self.directory = str(directory)
            path = urlsplit(self.path).path.lstrip("/")
            protected = path in payloads
            valid = (self.headers.get("Authorization") ==
                     "Bearer blackbox-download-token")
            requests.append({"path": path, "protected": protected, "authorized": valid})
            if protected and not valid:
                self.send_error(401, "Token required")
            else:
                super().do_GET()

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        driver.evidence.append({"observation": "auth-http", "data": json_value(requests)})


def run(driver: Driver, repository: RepositoryServer, url: str,
         fixture: FixtureManifest, name: str) -> None:
    """Exercise isolated authentication decisions and observable deployment results."""
    from run import PrerequisiteError, terminate

    del repository, url
    extra = fixture["extras"]["auth"]
    directory = Path(fixture["directory"]) / extra["directory"] / "repo"
    if name in {"auth-install-required", "auth-install-success"}:
        if "authenticator_ref" not in extra or "authenticator_commit" not in extra:
            raise PrerequisiteError("prepared available authenticator candidate required")
        if name == "auth-install-success" and "authenticator_binary" not in extra:
            raise PrerequisiteError("prepared runnable authenticator and runtime required")
        candidate = extra["authenticator_ref"]
        with protected_server(driver, directory, extra["payloads"]) as (auth_url, requests):
            driver.success("remote", auth_url)
            available = driver.cli_success("remote-info", "--user", "--show-commit",
                                           "fixture", candidate)
            driver.check(available == extra["authenticator_commit"],
                         "independent authenticator candidate is advertised")
            driver.cli_success("remote-modify", "--user", "--authenticator-install",
                               f"--authenticator-name={candidate.split('/')[1]}", "fixture")
            before = len(requests)
            output = driver.success("auth-install-required", extra["ref"], candidate)
            driver.check(output == "auth-install-declined", "client completed refusal assertions")
            driver.check(not any(item["protected"] for item in requests[before:]),
                          "declined authenticator installation prevents protected transfers")
            if name == "auth-install-success":
                from install_option_scenarios import _state

                _state(driver, {})
                before = len(requests)
                parent = "x11:1234"
                result = driver.call("auth-install-success", "basic", extra["ref"], extra["commit"],
                                     parent, candidate, extra["authenticator_commit"], auth_url,
                                     driver.cli, extra["authenticator_runtime_ref"])
                driver.check(result.returncode == 0,
                             f"accepted authenticator installation failed: {result.stderr}")
                driver.check(result.stdout.endswith("auth-result\t1\n"),
                             "client must complete accepted installation and authentication")
                driver.check(f"request {extra['ref']} {extra['commit']} {parent} {auth_url}" in
                             result.stdout and "response 0\n" in result.stdout,
                             "newly installed authenticator must validate the real request")
                transfers = [request for request in requests[before:] if request["protected"]]
                driver.check(bool(transfers) and
                             all(request["authorized"] for request in transfers),
                             "resumed transaction must use the authenticator token for payloads")
                _state(driver, {extra["ref"]: extra["commit"],
                                candidate: extra["authenticator_commit"],
                                extra["authenticator_runtime_ref"]:
                                    extra["authenticator_runtime_commit"]})
                deployment = Path(driver.cli_success("info", "--user", "--show-location",
                                                      candidate))
                payload = deployment / "files/bin/blackbox-authenticator"
                prepared = Path(fixture["directory"]) / extra["authenticator_binary"]
                driver.check(payload.read_bytes() == prepared.read_bytes(),
                             "installed service bytes must equal the independent prepared binary")
        return
    binary = driver.root / "fixture-auth-service"
    flags = subprocess.check_output(
        ["pkg-config", "--cflags", "--libs", "gio-2.0"], text=True)
    build = driver.external_call([
        "cc", "-Wall", "-Wextra", "-Werror", "-o", str(binary),
        str(Path(__file__).with_name("fixture-auth-service.c")), *shlex.split(flags),
    ], "setup")
    driver.check(build.returncode == 0, f"authenticator compile failed: {build.stderr}")
    mode = name.removeprefix("auth-")
    modes = {"web": ["web-wrong", "web"],
             "basic-abort": ["basic-decline", "basic-abort"],
             "web-abort": ["web-decline", "web-abort"],
             "pre-auth": ["pre-abort", "basic"],
             "parent-window": ["basic", "basic"]}.get(mode, [mode])
    with protected_server(driver, directory, extra["payloads"]) as (auth_url, requests):
        driver.success("remote", auth_url)
        driver.cli_success("remote-modify", "--user", "fixture", "--authenticator-name",
                           "org.flatpak.BlackboxAuthenticator")
        for index, current in enumerate(modes):
            parent = "wayland:blackbox-handle" if index else "x11:1234"
            log_path = driver.root / f"auth-service-{index}.log"
            with log_path.open("w") as log:
                service = subprocess.Popen([
                    str(binary), "web" if current.startswith("web") else "basic",
                    extra["ref"], extra["commit"], parent, auth_url,
                ], env=driver.env, stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=True)
                try:
                    deadline = time.monotonic() + 5
                    while "service-ready" not in log_path.read_text():
                        driver.check(service.poll() is None, log_path.read_text())
                        driver.check(time.monotonic() < deadline,
                                     "authenticator startup timed out")
                        time.sleep(0.02)
                    before = len(requests)
                    result = driver.call("auth-run", current, extra["ref"],
                                         extra["commit"], parent)
                    driver.check(result.returncode == 0,
                                 f"auth client assertion failed: {result.stderr}\n"
                                 f"{log_path.read_text()}")
                    success = current in ("basic", "web")
                    expected = f"auth-result\t{int(success)}"
                    driver.check(result.stdout.strip() == expected,
                                 "client must reach final authentication assertions")
                    deadline = time.monotonic() + 3
                    while (current != "pre-abort" and
                           "response " not in log_path.read_text()):
                        driver.check(service.poll() is None, log_path.read_text())
                        driver.check(time.monotonic() < deadline,
                                     "missing authenticator response")
                        time.sleep(0.02)
                    text = log_path.read_text()
                    driver.check(service.poll() is None, text)
                    if current == "pre-abort":
                        driver.check("request " not in text,
                                     "pre-auth refusal must precede token request")
                    else:
                        request = (f"request {extra['ref']} {extra['commit']} "
                                   f"{parent} {auth_url}")
                        driver.check(request in text,
                                     "service must validate exact request and parent")
                        status = 0 if success else 2 if current.endswith("wrong") else 1
                        driver.check(f"response {status}" in text, text)
                    transfers = [r for r in requests[before:] if r["protected"]]
                    if success:
                        driver.check(bool(transfers) and
                                     all(r["authorized"] for r in transfers),
                                     "payload must be downloaded with correct token")
                        driver.check(driver.success("query", extra["ref"]).split() ==
                                     [extra["ref"], extra["commit"]],
                                     "exact protected commit must deploy")
                        if index + 1 < len(modes):
                            driver.success("uninstall", extra["ref"])
                            driver.cli_success("repair", "--user")
                    else:
                        driver.check(not transfers,
                                     "failed authentication must not fetch payload")
                        driver.check(driver.success("list-refs", extra["ref"]) == "",
                                     "failed auth must leave installation empty")
                finally:
                    try:
                        service.terminate()
                        try:
                            service.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            terminate(service)
                    finally:
                        try:
                            terminate(service)
                        finally:
                            record: EvidenceRecord = {"observation": "authenticator-wire",
                                                      "mode": current,
                                                      "data": log_path.read_text()}
                            if service.returncode is not None:
                                record["exit_status"] = service.returncode
                            driver.evidence.append(record)
