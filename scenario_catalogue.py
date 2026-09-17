# SPDX-License-Identifier: LGPL-2.1-or-later
"""Load executable scenario groups independently of the fixed coverage denominators."""

import re
from pathlib import Path

from catalogue_schema import (
    Behavior,
    CoverageMapping,
    ScenarioGroup,
    indexed,
    parse_inventory,
    parse_mappings,
    parse_scenario_group,
)
from json_validation import load_json


def read_document(path: Path) -> ScenarioGroup:
    return parse_scenario_group(load_json(path), str(path))


def documents(suite: Path) -> list[ScenarioGroup]:
    result = []
    for path in sorted((suite / "scenario-data").rglob("*.json")):
        result.append(read_document(path))
    return result


def load_behaviors(suite: Path) -> list[Behavior]:
    path = suite / "inventory.json"
    result = parse_inventory(load_json(path), str(path))["behaviors"]
    for document in documents(suite):
        result.extend(document["behaviors"])
    indexed(result, "behavior")
    return result


def load_mappings(suite: Path) -> list[CoverageMapping]:
    path = suite / "coverage-data/mapping.json"
    result = parse_mappings(load_json(path), str(path))["cases"]
    for document in documents(suite):
        result.extend(document["mappings"])
    return result


def extension_clients(suite: Path) -> list[tuple[Path, str]]:
    clients: dict[str, Path] = {}
    for document in documents(suite):
        if "client" not in document:
            continue
        entry = document["client"]["entry"]
        source = document["client"]["source"]
        if not re.fullmatch(r"blackbox_[a-z0-9_]+_main", entry):
            raise ValueError(f"invalid client entry point: {entry}")
        if Path(source).name != source or not source.endswith(".c"):
            raise ValueError(f"invalid client source: {source}")
        path = suite / source
        if not path.is_file() or (entry in clients and clients[entry] != path):
            raise ValueError(f"missing or conflicting client source: {source}")
        clients[entry] = path
    return [(path, entry) for entry, path in sorted(clients.items())]
