# SPDX-License-Identifier: LGPL-2.1-or-later
"""Run public-interface compatibility scenarios against a configured target."""

import argparse
import functools
import hashlib
import importlib
import os
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager, suppress
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import monotonic
from xml.sax.saxutils import escape

from catalogue_schema import parse_gap
from console_output import ConsoleOutput, github_summary, use_color
from coverage_report import CoverageModel, digest, format_summary, write_json
from fixture_manifest import FixtureManifest, load_fixture
from json_validation import decode_json
from remote_scenarios import (
    remote_cli_args,
    remote_configuration,
    remote_priority_order,
)
from report_schema import (
    ArtifactIntegrity,
    ArtifactProvenance,
    CaseResult,
    EvidenceRecord,
    LibraryProvenance,
    RepositoryRequest,
    RunReport,
)
from scenario_catalogue import extension_clients, load_behaviors
from target_config import TargetConfig, load_target, parse_environment

HERE = Path(__file__).resolve().parent


class ContractFailure(Exception):
    pass


class PrerequisiteError(Exception):
    pass


class UnsupportedCapability(Exception):
    pass


def failure_status(error: Exception) -> str:
    if isinstance(error, PrerequisiteError):
        return "unmet-prerequisite"
    if isinstance(error, UnsupportedCapability):
        return "unsupported"
    if isinstance(error, ContractFailure):
        return "failed"
    return "setup-error"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractFailure(message)


def terminate(process: subprocess.Popen[str] | subprocess.Popen[bytes]) -> None:
    # Kill the process group even if its leader has already exited.
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def execute(argv: list[str], env: dict[str, str], cwd: Path,
            evidence: list[EvidenceRecord], timeout: float) -> subprocess.CompletedProcess[str]:
    record: EvidenceRecord = {"argv": argv}
    evidence.append(record)
    try:
        process = subprocess.Popen(argv, env=env, cwd=cwd, text=True,
                                   stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
    except FileNotFoundError as error:
        record["error"] = str(error)
        raise PrerequisiteError(str(error)) from error
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        terminate(process)
        stdout, stderr = process.communicate()
        record.update({"stdout": stdout, "stderr": stderr, "timed_out": True,
                       "exit_status": process.wait()})
        raise ContractFailure(f"command timed out after {timeout}s: {argv}") from error
    finally:
        terminate(process)
    returncode = process.wait()
    record.update({"stdout": stdout, "stderr": stderr, "exit_status": returncode})
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


@contextmanager
def session_bus(env: dict[str, str], root: Path, *,
                on_cleanup: Callable[[], None] | None = None) -> Iterator[None]:
    # A private address alone still permits host desktop-service activation.
    # Adapters can supply the target's required services in this directory.
    services = root / "services"
    services.mkdir(exist_ok=True)
    config = root / "session.conf"
    config.write_text(
        '<busconfig><type>session</type><listen>unix:tmpdir=/tmp</listen>'
        '<auth>EXTERNAL</auth>'
        f'<servicedir>{escape(str(services))}</servicedir>'
        '<policy context="default"><allow send_destination="*"/>'
        '<allow receive_sender="*"/><allow own="*"/></policy></busconfig>'
    )
    with (root / "dbus.log").open("w") as log:
        try:
            process = subprocess.Popen(
                ["dbus-daemon", f"--config-file={config}", "--nofork", "--print-address=1"],
                env=env, text=True, stdout=subprocess.PIPE, stderr=log,
                start_new_session=True,
            )
        except FileNotFoundError as error:
            raise PrerequisiteError("dbus-daemon is required") from error
        try:
            assert process.stdout is not None
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                if not selector.select(timeout=10):
                    raise PrerequisiteError("session bus startup timed out; see dbus.log")
            address = process.stdout.readline().strip()
            if not address:
                raise PrerequisiteError("session bus failed to start; see dbus.log")
            env["DBUS_SESSION_BUS_ADDRESS"] = address
            yield
        finally:
            if on_cleanup is not None:
                on_cleanup()
            try:
                terminate(process)
            finally:
                if process.stdout:
                    process.stdout.close()


class RepositoryServer:
    def __init__(self, fixtures: Path) -> None:
        self.fixtures = fixtures
        self.version = "A"
        self.fail_payloads = False
        self.requests: list[RepositoryRequest] = []

    @contextmanager
    def serving(self, *, on_cleanup: Callable[[], None] | None = None) -> Iterator[str]:
        repository = self

        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self) -> None:
                self.directory = str(repository.fixtures / repository.version)
                blocked = repository.fail_payloads and self.path.endswith(".filez")
                repository.requests.append({
                    "path": self.path, "version": repository.version, "blocked": blocked,
                })
                # Switching snapshots must not reuse a cached summary based on mtime.
                if "If-Modified-Since" in self.headers:
                    del self.headers["If-Modified-Since"]
                if blocked:
                    self.send_error(503, "Injected payload download failure")
                else:
                    super().do_GET()

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler))
        thread: threading.Thread | None = None
        thread_started = False
        shutdown_complete = False
        try:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            thread_started = True
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            if on_cleanup is not None:
                on_cleanup()
            try:
                if thread_started:
                    server.shutdown()
                    shutdown_complete = True
            finally:
                try:
                    server.server_close()
                finally:
                    # A failed shutdown must not block the remaining cleanup in join().
                    if shutdown_complete and thread is not None:
                        thread.join()


class Driver:
    def __init__(self, kind: str, cli: str, client: Path | None,
                 env: dict[str, str], root: Path,
                 evidence: list[EvidenceRecord], timeout: float) -> None:
        self.kind = kind
        self.cli = cli
        self.client = client
        self.env = env
        self.root = root
        self.evidence = evidence
        self.timeout = timeout

    def check(self, condition: bool, message: str) -> None:
        require(condition, message)

    def cli_call(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return self.external_call([self.cli, *arguments], "cli")

    def external_call(self, argv: list[str], interface: str) -> subprocess.CompletedProcess[str]:
        if interface not in ("cli", "library", "setup"):
            raise ValueError(f"invalid external command interface: {interface}")
        result = execute(argv, self.env, self.root, self.evidence, self.timeout)
        record = self.evidence[-1]
        if interface != "setup":
            record["interface"] = interface
        if interface == "library":
            record["api_calls"] = sorted({
                line.removeprefix("api-call ") for line in result.stderr.splitlines()
                if line.startswith("api-call ")
            })
            record["signals"] = sorted({
                line.removeprefix("signal-event ") for line in result.stderr.splitlines()
                if line.startswith("signal-event ")
            })
        return result

    def cli_success(self, *arguments: str) -> str:
        result = self.cli_call(*arguments)
        require(result.returncode == 0, f"CLI {arguments} failed: {result.stderr}")
        return result.stdout.strip()

    def call(self, operation: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        if operation == "run":
            # libflatpak lifecycle tests explicitly depend on CLI app launching.
            argv = [self.cli, "run", "--user", *arguments]
        elif self.kind == "library":
            assert self.client is not None
            argv = [str(self.client), operation, *arguments]
        else:
            remote_arguments = remote_cli_args(operation, arguments)
            if remote_arguments is not None:
                argv = [self.cli, *remote_arguments]
            else:
                argument, = arguments
                commands = {
                    "remote": ["remote-add", "--user", "--no-gpg-verify", "fixture", argument],
                    "install": ["install", "--user", "--noninteractive", "fixture", argument],
                    "update": ["update", "--user", "--noninteractive", argument],
                    "uninstall": ["uninstall", "--user", "--noninteractive", argument],
                    "query": ["info", "--user", "--show-ref", "--show-commit", argument],
                    "list-apps": ["list", "--user", "--app", "--columns=application"],
                    "list-refs": ["list", "--user", "--columns=ref"],
                }
                argv = [self.cli, *commands[operation]]
        interface = "library" if self.kind == "library" and operation != "run" else "cli"
        return self.external_call(argv, interface)

    def success(self, operation: str, *arguments: str) -> str:
        result = self.call(operation, *arguments)
        require(result.returncode == 0, f"{self.kind} {operation} failed: {result.stderr}")
        return result.stdout.strip()

    def expect_error(self, operation: str, ref: str, error_name: str) -> None:
        result = self.call(operation, ref)
        if self.kind == "library":
            # Client protocol statuses are mapped using public GError constants.
            statuses = {"NOT_INSTALLED": 3, "ALREADY_INSTALLED": 4, "REF_NOT_FOUND": 5}
            require(result.returncode == statuses[error_name],
                    f"{operation}: expected public {error_name} error, got "
                    f"client status {result.returncode}: {result.stderr}")
        else:
            require(result.returncode > 0, f"{operation} must fail for {ref}")
            diagnostics = {
                "NOT_INSTALLED": ("not installed", "nothing matches", "no installed refs found"),
                "REF_NOT_FOUND": ("no remote refs found", "not found", "nothing matches"),
            }
            require(ref.split("/")[1] in result.stderr,
                    f"{operation} diagnostic must identify the requested ref")
            require(any(text in result.stderr.casefold() for text in diagnostics[error_name]),
                    f"{operation} failed for an unrelated reason: {result.stderr}")

    def query(self, ref: str, commit: str | None = None) -> str:
        output = self.success("query", ref)
        parts = output.split()
        require(len(parts) == 2, f"expected ref and commit, got {output!r}")
        actual_ref, actual_commit = parts
        require(actual_ref == ref, f"queried ref {actual_ref!r} differs from {ref!r}")
        if commit is not None:
            require(actual_commit == commit, f"expected commit {commit}, got {actual_commit}")
        return str(actual_commit)


def assert_installed_version(driver: Driver, fixture: FixtureManifest, version: str,
                             context: str) -> None:
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
    driver.query(app, fixture["commits"][version])
    driver.query(runtime, fixture["runtime_commit"])
    require(driver.success("run", app) == version,
            f"app did not report version {version} {context}")


def scenario(driver: Driver, repository: RepositoryServer, url: str,
             fixture: FixtureManifest, name: str) -> None:
    if name == "remote-config":
        remote_configuration(driver, repository, url, fixture)
        return
    if name == "remote-priority-order":
        remote_priority_order(driver, repository, url, fixture)
        return
    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    missing = f"app/{fixture['app']}.Missing/{fixture['arch']}/{fixture['branch']}"
    driver.success("remote", url)
    if name == "ready-abort":
        aborted = driver.call("install-abort-ready", app)
        driver.check(aborted.returncode > 0,
                     "returning FALSE from ready must abort the transaction")
        driver.check(aborted.stderr.splitlines().count("signal ready") == 1,
                     "the abort decision must be made by the public ready signal handler")
        driver.check(not any(line.startswith("signal new-operation")
                             for line in aborted.stderr.splitlines()),
                     "ready rejection must prevent operation execution")
        driver.check(driver.success("list-refs", "") == "",
                     "aborted ready must leave no installed refs")
        # A new transaction accepting ready must still be able to install normally.
        accepted = driver.call("install", app)
        driver.check(accepted.returncode == 0,
                     f"accepting ready must permit install: {accepted.stderr}")
        driver.check(accepted.stderr.splitlines().count("signal ready") == 1,
                     "successful transaction must consult the accepting ready handler")
        assert_installed_version(driver, fixture, "A", "after accepting ready")
        return
    if name == "missing-install":
        driver.expect_error("install", missing, "REF_NOT_FOUND")
        require(driver.success("list-refs", "") == "",
                "failed install must leave the fresh installation empty")
        return
    driver.success("install", app)
    assert_installed_version(driver, fixture, "A", "after install")
    if name == "absent-ref":
        for operation in ("query", "uninstall"):
            driver.expect_error(operation, missing, "NOT_INSTALLED")
            assert_installed_version(driver, fixture, "A", f"after {operation} of absent ref")
        return
    if name in ("noop-update", "repeated-install"):
        if name == "noop-update":
            driver.success("update", app)
        else:
            # Plain install must not silently become an update when B is available.
            repository.version = "B"
            if driver.kind == "library":
                driver.expect_error("install", app, "ALREADY_INSTALLED")
            else:
                repeated = driver.call("install", app)
                require(repeated.returncode == 0, "repeated CLI install must succeed")
                require("already installed" in (repeated.stdout + repeated.stderr).casefold(),
                        "repeated CLI install must warn that the app is already installed")
        assert_installed_version(driver, fixture, "A", f"after {name}")
        return
    if name not in ("lifecycle", "failed-update", "retry-update"):
        raise ValueError(f"scenario has no implementation: {name}")
    failure = name in ("failed-update", "retry-update")
    repository.version = "B"
    repository.fail_payloads = failure
    if failure:
        result = driver.call("update", app)
        require(result.returncode > 0, "failed download must produce an update error")
        require(any(request["blocked"] for request in repository.requests),
                "update failed without attempting the injected payload download")
        version = "A"
    else:
        driver.success("update", app)
        version = "B"
    assert_installed_version(driver, fixture, version, "after update")
    if name == "retry-update":
        repository.fail_payloads = False
        retry_start = len(repository.requests)
        driver.success("update", app)
        require(any(request["version"] == "B" and request["path"].endswith(".filez")
                    and not request["blocked"] for request in repository.requests[retry_start:]),
                "retry did not attempt a restored payload download")
        assert_installed_version(driver, fixture, "B", "after retry")
    if not failure:
        driver.success("uninstall", app)
        runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
        driver.query(runtime, fixture["runtime_commit"])
        absent = driver.call("query", app)
        if driver.kind == "library":
            require(absent.returncode == 3, "expected public NOT_INSTALLED error")
        else:
            require(absent.returncode > 0, "query must fail after uninstall")
            require(driver.success("list-apps", "") == "",
                    "successful app enumeration must be empty after uninstall")


def environment(root: Path, target: TargetConfig) -> dict[str, str]:
    # Do not inherit host installations, session buses, proxy settings or test hooks.
    env = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C", "TZ": "UTC",
           "TERM": "dumb", "GIO_USE_VFS": "local"}
    for key, directory in {
        "HOME": "home", "XDG_DATA_HOME": "home/data", "XDG_CONFIG_HOME": "home/config",
        "XDG_CACHE_HOME": "home/cache", "XDG_STATE_HOME": "home/state",
        "XDG_RUNTIME_DIR": "runtime",
        "TMPDIR": "tmp",
    }.items():
        path = root / directory
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        env[key] = str(path)
    env.update(target.environment)
    return env


def resolve_program(command: str, env: dict[str, str], directory: Path) -> str:
    if "/" in command:
        candidate = Path(command)
        if not candidate.is_absolute():
            candidate = directory / candidate
        command = str(candidate)
    search_path = os.pathsep.join(
        str(Path(entry) if Path(entry).is_absolute() else directory / entry)
        for entry in env["PATH"].split(os.pathsep)
    )
    selected = shutil.which(command, path=search_path)
    if selected is None:
        raise PrerequisiteError(f"executable not found: {command}")
    return str(Path(selected).resolve())


def record_artifact(path: Path, artifacts: dict[str, str]) -> ArtifactProvenance:
    path = path.absolute()
    sha256 = digest(path.read_bytes())
    artifacts[str(path)] = sha256
    return {"path": str(path), "sha256": sha256}


def check_artifacts(artifacts: dict[str, str]) -> ArtifactIntegrity:
    changed = []
    for path, expected in artifacts.items():
        try:
            if digest(Path(path).read_bytes()) != expected:
                changed.append(path)
        except OSError:
            changed.append(path)
    return {"status": "changed" if changed else "verified", "changed_paths": changed}


def build_client(target: TargetConfig, output: Path,
                 evidence: list[EvidenceRecord], timeout: float,
                 provenance: LibraryProvenance, artifacts: dict[str, str]) -> Path:
    library = target.library
    if library is None:
        raise PrerequisiteError("target.library: public library configuration is required")
    env = dict(os.environ)
    env.update(library.environment)
    directories = library.runtime_library_dirs
    if not directories or any(not Path(p).is_absolute() or not Path(p).is_dir()
                              for p in directories):
        raise PrerequisiteError("explicit existing absolute runtime library dirs required")
    env["LD_LIBRARY_PATH"] = os.pathsep.join(directories)
    version = execute([library.pkg_config, "--modversion", library.package],
                      env, output, evidence, timeout)
    if version.returncode:
        raise PrerequisiteError(f"public libflatpak development files missing: {version.stderr}")
    flags = execute([library.pkg_config, "--cflags", "--libs", library.package],
                    env, output, evidence, timeout)
    if flags.returncode:
        raise PrerequisiteError(f"public libflatpak development files missing: {flags.stderr}")
    client = output / "library-client"
    extensions = extension_clients(HERE)
    dispatcher = output / "client-extensions.c"
    declarations = "\n".join(f"int {entry}(int, char **);" for _, entry in extensions)
    calls = "\n".join(f"result = {entry}(argc, argv); if (result >= 0) return result;"
                      for _, entry in extensions)
    dispatcher.write_text(
        declarations + "\nint blackbox_extension_main(int argc, char **argv) {\n"
        + ("int result;\n" if extensions else "(void)argc; (void)argv;\n")
        + calls + "\nreturn -1;\n}\n"
    )
    result = execute([library.cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                      "-I", str(HERE), str(HERE / "client.c"), str(dispatcher),
                      *(str(source) for source, _ in extensions),
                      "-o", str(client), *shlex.split(flags.stdout)],
                     env, output, evidence, timeout)
    require(result.returncode == 0, f"public library client did not compile: {result.stderr}")
    linked = execute(["ldd", str(client)], env, output, evidence, timeout)
    if linked.returncode:
        raise PrerequisiteError(f"cannot verify runtime library selection: {linked.stderr}")
    soname = library.soname
    resolved = [line.split()[2] for line in linked.stdout.splitlines()
                if len(line.split()) >= 3 and line.split()[:2] == [soname, "=>"]]
    if len(resolved) != 1 or not any(
        Path(resolved[0]).resolve().is_relative_to(Path(directory).resolve())
        for directory in directories
    ):
        raise PrerequisiteError(f"{soname} was not loaded from configured runtime library dirs")
    library_path = Path(resolved[0]).resolve()
    library_identity = record_artifact(library_path, artifacts)
    # Also follow the loader's original path at completion, detecting a retargeted
    # SONAME symlink even when the old resolved file remains unchanged.
    record_artifact(Path(resolved[0]), artifacts)
    client_identity = record_artifact(client, artifacts)
    provenance.update({"package_version": version.stdout.strip(), "path": library_identity["path"],
                       "sha256": library_identity["sha256"],
                       "client_sha256": client_identity["sha256"]})
    return client


def main(*, clock: Callable[[], float] = monotonic) -> int:
    started = clock()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--fixtures", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="new results directory")
    parser.add_argument("--driver", choices=["cli", "library", "all"], default="all")
    parser.add_argument("--color", choices=["auto", "always", "never"], default="auto",
                        help="console color (nonempty NO_COLOR overrides all modes)")
    try:
        inventory = load_behaviors(HERE)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(f"invalid coverage definitions: {error}")
    parser.add_argument("--scenario", default="all", choices=[
        "all", *(behavior["scenario"] for behavior in inventory if "scenario" in behavior),
    ])
    parser.add_argument("--timeout", type=float, default=120, help="seconds per command")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        coverage_model = CoverageModel(HERE)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(f"invalid coverage definitions: {error}")
    target_path = args.target.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    fixtures = args.fixtures.resolve()
    report: RunReport = {
        "schema": 1, "target_configuration": str(target_path),
        "results": [], "gaps": [parse_gap(item) for item in inventory if "gap" in item],
        "full_compatibility": False, "setup_evidence": [],
        "complete": False, "coverage_definition": coverage_model.definition,
        "started_at": datetime.now(timezone.utc).isoformat(), "library_provenance": {},
    }
    cases: dict[tuple[str, str, str], CaseResult] = {}
    for kind in ("cli", "library"):
        for behavior in inventory:
            if "scenario" not in behavior:
                continue
            if kind not in behavior["drivers"]:
                continue
            selected = args.driver in ("all", kind) and args.scenario in (
                "all", behavior["scenario"]
            )
            key = (behavior["id"], kind, behavior["profile"])
            required_capabilities = set(behavior["required_capabilities"]) | {"cli"}
            if kind == "library":
                required_capabilities.add("libflatpak")
            for identifier in coverage_model.mapping.get(key, set()):
                required_capabilities.update(
                    coverage_model.requirements[identifier]["required_capabilities"]
                )
            result: CaseResult = {
                "behavior_id": behavior["id"], "driver": kind, "profile": behavior["profile"],
                "target_version": None,
                "status": "pending" if selected else "not-selected", "evidence": [],
                "required_capabilities": sorted(required_capabilities),
            }
            cases[key] = result
            report["results"].append(result)
    console = ConsoleOutput(
        [result for result in cases.values() if result["status"] == "pending"], sys.stdout,
        color=use_color(args.color, sys.stdout, os.environ),
    )
    status = 0
    artifacts: dict[str, str] = {}
    write_json(output / "report.json", report)
    try:
        target = load_target(target_path)
        configuration = record_artifact(target_path, artifacts)
        report["target"] = target.name
        unsupported = target.unsupported_capabilities
        known_capabilities = {capability for result in cases.values()
                              for capability in result["required_capabilities"]}
        known_capabilities.update(capability for requirement in coverage_model.requirements.values()
                                  for capability in requirement["required_capabilities"])
        if set(unsupported) - known_capabilities:
            raise ValueError("unsupported_capabilities must map known capabilities to reasons")
        report["declared_unsupported_capabilities"] = unsupported
        for result in cases.values():
            missing = {capability: unsupported[capability]
                       for capability in result["required_capabilities"]
                       if capability in unsupported}
            if result["status"] == "pending" and missing:
                result.update({"status": "unsupported", "unsupported_capabilities": missing})
                status = 1
            case_definition = coverage_model.cases[
                result["behavior_id"], result["driver"], result["profile"]
            ]
            if result["status"] == "pending" and result["profile"] not in ("user", "any") and (
                case_definition.get("execution_environment") not in
                ("root-userns", "provisioned-system")
            ):
                result.update({"status": "unsupported",
                               "error": "System-profile execution requires a VM runner."})
                status = 1
            if result["status"] == "unsupported":
                console.case_finished(result)
        if not any(result["status"] == "pending" for result in cases.values()):
            raise UnsupportedCapability("target declares all selected scenarios unsupported")
        fixture = load_fixture(fixtures / "fixture.json")
        for relative, expected in fixture["sha256"].items():
            path = (fixtures / relative).resolve()
            if not path.is_relative_to(fixtures):
                raise PrerequisiteError(f"fixture path escapes fixture directory: {relative}")
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise PrerequisiteError(f"fixture checksum mismatch: {relative}")
        fixture["directory"] = str(fixtures)
        report["fixture"] = fixture
        fixture_identity = record_artifact(fixtures / "fixture.json", artifacts)
        report["fixture_provenance"] = {
            "path": str(fixtures), "manifest_sha256": fixture_identity["sha256"],
        }
        probe_env = environment(output / "probe", target)
        cli = resolve_program(target.cli, probe_env, target_path.parent)
        cli_identity = record_artifact(Path(cli), artifacts)
        adapter_command = [resolve_program(target.adapter[0], probe_env, target_path.parent),
                           *target.adapter[1:]]
        adapter_files = [record_artifact(Path(adapter_command[0]), artifacts)]
        for argument in adapter_command[1:]:
            candidate = Path(argument.split("=", 1)[-1])
            if not candidate.is_absolute():
                candidate = target_path.parent / candidate
            try:
                is_file = candidate.is_file()
            except OSError:
                # Inline code or a long option value is not necessarily a path.
                is_file = False
            if is_file:
                adapter_files.append(record_artifact(candidate, artifacts))
        report["target_provenance"] = {
            "configuration_sha256": configuration["sha256"],
            "cli_path": cli_identity["path"], "cli_sha256": cli_identity["sha256"],
            "adapter_files": adapter_files,
        }
        version = execute([cli, "--version"], probe_env, output,
                          report["setup_evidence"], args.timeout)
        require(version.returncode == 0, "target version query failed")
        report["target_version"] = version.stdout.strip()
        for result in cases.values():
            result["target_version"] = report["target_version"]
        arch = execute([cli, "--default-arch"], probe_env, output,
                       report["setup_evidence"], args.timeout)
        require(arch.returncode == 0, "target architecture query failed")
        if arch.stdout.strip() != fixture["arch"]:
            raise PrerequisiteError("fixture architecture differs from target architecture")
        drivers = ["cli", "library"] if args.driver == "all" else [args.driver]
        for kind in drivers:
            if not any(result["driver"] == kind and result["status"] == "pending"
                       for result in cases.values()):
                continue
            client = None
            client_error: Exception | None = None
            if kind == "library":
                try:
                    client = build_client(target, output, report["setup_evidence"], args.timeout,
                                          report["library_provenance"], artifacts)
                except (ContractFailure, PrerequisiteError, KeyError) as error:
                    client_error = error
            for behavior in inventory:
                if "scenario" not in behavior:
                    continue
                if kind not in behavior["drivers"]:
                    continue
                name = behavior["scenario"]
                result = cases[behavior["id"], kind, behavior["profile"]]
                if result["status"] != "pending":
                    continue
                if client_error:
                    result.update({"status": failure_status(client_error),
                                   "error": str(client_error)})
                    status = 1
                    console.case_finished(result)
                    continue
                case_started = clock()
                execution_started: float | None = None
                cleanup_started: float | None = None

                def begin_cleanup() -> None:
                    # A context may roll back inside __enter__, before ExitStack owns it.
                    nonlocal cleanup_started
                    if cleanup_started is None:
                        cleanup_started = clock()

                root: Path | None = None
                repository: RepositoryServer | None = None
                contexts = ExitStack()
                try:
                    # Unix-domain socket paths must fit even when --output is deep.
                    root = Path(tempfile.mkdtemp(prefix="fp-bb-"))
                    result["state_directory"] = str(root)
                    repository = RepositoryServer(fixtures)
                    env = environment(root, target)
                    adapter = execute([*adapter_command, str(root)], env, target_path.parent,
                                      result["evidence"], args.timeout)
                    if adapter.returncode == 77:
                        raise PrerequisiteError(f"setup adapter failed: {adapter.stderr}")
                    if adapter.returncode:
                        raise ValueError(f"setup adapter failed: {adapter.stderr}")
                    env.update(parse_environment(decode_json(adapter.stdout, "adapter"), "adapter"))
                    if kind == "library":
                        if target.library is None:
                            raise PrerequisiteError("target.library: configuration is required")
                        directories = target.library.runtime_library_dirs
                        if not directories or any(not Path(p).is_absolute() for p in directories):
                            raise PrerequisiteError(
                                "explicit absolute runtime library dirs required"
                            )
                        env["LD_LIBRARY_PATH"] = os.pathsep.join(directories)
                    contexts.enter_context(session_bus(env, root, on_cleanup=begin_cleanup))
                    url = contexts.enter_context(repository.serving(on_cleanup=begin_cleanup))
                    driver = Driver(kind, cli, client, env, root,
                                    result["evidence"], args.timeout)
                    execution_started = clock()
                    if "handler" in behavior:
                        module_name, function_name = behavior["handler"].split(":")
                        handler = getattr(importlib.import_module(module_name), function_name)
                        handler(driver, repository, url, fixture, name)
                    else:
                        scenario(driver, repository, url, fixture, name)
                    result["status"] = "passed"
                except (PrerequisiteError, ContractFailure, OSError, ValueError,
                        KeyError, TypeError) as error:
                    result.update({"status": failure_status(error), "error": str(error)})
                    status = 1
                finally:
                    begin_cleanup()
                    assert cleanup_started is not None
                    try:
                        try:
                            contexts.close()
                        finally:
                            if repository is not None:
                                result["repository_requests"] = repository.requests
                            if root is not None:
                                if (root / "dbus.log").exists():
                                    shutil.copy2(root / "dbus.log",
                                                 output / f"{kind}-{name}-dbus.log")
                                shutil.rmtree(root)
                        result["cleanup_complete"] = True
                    except (OSError, ValueError, KeyError, TypeError,
                            PrerequisiteError, ContractFailure) as error:
                        result.update({"status": "setup-error", "cleanup_error": str(error)})
                        status = 1
                    finally:
                        finished = clock()
                        result["duration_seconds"] = finished - case_started
                        result["timings"] = {
                            "setup_seconds": (execution_started if execution_started is not None
                                              else cleanup_started) - case_started,
                            "execution_seconds": (cleanup_started - execution_started
                                                  if execution_started is not None else 0.0),
                            "cleanup_seconds": finished - cleanup_started,
                        }
                    write_json(output / "report.json", report)
                console.case_finished(result)
    except (OSError, ValueError, KeyError, TypeError, PrerequisiteError,
            ContractFailure, UnsupportedCapability) as error:
        report["setup_error"] = str(error)
        report["setup_status"] = failure_status(error)
        for result in cases.values():
            if result["status"] == "pending":
                result.update({"status": failure_status(error), "error": str(error)})
                console.case_finished(result)
        status = 1
        console.setup_error(report["setup_status"], str(error))
    finally:
        report["complete"] = all(result["status"] != "pending" for result in cases.values())
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["artifact_integrity"] = check_artifacts(artifacts)
        if report["artifact_integrity"]["status"] != "verified":
            status = 1
        report["coverage"] = coverage_model.summarize(report)
        if report["coverage"]["verification"]["status"] != "current":
            status = 1
        report["duration_seconds"] = clock() - started
        write_json(output / "report.json", report)
        (output / "coverage.md").write_text(format_summary(report["coverage"]))
    console.summary(report, output, status)
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        try:
            rendered = github_summary(report, status)
            with Path(summary_path).open("a", encoding="utf-8") as summary:
                summary.write("\n\n" + rendered)
            # Only mark delivery after the Actions append has successfully closed.
            (output / "job-summary.md").write_text(rendered, encoding="utf-8")
        except OSError as error:
            console.setup_error("setup-error", f"Cannot write GitHub job summary: {error}")
            status = 1
    return status


if __name__ == "__main__":
    # Scenario modules import these public runner helpers and exception types.
    sys.modules["run"] = sys.modules[__name__]
    sys.exit(main())
