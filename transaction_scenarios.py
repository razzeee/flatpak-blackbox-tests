# SPDX-License-Identifier: LGPL-2.1-or-later
"""Transaction assertions using only public target interfaces and fixture HTTP."""

from __future__ import annotations

import base64
import configparser
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from fixture_manifest import FixtureManifest, FixtureSize
from json_validation import json_value

if TYPE_CHECKING:
    from typing import AnyStr

    from _typeshed import SupportsRead, SupportsWrite

    from run import Driver, RepositoryServer


class TransferServer:
    """Immutable repositories with per-payload failure, pacing, and cancellation gates."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.blocked: set[str] = set()
        self.slow = False
        self.cancel_marker: Path | None = None
        self.requests: list[dict[str, Any]] = []

    @contextmanager
    def serving(self, driver: Driver) -> Iterator[str]:
        fixture_server = self

        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self) -> None:
                self.directory = str(fixture_server.directory)
                path = urlsplit(self.path).path.lstrip("/")
                blocked = path in fixture_server.blocked
                fixture_server.requests.append({"path": path, "blocked": blocked})
                if "If-Modified-Since" in self.headers:
                    del self.headers["If-Modified-Since"]
                if blocked:
                    self.send_error(503, "Controlled transaction payload failure")
                else:
                    with suppress(BrokenPipeError, ConnectionResetError):
                        super().do_GET()

            def copyfile(self, source: SupportsRead[AnyStr],
                         outputfile: SupportsWrite[AnyStr]) -> None:
                payload = self.path.endswith(".filez")
                first = True
                while chunk := source.read(
                    1 if payload and first and fixture_server.cancel_marker is not None else 8192
                ):
                    outputfile.write(chunk)
                    self.wfile.flush()
                    if payload and first and fixture_server.cancel_marker is not None:
                        fixture_server.cancel_marker.write_text(self.path)
                        fixture_server.requests.append({"in_flight": self.path})
                        time.sleep(2)
                    first = False
                    if payload and fixture_server.slow:
                        time.sleep(0.025)

            def log_message(self, format: str, *args: Any) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            driver.evidence.append({"observation": "fixture-http",
                                    "data": json_value(self.requests)})


def _tx(driver: Driver, mode: str, action: str, ref: str, *,
        remote: str = "fixture", operand: str = "-", succeeds: bool = True,
        sizes: dict[str, FixtureSize] | None = None) -> list[list[str]]:
    """Run MODE ACTION REMOTE REF OPERAND [SIZE_KEYFILE].

    The action-specific operand is a commit for update, a second ref for rebase
    and independent-operation cases, or a remote name for lookup. Cancellation
    mode uses it as the synchronized cancellation-marker path.
    """
    arguments = [mode, action, remote, ref, operand]
    if sizes is not None:
        driver.check(mode == "sizes" and bool(sizes), "size oracle requires per-ref values")
        for values in sizes.values():
            driver.check(all(type(values[key]) is int and values[key] > 0
                             for key in ("download", "installed")),
                         "reference-prepared sizes must be positive integer byte counts")
        arguments.append("\n".join(
            f"[{size_ref}]\ndownload={values['download']}\ninstalled={values['installed']}\n"
            for size_ref, values in sorted(sizes.items())
        ))
    result = driver.call("tx-run", *arguments)
    driver.check(result.returncode == (0 if succeeds else 1),
                 f"{mode}/{action}: unexpected result {result.returncode}: {result.stderr}")
    rows = [line.split("\t") for line in result.stdout.splitlines()]
    driver.check(any(row[0] == "result" for row in rows), "client must complete its assertions")
    if not succeeds:
        driver.check(any(row[0] == "error" and len(row) == 3 for row in rows),
                     "failed transaction must supply an outer GError")
    return rows


def _rows(rows: list[list[str]], label: str) -> list[list[str]]:
    return [row[1:] for row in rows if row[0] == label]


def _state(driver: Driver, fixture: FixtureManifest, version: str) -> None:
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    for ref, commit in ((app, fixture["commits"][version]), (runtime, fixture["runtime_commit"])):
        driver.check(driver.success("query", ref).split() == [ref, commit],
                     f"{ref} must retain expected commit {commit}")


def _empty(driver: Driver, app: str) -> None:
    driver.check(driver.success("list-refs", app) == "", "installation must remain empty")


def _installed(driver: Driver, rows: list[list[str]], app: str, runtime: str,
               fixture: FixtureManifest, version: str = "A") -> None:
    expected = {app: fixture["commits"][version], runtime: fixture["runtime_commit"]}
    ops = _rows(rows, "op")
    driver.check({op[0]: op[3] for op in ops} == expected,
                 f"resolved operations must match fixture commits: {ops!r}")
    driver.check(all(op[2] == "0" for op in ops), "both operations must be installs")
    driver.check(_rows(rows, "ready") == [["2"]], "ready must expose app and dependency")
    driver.check(_rows(rows, "new") == [[op[0]] for op in ops],
                 "all resolved operations must execute in list order")
    driver.check({row[0]: row[1] for row in _rows(rows, "done")} == expected,
                 "done signals must report exact deployed commits")
    driver.check(not _rows(rows, "operation-error"), "healthy install must have no errors")
    _state(driver, fixture, version)


def run(driver: Driver, repository: RepositoryServer, url: str,
        fixture: FixtureManifest, name: str) -> None:
    """Dispatch isolated cases. Each runner invocation provides fresh user state."""
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    repository.version = "A"
    driver.success("remote", url)

    if name == "tx-lookup":
        driver.success("install", app)
        driver.success("remote-create", "tx-second", url + "/", "Second origin", "1")
        _tx(driver, "normal", "lookup", app, operand="tx-second")
        _state(driver, fixture, "A")
        return

    if name == "tx-cancel-download":
        driver.success("install", app)
        server = TransferServer(Path(fixture["directory"]) / "B")
        server.cancel_marker = driver.root / "payload-in-flight"
        with server.serving(driver) as transfer_url:
            driver.success("remote-edit", "fixture", transfer_url, "Cancellation fixture", "1")
            rows = _tx(driver, "cancel", "update", app,
                       operand=str(server.cancel_marker), succeeds=False)
            driver.check(_rows(rows, "cancelled-in-flight") == [[]],
                         "cancellation thread must observe server's in-flight marker")
            driver.check(any("in_flight" in request for request in server.requests),
                         "server must have sent first payload byte with remainder gated")
            driver.check(not _rows(rows, "done"), "interrupted update must not complete")
        _state(driver, fixture, "A")
        return

    if name == "tx-choose-remote":
        driver.cli_success("remote-modify", "--user", "--no-use-for-deps", "fixture")
        driver.success("remote-create", "tx-low", url + "/", "Low priority", "10")
        driver.success("remote-create", "tx-high", url + "//", "High priority", "90")
        for mode, succeeds in (("decline", False), ("normal", True)):
            rows = _tx(driver, mode, "install", app, succeeds=succeeds)
            driver.check(_rows(rows, "choose") == [[app, runtime, "tx-high", "tx-low"]],
                         "runtime choice must identify refs and candidates in descending priority")
            if succeeds:
                runtime_ops = [row for row in _rows(rows, "op") if row[0] == runtime]
                driver.check(len(runtime_ops) == 1 and runtime_ops[0][1] == "tx-high",
                             "returning index zero must choose the first remote")
                _state(driver, fixture, "A")
            else:
                driver.check(not _rows(rows, "new"), "declining must fail before execution")
                _empty(driver, app)
        return

    if name == "tx-flatpakref":
        for mode in ("decline", "normal"):
            server = TransferServer(Path(fixture["directory"]) / "A")
            with server.serving(driver) as ref_url:
                data = (f"[Flatpak Ref]\nVersion=1\nName={fixture['app']}\n"
                        f"Branch={fixture['branch']}\nTitle=Transaction fixture\n"
                        f"Url={ref_url}\nSuggestRemoteName=tx-suggested\nIsRuntime=false\n")
                result = driver.call("tx-run", mode, "flatpakref", "-", data, "-")
                driver.check(result.returncode in (0, 1), f"flatpakref assertion: {result.stderr}")
                rows = [line.split("\t") for line in result.stdout.splitlines()]
                driver.check(_rows(rows, "add-remote") == [
                    ["0", fixture["app"], "tx-suggested", ref_url]],
                    "remote suggestion must supply generic reason, originating ID, name and URL")
                names = [line.split("\t")[0] for line in driver.success("remote-list").splitlines()]
                driver.check(("tx-suggested" in names) == (mode == "normal"),
                             "suggested remote addition must follow callback decision")
                if mode == "normal":
                    driver.check(result.returncode == 0, "accepted flatpakref must install")
                    _state(driver, fixture, "A")
                elif result.returncode == 0:
                    _state(driver, fixture, "A")
                    _tx(driver, "normal", "uninstall", app)
        return

    if name in ("tx-metadata", "tx-independent-errors", "tx-completed-survive",
                 "tx-progress", "tx-rate", "tx-frequency",
                "tx-eol", "tx-eol-rebase", "tx-rebase-success", "tx-rebase-failure",
                "tx-rebase-null"):
        _supplemental(driver, fixture, name)
        return

    if name == "tx-options":
        rows = _tx(driver, "normal", "empty", app)
        driver.check(_rows(rows, "ready") == [["0"]], "empty transaction resolves empty")
        driver.check(not _rows(rows, "new"), "empty transaction executes nothing")
        _empty(driver, app)
    elif name in ("tx-ready", "tx-pre-auth", "tx-disable-dependencies"):
        mode = {"tx-ready": "abort-ready", "tx-pre-auth": "abort-pre-auth",
                "tx-disable-dependencies": "no-dependencies"}[name]
        rows = _tx(driver, mode, "install", app, succeeds=False)
        driver.check(not _rows(rows, "new") and not _rows(rows, "done"),
                     "refused readiness must precede all execution")
        if name == "tx-pre-auth":
            driver.check(_rows(rows, "pre-auth") == [["2"]] and not _rows(rows, "ready"),
                         "pre-auth refusal must precede ready")
            driver.check(dict(_rows(rows, "pre-ref")) == {
                app: fixture["commits"]["A"], runtime: fixture["runtime_commit"]},
                "pre-auth operations must already be resolved")
        else:
            expected = [app] if name == "tx-disable-dependencies" else [runtime, app]
            driver.check([row[0] for row in _rows(rows, "op")] == expected,
                         "resolved operation set must respect dependency setting")
        _empty(driver, app)
        _installed(driver, _tx(driver, "normal", "install", app), app, runtime, fixture)
    elif name in ("tx-operation-list", "tx-operation-sizes", "tx-ownership"):
        mode = "sizes" if name == "tx-operation-sizes" else "normal"
        sizes = None
        if name == "tx-operation-sizes":
            driver.check("sizes" in fixture, "reference-prepared fixture sizes are required")
            sizes = {ref: fixture["sizes"]["A"][ref] for ref in (app, runtime)}
        rows = _tx(driver, mode, "install", app, sizes=sizes)
        _installed(driver, rows, app, runtime, fixture)
        if name == "tx-ownership":
            driver.check([runtime, app, "0"] in _rows(rows, "cause"),
                         "live borrowed graph must identify the app causing its runtime")
            driver.check(bool(_rows(rows, "progress")),
                         "progress status ownership must be exercised")
        if name == "tx-operation-list":
            noop = _tx(driver, "normal", "update", app)
            driver.check(_rows(noop, "ready") == [["0"]] and not _rows(noop, "new"),
                         "all-skipped update must be empty and execute no operations")
            _state(driver, fixture, "A")
        if name == "tx-operation-sizes":
            rows = _tx(driver, "sizes", "uninstall", app)
            driver.check(len(_rows(rows, "op")) == 1, "uninstall must expose one operation")
            driver.check(_rows(rows, "op")[0][4:] == ["0", "0"],
                         "uninstall sizes must both be zero")
    elif name in ("tx-download-only", "tx-no-pull", "tx-explicit-commit", "tx-no-deploy-uninstall"):
        driver.success("install", app)
        if name == "tx-no-deploy-uninstall":
            rows = _tx(driver, "no-deploy", "uninstall", app)
            _state(driver, fixture, "A")
            return
        repository.version = "B"
        if name == "tx-explicit-commit":
            _tx(driver, "normal", "update", app)
            _state(driver, fixture, "B")
            _tx(driver, "normal", "update", app, operand=fixture["commits"]["A"])
            _state(driver, fixture, "A")
            return
        before = len(repository.requests)
        _tx(driver, "download", "update", app)
        driver.check(any(request["path"].endswith(".filez") and not request["blocked"]
                         for request in repository.requests[before:]),
                     "download-only update must fetch payload")
        _state(driver, fixture, "A")
        if name == "tx-no-pull":
            before = len(repository.requests)
            _tx(driver, "local", "update", app)
            driver.check(len(repository.requests) == before,
                         "no-pull must not request network data")
            _state(driver, fixture, "B")
        else:
            _tx(driver, "normal", "empty", app)
    elif name == "tx-error-sequence":
        driver.success("install", app)
        repository.version = "B"
        repository.fail_payloads = True
        before = len(repository.requests)
        rows = _tx(driver, "normal", "update", app, succeeds=False)
        driver.check(_rows(rows, "new") == [[app]], "failed update must begin once")
        errors = _rows(rows, "operation-error")
        driver.check(len(errors) == 1 and errors[0][0] == app and errors[0][3] == "0",
                     "mandatory failed update must carry its own error and fatal details")
        driver.check(not _rows(rows, "done"), "failed update must not report completion")
        driver.check(any(request["path"].endswith(".filez") and request["blocked"]
                         for request in repository.requests[before:]),
                     "must attempt denied payload")
        _state(driver, fixture, "A")
        repository.fail_payloads = False
        rows = _tx(driver, "normal", "update", app)
        driver.check(_rows(rows, "new") == [[app]], "retry must begin one update")
        driver.check(_rows(rows, "done") == [[app, fixture["commits"]["B"], "0"]],
                     "retry completion must identify B")
        _state(driver, fixture, "B")
    elif name == "tx-auto-pin":
        _tx(driver, "normal", "install", runtime)
        driver.check(driver.success("tx-pins", fixture["arch"]) == runtime,
                     "explicit runtime must be pinned")
        _tx(driver, "normal", "uninstall", runtime)
        driver.cli_success("pin", "--user", "--remove", runtime)
        _tx(driver, "no-pin", "install", runtime)
        driver.check(driver.success("tx-pins", fixture["arch"]) == "",
                     "disable-auto-pin must leave fresh runtime unpinned")
    else:
        raise ValueError(f"unknown transaction scenario {name}")


def _supplemental(driver: Driver, fixture: FixtureManifest, name: str) -> None:
    extra = fixture.get("extras", {}).get("transactions")
    driver.check(extra is not None, "prepare_transactions.py supplemental fixture is required")
    assert extra is not None
    directory = Path(fixture["directory"]) / extra["directory"]
    first, second = [f"app/{app}/{fixture['arch']}/{fixture['branch']}" for app in extra["apps"]]
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    server = TransferServer(directory / "A")

    def state(ref: str, version: str) -> None:
        driver.check(driver.success("query", ref).split() == [ref, extra["commits"][version][ref]],
                     f"{ref} must be deployed at {version}")

    def absent(ref: str) -> None:
        result = driver.call("query", ref)
        driver.check(result.returncode == 3, f"{ref} must be absent with NOT_INSTALLED")

    with server.serving(driver) as url:
        driver.success("remote-edit", "fixture", url, "Supplemental transactions", "1")
        driver.success("install", first)
        state(first, "A")
        server.directory = directory / "B"

        if name == "tx-metadata":
            rows = _tx(driver, "abort-ready", "update", first, succeeds=False)
            driver.check(_rows(rows, "ready") == [["1"]], "metadata update resolves only app")
            driver.check(_rows(rows, "op")[0][3] == extra["commits"]["B"][first],
                         "resolved commit must be B")
            for label, version in (("metadata", "B"), ("old-metadata", "A")):
                encoded, = _rows(rows, label)[0]
                actual = configparser.ConfigParser()
                actual.read_string(base64.b64decode(encoded).decode())
                expected = configparser.ConfigParser()
                expected.read_string(extra["metadata"][f"{version}:{extra['apps'][0]}"])
                driver.check(actual == expected, f"{label} must equal complete fixture {version}")
            state(first, "A")
        elif name == "tx-frequency":
            counts = []
            for mode in ("frequency-fast", "frequency-slow", "frequency-fast"):
                server.directory = directory / "B"
                server.slow = True
                rows = _tx(driver, mode, "update", first)
                samples = {int(row[1]) for row in _rows(rows, "progress")}
                driver.check(max(samples) >= 1024 * 1024,
                             "each cadence control transfers independent payload")
                counts.append(len(samples - {0, max(samples)}))
                state(first, "B")
                server.directory = directory / "A"
                server.slow = False
                _tx(driver, "normal", "update", first, operand=extra["commits"]["A"][first])
                state(first, "A")
            driver.check(counts[1] >= 1 and min(counts[0], counts[2]) > 2 * counts[1],
                         f"50ms updates sample advancing bytes more often than 1000ms: {counts}")
            driver.evidence.append({"observation": "progress-update-cadence",
                                    "data": json_value({"interval_ms": [50, 1000, 50],
                                                        "advancing_samples": counts})})
        elif name in ("tx-progress", "tx-rate"):
            server.slow = True
            rows = _tx(driver, "progress" if name == "tx-progress" else "rate", "update", first)
            values = _rows(rows, "progress")
            driver.check(len(values) > 2 and max(int(row[1]) for row in values) >= 1024 * 1024,
                         "paced transfer needs repeated readings and payload-sized byte count")
            if name == "tx-rate":
                rates = [(int(elapsed), int(rate)) for elapsed, rate in _rows(rows, "rate")]
                driver.check(any(elapsed < 1_000_000 and rate == 0 for elapsed, rate in rates),
                             "first transfer second must expose initial zero rate")
                driver.check(any(elapsed >= 1_000_000 and rate > 0 for elapsed, rate in rates),
                             "sustained transfer must eventually expose positive bytes-per-second")
            state(first, "B")
        elif name in ("tx-independent-errors", "tx-completed-survive"):
            plan = _tx(driver, "abort-ready", "update-install", first,
                       operand=second, succeeds=False)
            order = [row[0] for row in _rows(plan, "op")]
            driver.check(set(order) == {first, second} and len(order) == 2,
                         "controlled plan must have exactly two independent app operations")
            failing = order[-1] if name == "tx-completed-survive" else order[0]
            server.blocked = set(extra["payloads"]["B"][failing])
            driver.check(bool(server.blocked), "failed operation must require unique new payloads")
            modes = ("normal", "continue") if name == "tx-independent-errors" else ("normal",)
            for mode in modes:
                # Continue may report aggregate success despite a failed operation.
                result = driver.call("tx-run", mode, "update-install", "fixture", first, second)
                driver.check(result.returncode in (0, 1),
                             f"operation decision assertion: {result.stderr}")
                rows = [line.split("\t") for line in result.stdout.splitlines()]
                errors = _rows(rows, "operation-error")
                driver.check(len(errors) == 1 and errors[0][0] == failing and errors[0][3] == "0",
                             "failing mandatory operation must provide GError and fatal detail")
                expected_new = (order if mode == "continue" or name == "tx-completed-survive"
                                else order[:1])
                driver.check(_rows(rows, "new") == [[ref] for ref in expected_new],
                             "callback decision must govern remaining independent operation")
                completed = [ref for ref in expected_new if ref != failing]
                driver.check(_rows(rows, "done") == [
                    [ref, extra["commits"]["B"][ref], "0"] for ref in completed],
                    "completed independent operations must identify B commits")
                if mode == "normal":
                    driver.check(result.returncode == 1 and bool(_rows(rows, "error")),
                                 "stopping on failure must return FALSE and outer GError")
                for ref in (first, second):
                    if ref in completed:
                        state(ref, "B")
                    elif ref == first:
                        state(ref, "A")
                    else:
                        absent(ref)
            driver.check(any(request.get("blocked") for request in server.requests),
                         "server must observe a denied required payload")
        elif name == "tx-eol":
            server.directory = directory / "EOL"
            rows = _tx(driver, "normal", "update", first)
            driver.check(_rows(rows, "eol") == [[first, extra["eol_reason"], "-"]],
                         "EOL notification must supply ref, reason, and absent replacement")
            state(first, "EOL")
            server.directory = directory / "REBASE"
            rows = _tx(driver, "normal", "update", first)
            driver.check(_rows(rows, "eol") == [[first, extra["eol_reason"], second]],
                         "EOL notification must also preserve a non-NULL replacement")
            state(first, "REBASE")
        elif name == "tx-eol-rebase":
            server.directory = directory / "REBASE"
            rows = _tx(driver, "normal", "update", first)
            eol_payload = ["fixture", first, extra["eol_reason"], second, extra["apps"][0]]
            driver.check(_rows(rows, "eol-rebase") == [eol_payload],
                         "EOL callback must identify source, reason, target and previous IDs")
            driver.check(_rows(rows, "new") == [[first]], "FALSE must retain old update")
            state(first, "REBASE")
            absent(second)
            # Reinstall A from the available older commit, then accept the same EOL decision.
            _tx(driver, "normal", "update", first, operand=extra["commits"]["A"][first])
            rows = _tx(driver, "rebase", "update", first)
            driver.check(_rows(rows, "eol-rebase") == [eol_payload],
                         "TRUE receives same EOL payload")
            driver.check(_rows(rows, "new") == [[second], [first]],
                         "rebase replacement installs before old uninstall")
            driver.check([row[2] for row in _rows(rows, "op")] == ["0", "3"],
                         "old update must be skipped in favor of uninstall")
            state(second, "REBASE")
            absent(first)
        elif name == "tx-rebase-null":
            # gtk-doc explicitly annotates previous_ids nullable. Keep this
            # variant separate from the ordinary explicit-IDs rebase contract.
            rows = _tx(driver, "normal", "rebase-null", first, operand=second)
            driver.check(_rows(rows, "new") == [[second], [first]],
                         "documented nullable IDs must still install then uninstall")
            state(second, "B")
            absent(first)
        elif name in ("tx-rebase-success", "tx-rebase-failure"):
            if name == "tx-rebase-failure":
                server.blocked = set(extra["payloads"]["B"][second])
                rows = _tx(driver, "normal", "rebase", first, operand=second, succeeds=False)
                driver.check(_rows(rows, "new") == [[second]],
                             "failed rebase cannot uninstall old app")
                driver.check(bool(_rows(rows, "operation-error")),
                             "replacement must fail during execution")
                state(first, "A")
                absent(second)
            else:
                rows = _tx(driver, "normal", "rebase", first, operand=second)
                driver.check(_rows(rows, "new") == [[second], [first]],
                             "replacement install must precede old uninstall")
                state(second, "B")
                absent(first)
                _tx(driver, "normal", "uninstall", second)
                rows = _tx(driver, "normal", "rebase", first, operand=second)
                driver.check(_rows(rows, "new") == [[second]],
                             "absent old ref silently omits uninstall")
                state(second, "B")
        driver.check(driver.success("query", runtime).split() ==
                     [runtime, fixture["runtime_commit"]],
                     "supplemental transactions must retain unchanged runtime")
