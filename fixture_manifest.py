# SPDX-License-Identifier: LGPL-2.1-or-later
"""Validated schema-1 fixture inputs shared by preparation and scenarios."""

from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict

from json_validation import (
    ValidationError,
    array,
    boolean,
    integer,
    load_json,
    object_map,
    required,
    schema_one,
    string,
    string_map,
    strings,
)


class FixtureAssets(TypedDict):
    runtime_tree: str
    app_tree: str


class FixtureSize(TypedDict):
    installed: int
    download: int


class FixtureBuild(TypedDict):
    gpg_home: str
    public_key: str
    key_id: str
    signed_repo: str
    bundle: str
    usb_repo: str
    collection_id: str
    usb_commits: dict[str, str]
    inheritance_tree: str
    permissions_repo: str


class _BuildOptionsRequired(TypedDict):
    oci: str
    oci_ref: str


class FixtureBuildOptions(_BuildOptionsRequired, total=False):
    arch: str
    arch_repo: str
    arch_commits: dict[str, str]


class FixtureQueryRef(FixtureSize):
    commit: str
    metadata: str


class FixtureQueryVersion(TypedDict):
    repo: str
    refs: dict[str, FixtureQueryRef]
    appstream: str


class FixturePolicyExtension(TypedDict):
    ref: str
    commit: str
    no_autodownload: bool
    autodelete: bool
    should_download: bool
    should_delete: bool


class _QueriesRequired(TypedDict):
    app: str
    second: str
    extension: str
    foreign_arch: str
    versions: dict[str, FixtureQueryVersion]
    bundle_urls: str
    bundle_urls_size: int
    bundle_plain: str
    bundle_plain_size: int
    policy_repo: str
    policy_ref: str
    policy_commit: str
    policy_metadata: str
    policy_extensions: list[FixturePolicyExtension]
    appstream: str
    icons: dict[str, str]


class FixtureQueries(_QueriesRequired, total=False):
    selection_repo: str
    selection_commits: dict[str, str]


class FixtureTransactions(TypedDict):
    directory: str
    apps: list[str]
    commits: dict[str, dict[str, str]]
    payloads: dict[str, dict[str, list[str]]]
    metadata: dict[str, str]
    eol_reason: str


class FixtureAuth(TypedDict):
    directory: str
    ref: str
    commit: str
    payloads: list[str]


class FixtureExtras(TypedDict, total=False):
    transactions: FixtureTransactions
    auth: FixtureAuth


class FixtureTrigger(TypedDict):
    repo: str
    commit: str


class _LifecycleRequired(TypedDict):
    reference_version: str
    image_A: str
    payload_A: str
    image_B: str
    payload_B: str
    signed_bundle: str
    sideload_native: str
    sideload: str
    usage_repo: str
    usage_app: str
    usage_sdk: str
    usage_metadata: str
    usage_app_commit: str
    usage_sdk_commit: str
    trigger_app: str
    triggers: dict[str, FixtureTrigger]


class FixtureLifecycleExtra(_LifecycleRequired, total=False):
    foreign_bundle: str


class _FixtureRequired(TypedDict):
    schema: int
    arch: str
    app: str
    runtime: str
    branch: str
    commits: dict[str, str]
    runtime_commit: str
    sha256: dict[str, str]


class FixtureManifest(_FixtureRequired, total=False):
    directory: str
    reference_version: str
    compiler: str
    assets: FixtureAssets
    sizes: dict[str, dict[str, FixtureSize]]
    build: FixtureBuild
    build_options: FixtureBuildOptions
    queries: FixtureQueries
    extras: FixtureExtras
    lifecycle_extra: FixtureLifecycleExtra


class FixtureBuildEntries(TypedDict, total=False):
    build: FixtureBuild
    build_options: FixtureBuildOptions


class FixtureQueryEntries(TypedDict):
    queries: FixtureQueries


def _text(data: dict[str, object], key: str, path: str) -> str:
    return string(required(data, key, path), f"{path}.{key}")


def _size(data: dict[str, object], key: str, path: str) -> int:
    return integer(required(data, key, path), f"{path}.{key}", minimum=0)


def _flag(data: dict[str, object], key: str, path: str) -> bool:
    return boolean(required(data, key, path), f"{path}.{key}")


def _known(data: dict[str, object], result: Mapping[str, object], path: str) -> None:
    # Schema 1 has no arbitrary extension fields. Do not silently drop input.
    for key in data.keys() - result.keys():
        raise ValidationError(f"{path}.{key}: unknown fixture field")


def parse_assets(value: object, path: str) -> FixtureAssets:
    data = object_map(value, path)
    result: FixtureAssets = {
        "runtime_tree": _text(data, "runtime_tree", path),
        "app_tree": _text(data, "app_tree", path),
    }
    _known(data, result, path)
    return result


def parse_size(value: object, path: str) -> FixtureSize:
    data = object_map(value, path)
    result: FixtureSize = {
        "installed": _size(data, "installed", path),
        "download": _size(data, "download", path),
    }
    _known(data, result, path)
    return result


def parse_sizes(value: object, path: str) -> dict[str, dict[str, FixtureSize]]:
    return {
        version: {ref: parse_size(size, f"{path}.{version}.{ref}")
                  for ref, size in object_map(refs, f"{path}.{version}").items()}
        for version, refs in object_map(value, path).items()
    }


def parse_build(value: object, path: str) -> FixtureBuild:
    data = object_map(value, path)
    result: FixtureBuild = {
        "gpg_home": _text(data, "gpg_home", path),
        "public_key": _text(data, "public_key", path),
        "key_id": _text(data, "key_id", path),
        "signed_repo": _text(data, "signed_repo", path),
        "bundle": _text(data, "bundle", path),
        "usb_repo": _text(data, "usb_repo", path),
        "collection_id": _text(data, "collection_id", path),
        "usb_commits": string_map(required(data, "usb_commits", path), f"{path}.usb_commits"),
        "inheritance_tree": _text(data, "inheritance_tree", path),
        "permissions_repo": _text(data, "permissions_repo", path),
    }
    _known(data, result, path)
    return result


def parse_build_options(value: object, path: str) -> FixtureBuildOptions:
    data = object_map(value, path)
    result: FixtureBuildOptions = {
        "oci": _text(data, "oci", path), "oci_ref": _text(data, "oci_ref", path),
    }
    if "arch" in data:
        result["arch"] = _text(data, "arch", path)
    if "arch_repo" in data:
        result["arch_repo"] = _text(data, "arch_repo", path)
    if "arch_commits" in data:
        result["arch_commits"] = string_map(data["arch_commits"], f"{path}.arch_commits")
    _known(data, result, path)
    return result


def parse_query_ref(value: object, path: str) -> FixtureQueryRef:
    data = object_map(value, path)
    result: FixtureQueryRef = {
        "commit": _text(data, "commit", path), "metadata": _text(data, "metadata", path),
        "installed": _size(data, "installed", path), "download": _size(data, "download", path),
    }
    _known(data, result, path)
    return result


def parse_query_version(value: object, path: str) -> FixtureQueryVersion:
    data = object_map(value, path)
    result: FixtureQueryVersion = {
        "repo": _text(data, "repo", path), "appstream": _text(data, "appstream", path),
        "refs": {ref: parse_query_ref(item, f"{path}.refs.{ref}")
                 for ref, item in object_map(required(data, "refs", path), f"{path}.refs").items()},
    }
    _known(data, result, path)
    return result


def parse_policy_extension(value: object, path: str) -> FixturePolicyExtension:
    data = object_map(value, path)
    result: FixturePolicyExtension = {
        "ref": _text(data, "ref", path), "commit": _text(data, "commit", path),
        "no_autodownload": _flag(data, "no_autodownload", path),
        "autodelete": _flag(data, "autodelete", path),
        "should_download": _flag(data, "should_download", path),
        "should_delete": _flag(data, "should_delete", path),
    }
    _known(data, result, path)
    return result


def parse_queries(value: object, path: str, *, arch: str) -> FixtureQueries:
    data = object_map(value, path)
    result: FixtureQueries = {
        "app": _text(data, "app", path), "second": _text(data, "second", path),
        "extension": _text(data, "extension", path),
        "foreign_arch": _text(data, "foreign_arch", path),
        "versions": {version: parse_query_version(item, f"{path}.versions.{version}")
                     for version, item in object_map(
                         required(data, "versions", path), f"{path}.versions").items()},
        "bundle_urls": _text(data, "bundle_urls", path),
        "bundle_urls_size": _size(data, "bundle_urls_size", path),
        "bundle_plain": _text(data, "bundle_plain", path),
        "bundle_plain_size": _size(data, "bundle_plain_size", path),
        "policy_repo": _text(data, "policy_repo", path),
        "policy_ref": _text(data, "policy_ref", path),
        "policy_commit": _text(data, "policy_commit", path),
        "policy_metadata": _text(data, "policy_metadata", path),
        "policy_extensions": [parse_policy_extension(item, f"{path}.policy_extensions[{index}]")
                              for index, item in enumerate(array(
                                  required(data, "policy_extensions", path),
                                  f"{path}.policy_extensions"))],
        "appstream": _text(data, "appstream", path),
        "icons": string_map(required(data, "icons", path), f"{path}.icons"),
    }
    if "selection_repo" in data:
        result["selection_repo"] = _text(data, "selection_repo", path)
        result["selection_commits"] = string_map(
            required(data, "selection_commits", path), f"{path}.selection_commits")
        # These are the four additional refs exported by the selection fixture.
        # Its base runtime uses the manifest's existing runtime_commit oracle.
        for kind, name in (("app", "org.flatpak.Selection"),
                           ("app", "org.flatpak.SelectionOther"),
                           ("runtime", "org.flatpak.SelectionPlatform"),
                           ("runtime", "org.flatpak.Selection.Locale")):
            ref = f"{kind}/{name}/{arch}/test"
            if ref not in result["selection_commits"]:
                raise ValidationError(f"{path}.selection_commits.{ref}: required field is missing")
            string(result["selection_commits"][ref],
                   f"{path}.selection_commits.{ref}", nonempty=True)
    _known(data, result, path)
    return result


def parse_transactions(value: object, path: str) -> FixtureTransactions:
    data = object_map(value, path)
    apps = strings(required(data, "apps", path), f"{path}.apps")
    if len(apps) < 2:
        raise ValidationError(f"{path}.apps: expected at least two apps")
    result: FixtureTransactions = {
        "directory": _text(data, "directory", path),
        "apps": apps,
        "commits": {version: string_map(item, f"{path}.commits.{version}")
                    for version, item in object_map(
                        required(data, "commits", path), f"{path}.commits").items()},
        "payloads": {version: {
            ref: strings(items, f"{path}.payloads.{version}.{ref}")
            for ref, items in object_map(refs, f"{path}.payloads.{version}").items()}
            for version, refs in object_map(
                required(data, "payloads", path), f"{path}.payloads").items()},
        "metadata": string_map(required(data, "metadata", path), f"{path}.metadata"),
        "eol_reason": _text(data, "eol_reason", path),
    }
    _known(data, result, path)
    return result


def parse_auth(value: object, path: str) -> FixtureAuth:
    data = object_map(value, path)
    result: FixtureAuth = {
        "directory": _text(data, "directory", path), "ref": _text(data, "ref", path),
        "commit": _text(data, "commit", path),
        "payloads": strings(required(data, "payloads", path), f"{path}.payloads"),
    }
    _known(data, result, path)
    return result


def parse_extras(value: object, path: str) -> FixtureExtras:
    data = object_map(value, path)
    result: FixtureExtras = {}
    if "transactions" in data:
        result["transactions"] = parse_transactions(data["transactions"], f"{path}.transactions")
    if "auth" in data:
        result["auth"] = parse_auth(data["auth"], f"{path}.auth")
    _known(data, result, path)
    return result


def parse_trigger(value: object, path: str) -> FixtureTrigger:
    data = object_map(value, path)
    result: FixtureTrigger = {
        "repo": _text(data, "repo", path), "commit": _text(data, "commit", path),
    }
    _known(data, result, path)
    return result


def parse_lifecycle_extra(value: object, path: str) -> FixtureLifecycleExtra:
    data = object_map(value, path)
    result: FixtureLifecycleExtra = {
        "reference_version": _text(data, "reference_version", path),
        "image_A": _text(data, "image_A", path), "payload_A": _text(data, "payload_A", path),
        "image_B": _text(data, "image_B", path), "payload_B": _text(data, "payload_B", path),
        "signed_bundle": _text(data, "signed_bundle", path),
        "sideload_native": _text(data, "sideload_native", path),
        "sideload": _text(data, "sideload", path), "usage_repo": _text(data, "usage_repo", path),
        "usage_app": _text(data, "usage_app", path), "usage_sdk": _text(data, "usage_sdk", path),
        "usage_metadata": _text(data, "usage_metadata", path),
        "usage_app_commit": _text(data, "usage_app_commit", path),
        "usage_sdk_commit": _text(data, "usage_sdk_commit", path),
        "trigger_app": _text(data, "trigger_app", path),
        "triggers": {version: parse_trigger(item, f"{path}.triggers.{version}")
                     for version, item in object_map(
                         required(data, "triggers", path), f"{path}.triggers").items()},
    }
    if "foreign_bundle" in data:
        result["foreign_bundle"] = _text(data, "foreign_bundle", path)
    _known(data, result, path)
    return result


def parse_fixture(value: object, path: str = "fixture") -> FixtureManifest:
    """Validate every provided field, leaving supplemental groups optional for --basic."""
    data = object_map(value, path)
    schema_one(data, path)
    commits = string_map(required(data, "commits", path), f"{path}.commits", nonempty=True)
    for version in ("A", "B"):
        if version not in commits:
            raise ValidationError(f"{path}.commits.{version}: required field is missing")
    result: FixtureManifest = {
        "schema": 1,
        "arch": string(required(data, "arch", path), f"{path}.arch", nonempty=True),
        "app": string(required(data, "app", path), f"{path}.app", nonempty=True),
        "runtime": string(required(data, "runtime", path), f"{path}.runtime", nonempty=True),
        "branch": string(required(data, "branch", path), f"{path}.branch", nonempty=True),
        "commits": commits,
        "runtime_commit": _text(data, "runtime_commit", path),
        "sha256": string_map(required(data, "sha256", path), f"{path}.sha256"),
    }
    if "directory" in data:
        result["directory"] = _text(data, "directory", path)
    if "reference_version" in data:
        result["reference_version"] = _text(data, "reference_version", path)
    if "compiler" in data:
        result["compiler"] = _text(data, "compiler", path)
    if "assets" in data:
        result["assets"] = parse_assets(data["assets"], f"{path}.assets")
    if "sizes" in data:
        result["sizes"] = parse_sizes(data["sizes"], f"{path}.sizes")
    if "build" in data:
        result["build"] = parse_build(data["build"], f"{path}.build")
    if "build_options" in data:
        result["build_options"] = parse_build_options(
            data["build_options"], f"{path}.build_options")
    if "queries" in data:
        result["queries"] = parse_queries(data["queries"], f"{path}.queries", arch=result["arch"])
    if "extras" in data:
        result["extras"] = parse_extras(data["extras"], f"{path}.extras")
    if "lifecycle_extra" in data:
        result["lifecycle_extra"] = parse_lifecycle_extra(
            data["lifecycle_extra"], f"{path}.lifecycle_extra")
    _known(data, result, path)
    return result


def load_fixture(path: Path) -> FixtureManifest:
    return parse_fixture(load_json(path), str(path))
