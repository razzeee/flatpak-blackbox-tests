# SPDX-License-Identifier: LGPL-2.1-or-later
"""Typed configuration for the target and its public development package."""

from dataclasses import dataclass
from pathlib import Path

from json_validation import ValidationError, load_json, object_map, required, string, strings


@dataclass(frozen=True)
class LibraryConfig:
    runtime_library_dirs: tuple[str, ...]
    environment: dict[str, str]
    pkg_config: str = "pkg-config"
    package: str = "flatpak"
    cc: str = "cc"
    soname: str = "libflatpak.so.0"


@dataclass(frozen=True)
class TargetConfig:
    name: str
    cli: str
    adapter: tuple[str, ...]
    environment: dict[str, str]
    unsupported_capabilities: dict[str, str]
    library: LibraryConfig | None = None


def _known(data: dict[str, object], fields: set[str], path: str) -> None:
    for key in data.keys() - fields:
        raise ValidationError(f"{path}.{key}: unknown configuration field")


def parse_environment(value: object, path: str = "environment") -> dict[str, str]:
    result = {}
    for key, item in object_map(value, path).items():
        string(key, path, nonempty=True)
        if "=" in key:
            raise ValidationError(f"{path}.{key}: environment names cannot contain '='")
        result[key] = string(item, f"{path}.{key}")
    return result


def _library(value: object, path: str) -> LibraryConfig:
    data = object_map(value, path)
    _known(data, {"runtime_library_dirs", "environment", "pkg_config", "package", "cc", "soname"},
           path)
    return LibraryConfig(
        runtime_library_dirs=tuple(strings(data.get("runtime_library_dirs", []),
                                          f"{path}.runtime_library_dirs", nonempty=True)),
        environment=parse_environment(data.get("environment", {}), f"{path}.environment"),
        pkg_config=string(data.get("pkg_config", "pkg-config"),
                          f"{path}.pkg_config", nonempty=True),
        package=string(data.get("package", "flatpak"), f"{path}.package", nonempty=True),
        cc=string(data.get("cc", "cc"), f"{path}.cc", nonempty=True),
        soname=string(data.get("soname", "libflatpak.so.0"), f"{path}.soname", nonempty=True),
    )


def parse_target(value: object, path: str = "target") -> TargetConfig:
    data = object_map(value, path)
    _known(data, {"name", "cli", "adapter", "environment", "unsupported_capabilities", "library"},
           path)
    adapter = strings(required(data, "adapter", path), f"{path}.adapter")
    if not adapter or not adapter[0]:
        raise ValidationError(f"{path}.adapter: expected a nonempty executable argument")
    unsupported = {}
    for capability, reason in object_map(data.get("unsupported_capabilities", {}),
                                         f"{path}.unsupported_capabilities").items():
        string(capability, f"{path}.unsupported_capabilities", nonempty=True)
        unsupported[capability] = string(reason, f"{path}.unsupported_capabilities.{capability}",
                                         nonempty=True)
    library = data.get("library")
    return TargetConfig(
        name=string(required(data, "name", path), f"{path}.name", nonempty=True),
        cli=string(required(data, "cli", path), f"{path}.cli", nonempty=True),
        adapter=tuple(adapter),
        environment=parse_environment(data.get("environment", {}), f"{path}.environment"),
        unsupported_capabilities=unsupported,
        library=None if library is None else _library(library, f"{path}.library"),
    )


def load_target(path: Path) -> TargetConfig:
    return parse_target(load_json(path), "target")
