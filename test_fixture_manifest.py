# SPDX-License-Identifier: LGPL-2.1-or-later
"""Public fixture parser contracts, including the prepared schema-1 format."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from fixture_manifest import FixtureContracts, load_fixture, parse_fixture
from json_validation import JSONValue, ValidationError, json_value, load_json


def basic() -> dict[str, object]:
    return {
        "schema": 1, "arch": "x86_64", "app": "org.example.App",
        "runtime": "org.example.Platform", "branch": "test",
        "commits": {"A": "app-a", "B": "app-b"},
        "runtime_commit": "runtime-a", "sha256": {"A/config": "digest"},
    }


def rich() -> dict[str, object]:
    return {
        **basic(), "directory": "/fixtures", "reference_version": "Flatpak 1.18.2",
        "compiler": "cc", "assets": {"runtime_tree": "runtime", "app_tree": "app"},
        "sizes": {"A": {"app/ref": {"installed": 100, "download": 20}}},
        "build": {
            "gpg_home": "gpg", "public_key": "public.gpg", "key_id": "key",
            "signed_repo": "signed", "bundle": "app.flatpak", "usb_repo": "usb",
            "collection_id": "org.example.Collection",
            "usb_commits": {"app": "app-a", "runtime": "runtime-a"},
            "inheritance_tree": "inheritance", "permissions_repo": "permissions",
        },
        "build_options": {
            "oci": "image", "oci_ref": "app/ref", "arch": "i386", "arch_repo": "foreign",
            "arch_commits": {"app": "foreign-app", "runtime": "foreign-runtime"},
        },
        "queries": {
            "app": "org.example.Query", "second": "org.example.Second",
            "extension": "org.example.Query.Data", "foreign_arch": "aarch64",
            "versions": {"A": {
                "repo": "query-A", "appstream": "cache.xml",
                "refs": {"app/ref": {
                    "commit": "query-a", "metadata": "metadata", "installed": 10, "download": 2,
                }},
            }},
            "bundle_urls": "urls.flatpak", "bundle_urls_size": 12,
            "bundle_plain": "plain.flatpak", "bundle_plain_size": 12,
            "policy_repo": "policy", "policy_ref": "app/policy", "policy_commit": "policy-a",
            "policy_metadata": "policy-metadata", "policy_extensions": [{
                "ref": "runtime/extension", "commit": "extension-a", "no_autodownload": False,
                "autodelete": True, "should_download": True, "should_delete": False,
            }],
            "appstream": "appstream.xml", "icons": {"64": "icon.png"},
            "selection_repo": "selection", "selection_commits": {
                "app/org.flatpak.Selection/x86_64/test": "selection-a",
                "app/org.flatpak.SelectionOther/x86_64/test": "other-a",
                "runtime/org.flatpak.SelectionPlatform/x86_64/test": "platform-a",
                "runtime/org.flatpak.Selection.Locale/x86_64/test": "locale-a",
            },
        },
        "extras": {
            "transactions": {
                "directory": "transactions", "apps": ["org.example.First", "org.example.Second"],
                "commits": {"A": {"app/ref": "tx-a"}},
                "payloads": {"A": {"app/ref": ["objects/payload.filez"]}},
                "metadata": {"A:org.example.First": "[Application]\n"}, "eol_reason": "Retired",
            },
            "auth": {"directory": "auth", "ref": "runtime/auth", "commit": "auth-a",
                     "payloads": ["objects/auth.filez"]},
        },
        "lifecycle_extra": {
            "reference_version": "Flatpak 1.18.2", "foreign_bundle": "foreign.flatpak",
            "image_A": "image-A", "payload_A": "payload-A",
            "image_B": "image-B", "payload_B": "payload-B",
            "signed_bundle": "signed.flatpak", "sideload_native": "native", "sideload": "usb",
            "usage_repo": "usage", "usage_app": "app/usage", "usage_sdk": "runtime/sdk",
            "usage_metadata": "usage-metadata", "usage_app_commit": "usage-a",
            "usage_sdk_commit": "sdk-a", "trigger_app": "org.example.Trigger",
            "triggers": {"A": {"repo": "triggers-A", "commit": "trigger-a"}},
        },
    }


def malformed_nodes(value: JSONValue, path: str = "fixture") -> list[tuple[JSONValue, str]]:
    """Replace each node once, keeping its ancestors valid to exercise its validator."""
    cases: list[tuple[JSONValue, str]] = []
    if isinstance(value, dict):
        cases.append(([], path))
        for key, item in value.items():
            cases.extend(({**value, key: bad}, field)
                         for bad, field in malformed_nodes(item, f"{path}.{key}"))
    elif isinstance(value, list):
        cases.append(({}, path))
        for index, item in enumerate(value):
            for bad, field in malformed_nodes(item, f"{path}[{index}]"):
                changed = list(value)
                changed[index] = bad
                cases.append((changed, field))
    elif isinstance(value, bool):
        cases.append((1, path))
    elif isinstance(value, int):
        cases.extend([(True, path), (-1, path), (1.5, path), ("1", path)])
    elif isinstance(value, str):
        cases.extend([(None, path), (42, path), ("bad\0string", path)])
    return cases


class FixtureManifestTests(unittest.TestCase):
    def test_contract_fixture_requires_every_ref_and_version_oracle(self) -> None:
        aliases = ("one", "two", "platform", "sdk", "extension", "shared", "one_debug",
                   "two_debug", "platform_debug", "sdk_debug")
        refs = {alias: f"runtime/org.example.{alias}/x86_64/test" for alias in aliases}
        contracts: FixtureContracts = {
            "refs": refs,
            "repos": {version: version for version in ("A", "RUNTIME", "EXTENSION", "APP")},
            "commits": {version: {ref: "commit" for ref in refs.values()}
                        for version in ("A", "RUNTIME", "EXTENSION", "APP")},
        }
        self.assertEqual(parse_fixture({**basic(), "contracts": contracts})["contracts"], contracts)
        for version in contracts["repos"]:
            for ref in refs.values():
                changed: FixtureContracts = {**contracts, "commits": {
                    **contracts["commits"], version: {
                        key: commit for key, commit in contracts["commits"][version].items()
                        if key != ref}}}
                with self.subTest(version=version, ref=ref), self.assertRaisesRegex(
                    ValidationError,
                    re.escape(f"fixture.contracts.commits.{version}.{ref}: required")
                ):
                    parse_fixture({**basic(), "contracts": changed})
        for alias in aliases:
            changed = {**contracts, "refs": {key: ref for key, ref in refs.items() if key != alias}}
            with self.subTest(alias=alias), self.assertRaisesRegex(
                ValidationError, re.escape(f"fixture.contracts.refs.{alias}: required")
            ):
                parse_fixture({**basic(), "contracts": changed})

    def test_basic_groups_are_optional(self) -> None:
        value = basic()
        self.assertEqual(parse_fixture(value), value)

    def test_rich_round_trip(self) -> None:
        value = rich()
        parsed = parse_fixture(value)
        self.assertEqual(parsed, value)
        self.assertEqual(parse_fixture(json.loads(json.dumps(parsed))), value)

    def test_every_known_node_is_validated(self) -> None:
        for malformed, path in malformed_nodes(json_value(rich())):
            with (self.subTest(path=path, malformed=malformed),
                  self.assertRaisesRegex(ValidationError, re.escape(path) + ":")):
                parse_fixture(malformed)

    def test_common_fields_are_required(self) -> None:
        for key in basic():
            value = basic()
            del value[key]
            with (self.subTest(key=key),
                  self.assertRaisesRegex(ValidationError, f"fixture.{key}: required")):
                parse_fixture(value)

    def test_missing_nested_field_has_full_path(self) -> None:
        cases: list[tuple[dict[str, object], str]] = [
            ({"assets": {"runtime_tree": "runtime"}}, "assets.app_tree"),
            ({"sizes": {"A": {"app/ref": {"installed": 1}}}}, "sizes.A.app/ref.download"),
            ({"extras": {"auth": {"directory": "auth", "ref": "ref", "commit": "a"}}},
             "extras.auth.payloads"),
            ({"build_options": {"oci": "image"}}, "build_options.oci_ref"),
        ]
        for fields, path in cases:
            with (self.subTest(path=path), self.assertRaisesRegex(
                    ValidationError, re.escape(f"fixture.{path}: required"))):
                parse_fixture({**basic(), **fields})

    def test_conditional_inputs_are_optional(self) -> None:
        value = rich()
        options = value["build_options"]
        lifecycle = value["lifecycle_extra"]
        queries = value["queries"]
        assert isinstance(options, dict) and isinstance(lifecycle, dict)
        assert isinstance(queries, dict)
        for key in ("arch", "arch_repo", "arch_commits"):
            del options[key]
        del lifecycle["foreign_bundle"]
        del queries["selection_repo"]
        del queries["selection_commits"]
        value["extras"] = {}
        self.assertEqual(parse_fixture(value), value)

    def test_selection_repository_requires_commit_oracles(self) -> None:
        value = rich()
        queries = value["queries"]
        assert isinstance(queries, dict)
        del queries["selection_commits"]
        with self.assertRaisesRegex(ValidationError, "fixture.queries.selection_commits: required"):
            parse_fixture(value)

    def test_selection_commit_oracles_require_all_native_refs(self) -> None:
        original = parse_fixture(rich())["queries"]["selection_commits"]
        invalid = [{}, *({key: item for key, item in original.items() if key != ref}
                         for ref in original)]
        for commits in invalid:
            value = rich()
            queries = value["queries"]
            assert isinstance(queries, dict)
            queries["selection_commits"] = commits
            with self.subTest(commits=commits), self.assertRaisesRegex(
                ValidationError, r"fixture.queries.selection_commits.*: required field is missing"
            ):
                parse_fixture(value)
        value = rich()
        value["arch"] = "aarch64"
        with self.assertRaisesRegex(ValidationError, r"selection_commits.*aarch64/test: required"):
            parse_fixture(value)

    def test_unknown_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "fixture.observation: unknown"):
            parse_fixture({**basic(), "observation": {"arbitrary": True}})
        with self.assertRaisesRegex(ValidationError, "fixture.extras.other: unknown"):
            parse_fixture({**basic(), "extras": {"other": {}}})

    def test_transactions_require_two_apps(self) -> None:
        for apps in ([], ["org.flatpak.SingleApp"]):
            value = rich()
            extras = value["extras"]
            assert isinstance(extras, dict)
            transactions = extras["transactions"]
            assert isinstance(transactions, dict)
            transactions["apps"] = apps
            with self.subTest(apps=apps), self.assertRaisesRegex(
                ValidationError, r"fixture.extras.transactions.apps: expected at least two apps"
            ):
                parse_fixture(value)

    def test_unsupported_schema(self) -> None:
        with self.assertRaisesRegex(ValidationError, "fixture.schema: expected supported schema 1"):
            parse_fixture({**basic(), "schema": 2})

    def test_load_reports_filename_and_field(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fixture.json"
            path.write_text(json.dumps(basic()))
            self.assertEqual(load_fixture(path), basic())
            path.write_text(json.dumps({**basic(), "commits": {"A": False}}))
            with self.assertRaisesRegex(ValidationError, re.escape(f"{path}.commits.A:")):
                load_fixture(path)
            path.write_text('{"schema": 1, "schema": 1}')
            with self.assertRaisesRegex(ValidationError, "duplicate JSON key"):
                load_fixture(path)

    def test_current_prepared_fixture(self) -> None:
        path = (Path(__file__).resolve().parents[2] / "_build/blackbox-artifacts"
                / "expanded-reviewed-fixtures/fixture.json")
        if not path.exists():
            self.skipTest("reviewed prepared fixture is not available in this checkout")
        self.assertEqual(load_fixture(path), load_json(path))


if __name__ == "__main__":
    unittest.main()
