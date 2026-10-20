# SPDX-License-Identifier: LGPL-2.1-or-later
"""Canaries for mixed-kind search assertions and optional interface handling."""

import gzip
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import search_kind_scenarios as search
from fixture_manifest import parse_fixture
from run import ContractFailure, Driver, PrerequisiteError, RepositoryServer, UnsupportedCapability
from test_fixture_manifest import rich


class SearchKindTests(unittest.TestCase):
    def exercise(self, mutation: str = "", help_text: str = "  --app  Apps\n  --runtime  Runtimes",
                 *, prepared: bool = True) -> list[tuple[str, ...]]:
        calls: list[tuple[str, ...]] = []

        def cli(*args: str) -> str:
            calls.append(args)
            if args == ("search", "--help"):
                return help_text
            if args[0] != "search":
                return ""
            if args[-1] == "nonexistentkindneedle":
                return f"{search.APP}\ttest" if mutation == "absent" else "No matches found"
            app = "--app" in args
            runtime = "--runtime" in args
            expected = {search.APP, search.RUNTIME}
            if app and not runtime:
                expected = {search.APP}
            if runtime and not app:
                expected = {search.RUNTIME}
            if mutation == "ignore":
                expected = {search.APP, search.RUNTIME}
            if mutation == "intersection" and app and runtime:
                expected = set()
            if mutation == "default" and not app and not runtime:
                expected = {search.APP}
            if mutation == "control":
                expected.add(search.APP + "Control")
            if mutation == "duplicate":
                return f"{search.APP}\ttest\n{search.APP}\ttest"
            return "\n".join(f"{identity}\ttest" for identity in sorted(expected))

        fixture = parse_fixture(rich())
        if not prepared:
            del fixture["queries"]["search_kind_repo"]
        with tempfile.TemporaryDirectory() as temporary:
            driver = Driver("cli", "/target/flatpak", None, {}, Path(temporary), [], 1)
            with patch.object(driver, "cli_success", side_effect=cli), patch.object(
                search, "_refs", return_value={"unexpected/deployment"} if mutation == "deploy"
                else set(),
            ):
                search.run(driver, RepositoryServer(Path(temporary)), "", fixture,
                           "search-kind-filters")
        return calls

    def test_all_four_modes_and_negative_terms_are_executed(self) -> None:
        calls = self.exercise()
        searches = [call for call in calls if call[0] == "search" and "--help" not in call]
        self.assertEqual(len(searches), 8)
        for flags in ((), ("--app",), ("--runtime",), ("--app", "--runtime")):
            for term in (search.TERM, "nonexistentkindneedle"):
                self.assertIn(("search", "--user", "--columns=application,branch", *flags, term),
                              searches)

    def test_broken_filters_and_negative_controls_fail(self) -> None:
        for mutation in ("ignore", "intersection", "default", "control", "duplicate",
                         "absent", "deploy"):
            with self.subTest(mutation=mutation), self.assertRaises(ContractFailure):
                self.exercise(mutation)

    def test_missing_options_are_unsupported_before_unknown_options_are_called(self) -> None:
        for help_text in ("  --arch  Architecture", "  --app  Apps", "  --runtime  Runtimes",
                          "  --appstream  Metadata\n  --runtime-extra  Other"):
            with self.subTest(help=help_text), self.assertRaises(UnsupportedCapability):
                self.exercise(help_text=help_text)

    def test_old_fixtures_require_regeneration(self) -> None:
        with self.assertRaises(PrerequisiteError):
            self.exercise(prepared=False)

    def test_help_failure_is_not_hidden_as_unsupported(self) -> None:
        driver = Driver("cli", "/target/flatpak", None, {}, Path("."), [], 1)
        with patch.object(driver, "cli_success", side_effect=ContractFailure("broken help")), \
                self.assertRaises(ContractFailure):
            search.run(driver, RepositoryServer(Path(".")), "", parse_fixture(rich()),
                       "search-kind-filters")

    def test_old_target_never_receives_unknown_options(self) -> None:
        driver = Driver("cli", "/target/flatpak", None, {}, Path("."), [], 1)
        with patch.object(driver, "cli_success", return_value="  --arch  Architecture") as cli:
            with self.assertRaises(UnsupportedCapability):
                search.run(driver, RepositoryServer(Path(".")), "", parse_fixture(rich()),
                           "search-kind-filters")
            cli.assert_called_once_with("search", "--help")

    def test_preparation_exports_both_kinds_and_nonmatching_controls(self) -> None:
        components: dict[str, tuple[str, str, str]] = {}

        def command(args: list[str], *, check: bool) -> None:
            self.assertTrue(check)
            if args[1] != "build-export":
                return
            build = Path(args[-2])
            kind = "runtime" if "--runtime" in args else "app"
            files = build / ("usr" if kind == "runtime" else "files")
            xml = files / f"share/app-info/xmls/{build.name}.xml.gz"
            component = ET.fromstring(gzip.decompress(xml.read_bytes())).find("component")
            assert component is not None
            components[build.name] = (component.attrib["type"],
                                      component.findtext("bundle", ""),
                                      component.findtext("summary", ""))

        with tempfile.TemporaryDirectory() as temporary, patch(
            "search_kind_scenarios.subprocess.run", side_effect=command,
        ):
            self.assertEqual(search.prepare("/reference/flatpak", Path(temporary), "x86_64"),
                             "search-kind-inputs")
        self.assertEqual(set(components), {search.APP, search.RUNTIME,
                                          search.APP + "Control", search.RUNTIME + "Control"})
        for kind, name in (("app", search.APP), ("runtime", search.RUNTIME)):
            for suffix in ("", "Control"):
                component_type, bundle, summary = components[name + suffix]
                self.assertEqual(component_type, "desktop")
                self.assertEqual(bundle, f"{kind}/{name}{suffix}/x86_64/test")
                self.assertEqual(search.TERM in summary, not suffix)


if __name__ == "__main__":
    unittest.main()
