# SPDX-License-Identifier: LGPL-2.1-or-later
"""Public help and informational options, with independent output oracles."""

from __future__ import annotations

import re
from pathlib import Path
from subprocess import CompletedProcess
from typing import TYPE_CHECKING, Protocol

from fixture_manifest import FixtureManifest

if TYPE_CHECKING:
    from run import Driver

# Frozen documented commands, not discovered from the target's own help output.
# Each value is a documented option or positional syntax from its manpage.
# Seeing an option in help tests only --help, never the displayed option.
HELP_SYNTAX = {
    "build": "--runtime",
    "build-bundle": "--runtime",
    "build-commit-from": "--src-repo",
    "build-export": "--runtime",
    "build-finish": "--command",
    "build-import-bundle": "--gpg-sign",
    "build-init": "--sdk-extension",
    "build-sign": "--gpg-sign",
    "build-update-repo": "--generate-static-deltas",
    "config": "--set",
    "create-usb": "--allow-partial",
    "document-export": "--unique",
    "document-info": "FILE",
    "document-unexport": "--doc-id",
    "documents": "[APPID]",
    "enter": "INSTANCE COMMAND",
    "history": "--columns",
    "info": "--show-ref",
    "install": "--no-deploy",
    "kill": "INSTANCE",
    "list": "--app-runtime",
    "make-current": "--arch",
    "mask": "--remove",
    "override": "--show",
    "permission-remove": "TABLE ID",
    "permission-reset": "--all",
    "permission-set": "--data",
    "permission-show": "APP_ID",
    "permissions": "[TABLE] [ID]",
    "pin": "--remove",
    "preinstall": "--no-deploy",
    "ps": "--columns",
    "remote-add": "--title",
    "remote-delete": "--force",
    "remote-info": "--show-ref",
    "remote-ls": "--updates",
    "remote-modify": "--title",
    "remotes": "--show-disabled",
    "repair": "--dry-run",
    "repo": "--branches",
    "run": "--command",
    "search": "--columns",
    "uninstall": "--force-remove",
    "update": "--commit",
}


class HelpDriver(Protocol):
    """The public runner operations needed by these scenarios."""

    def cli_call(self, *arguments: str) -> CompletedProcess[str]: ...

    def check(self, condition: bool, message: str) -> None: ...


def _output(driver: HelpDriver, *arguments: str) -> str:
    result = driver.cli_call(*arguments)
    driver.check(result.returncode == 0,
                 f"{arguments}: expected success, got {result.returncode}: "
                 f"{result.stderr}")
    driver.check(not result.stderr.strip(),
                 f"{arguments}: unexpected stderr: {result.stderr!r}")
    driver.check(bool(result.stdout.strip()), f"{arguments}: stdout must not be empty")
    return result.stdout


def _help(driver: HelpDriver, command: str | None) -> str:
    arguments = (command, "--help") if command else ("--help",)
    output = _output(driver, *arguments)
    # GLib may render the ellipsis as '?' when stdout uses the C locale's charset.
    # Keep checking command identity and syntax independently of that rendering.
    usage = r"(?m)^\s*\S+\s+"
    if command:
        usage += re.escape(command) + r"\s+"
    usage += r"\[OPTION(?:…|\.{3}|\?)?\]"
    if command is None:
        usage += r"\s+COMMAND\b"
    driver.check(output.startswith("Usage:\n") and re.search(usage, output) is not None,
                 f"{arguments}: missing command-specific usage: {output!r}")
    driver.check(re.search(r"(?m)^\s+(?:-h,\s+)?--help\s+\S", output) is not None,
                 f"{arguments}: missing described --help option")
    return output


def run(driver: HelpDriver, repository: object, url: str,
        fixture: FixtureManifest, name: str) -> None:
    """Check one informational contract using the standard scenario handler."""
    if name == "global-options-command-help":
        for command, syntax in HELP_SYNTAX.items():
            output = _help(driver, command)
            if syntax.startswith("--"):
                pattern = r"(?m)^\s+(?:-\w,\s+)?" + re.escape(syntax) + r"(?:=|\s)"
                driver.check(re.search(pattern, output) is not None,
                             f"{command} --help: missing documented option {syntax}")
            else:
                driver.check(syntax in output.splitlines()[1],
                             f"{command} --help: missing argument syntax {syntax}")
        return

    if name == "global-options-help":
        output = _help(driver, None)
        for command in HELP_SYNTAX:
            driver.check(re.search(r"(?m)^\s+" + re.escape(command) + r"\s+\S", output)
                         is not None, f"global help omits documented command {command}")
        driver.check("--default-arch" in output and "--version" in output,
                     "global help omits documented informational options")
        return

    if name == "global-options-default-arch":
        output = _output(driver, "--default-arch")
        driver.check(output.split() == [fixture["arch"]],
                     f"default arch differs from independent fixture: {output!r}")
        return

    if name == "global-options-supported-arches":
        # Independent compatibility metadata for the prepared x86_64 fixture.
        # Other hosts need explicit reference metadata, not target self-comparison.
        if fixture["arch"] != "x86_64":
            from run import PrerequisiteError
            message = "supported-arches oracle requires an x86_64 fixture"
            raise PrerequisiteError(message)
        output = _output(driver, "--supported-arches")
        driver.check(output.split() == ["x86_64", "i386"],
                     f"expected native then compatible x86 architectures: {output!r}")
        return

    if name == "global-options-version":
        output = _output(driver, "--version")
        # The target may be a different release from the fixture producer. Check
        # product/version information, without deriving an expected value from it.
        version = r"Flatpak \d+\.\d+\.\d+(?:[-+~.][\w.+~-]+)?\s*"
        driver.check(re.fullmatch(version, output)
                     is not None, f"expected Flatpak release information: {output!r}")
        return

    message = f"unknown global option scenario: {name}"
    raise ValueError(message)


def _diagnostics(driver: HelpDriver, result: CompletedProcess[str], expected: str) -> set[str]:
    driver.check(result.returncode == 0,
                 f"diagnostic command failed: {result.args}: {result.stderr}")
    driver.check(result.stdout == expected,
                 f"verbosity changed command output: {result.stdout!r}, expected {expected!r}")
    return {line.strip() for line in result.stderr.splitlines() if line.strip()}


def _levels(driver: HelpDriver, quiet: set[str], verbose: set[str], detailed: set[str]) -> None:
    driver.check(not quiet, f"quiet control unexpectedly emitted diagnostics: {quiet}")
    driver.check(bool(verbose), "--verbose did not enable diagnostics")
    driver.check(len(detailed) > len(verbose), "-vv did not provide additional distinct detail")


def run_controlled(driver: Driver, repository: object, url: str,
                   fixture: FixtureManifest, name: str) -> None:
    """Observe controlled environment selection and diagnostic levels through the CLI."""
    from run import Driver

    environment = dict(driver.env)
    # An inherited GLib debug setting must not enable diagnostics in the controls.
    environment.pop("G_MESSAGES_DEBUG", None)
    driver = Driver(driver.kind, driver.cli, driver.client, environment, driver.root,
                    driver.evidence, driver.timeout)
    driver.evidence.append({"observation": "global-option-environment",
                            "data": {"G_MESSAGES_DEBUG": None}})
    if name == "global-options-gl-drivers":
        for drivers in (("mesa-git", "default"), ("default", "mesa-git")):
            selected = ":".join(drivers)
            environment["FLATPAK_GL_DRIVERS"] = selected
            driver.evidence.append({"observation": "global-option-environment",
                                    "data": {"FLATPAK_GL_DRIVERS": selected}})
            output = _output(driver, "--gl-drivers")
            driver.check(output.split() == list(drivers),
                         f"active GL drivers must match override order {drivers}: {output!r}")
        return

    app = f"app/{fixture['app']}/{fixture['arch']}/{fixture['branch']}"
    if name == "global-options-ostree-verbose":
        repo = str(Path(fixture["directory"]) / "A")
        arguments: tuple[str, ...] = ("repo", f"--commits={app}", repo)
        control = driver.cli_call(*arguments)
        driver.check(fixture["commits"]["A"] in control.stdout,
                     "commit query must identify the independently prepared A commit")
        driver.check(not _diagnostics(driver, control, control.stdout),
                     "initial repository control emitted diagnostics")
        for flags in ((), ("--ostree-verbose",), (), ("--ostree-verbose",), ()):
            diagnostics = _diagnostics(driver, driver.cli_call(*flags, *arguments), control.stdout)
            driver.check(bool(diagnostics) == bool(flags),
                         f"repository diagnostics must follow --ostree-verbose: {diagnostics}")
        return

    if name == "global-options-verbose":
        runtime = f"runtime/{fixture['runtime']}/{fixture['arch']}/{fixture['branch']}"
        driver.cli_success("remote-add", "--user", "--no-gpg-verify", "verbosity-fixture", url)
        driver.cli_success("install", "--user", "--noninteractive", "verbosity-fixture", app)
        expected = {app: fixture["commits"]["A"], runtime: fixture["runtime_commit"]}

        def unchanged() -> None:
            for ref, commit in expected.items():
                output = driver.cli_success("info", "--user", "--show-ref", "--show-commit", ref)
                driver.check(output.split() == [ref, commit],
                             f"verbosity check changed installed {ref}: {output!r}")

        unchanged()
        arguments = ("uninstall", "--user", "--unused", "--noninteractive")
        # Warm up any one-time installation maintenance before comparing levels.
        control = driver.cli_call(*arguments)
        driver.check(bool(control.stdout.strip()), "unused-runtime query returned no result")
        driver.check(not _diagnostics(driver, control, control.stdout),
                     "initial unused-runtime control emitted diagnostics")
        unchanged()
        for order in (((), ("--verbose",), ("-vv",)), (("-vv",), ("--verbose",), ())):
            observed = {}
            for flags in order:
                observed[flags] = _diagnostics(driver, driver.cli_call(*flags, *arguments),
                                               control.stdout)
                unchanged()
            _levels(driver, observed[()], observed[("--verbose",)], observed[("-vv",)])
        return

    raise ValueError(f"unknown controlled global option scenario: {name}")
