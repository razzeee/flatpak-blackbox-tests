# SPDX-License-Identifier: LGPL-2.1-or-later
"""Checked static inputs for coverage and executable scenario catalogues.

Unknown fields are retained as JSON extensions, without assigning them coverage
meaning. Known optional metadata is checked even when no consumer needs it.
Legacy minimal catalogues may omit surface sources and executable capabilities;
those become empty lists. Gap records need only an ID and a gap explanation.
"""

import re
from pathlib import Path
from typing import Literal, TypedDict, TypeVar

from catalogue import Catalogue, Source
from json_validation import ValidationError, array, load_json, object_map, required, string
from typed_json import parse_typed

Interface = Literal["cli", "library"]
Profile = Literal["user", "system", "any"]


class Identified(TypedDict):
    id: str


class BehaviorMetadata(Identified, total=False):
    description: str
    preconditions: str | list[str]
    expected: str | list[str]
    references: list[str]
    handler: str
    execution_environment: str
    notes: list[str]


class Behavior(BehaviorMetadata, total=False):
    gap: str
    scenario: str
    profile: Profile
    drivers: list[Interface]
    required_capabilities: list[str]


class ExecutableBehavior(BehaviorMetadata):
    scenario: str
    profile: Profile
    drivers: list[Interface]
    required_capabilities: list[str]


class GapRequired(BehaviorMetadata):
    gap: str


class GapBehavior(GapRequired, total=False):
    profile: Profile
    drivers: list[Interface]
    required_capabilities: list[str]


class SurfaceAssertion(Identified):
    rationale: str


class MappingRequired(TypedDict):
    behavior_id: str
    driver: Interface
    profile: Profile
    requirements: list[str]
    rationale: str


class CoverageMapping(MappingRequired, total=False):
    surface_assertions: list[SurfaceAssertion]
    equivalent_options: list[SurfaceAssertion]
    notes: list[str]


class Client(TypedDict):
    source: str
    entry: str


class Inventory(TypedDict):
    schema: int
    behaviors: list[Behavior]


class ScenarioGroupRequired(Inventory):
    mappings: list[CoverageMapping]


class ScenarioGroup(ScenarioGroupRequired, total=False):
    client: Client
    notes: list[str]


class MappingDocument(TypedDict):
    schema: int
    cases: list[CoverageMapping]


class Requirement(Identified):
    interface: Interface
    profile: Profile
    category: str
    description: str
    sources: list[Source]
    surfaces: list[str]
    required_capabilities: list[str]


class RequirementsRequired(TypedDict):
    schema: int
    scope: Interface
    limitations: list[str]
    requirements: list[Requirement]


class RequirementsDocument(RequirementsRequired, total=False):
    includes: list[str]


Item = TypeVar("Item", bound=Identified)


def indexed(items: list[Item], label: str) -> dict[str, Item]:
    result: dict[str, Item] = {}
    for item in items:
        identifier = string(item["id"], f"{label}.id", nonempty=True)
        if identifier in result:
            raise ValidationError(f"invalid or duplicate {label} ID: {identifier}")
        result[identifier] = item
    return result


def parse_catalogue(value: object, path: str = "catalogue") -> Catalogue:
    data = object_map(value, path)
    surfaces = []
    for index, item in enumerate(array(required(data, "surfaces", path), f"{path}.surfaces")):
        raw_surface = object_map(item, f"{path}.surfaces[{index}]")
        raw_surface.setdefault("sources", [])
        surfaces.append(raw_surface)
    data["surfaces"] = surfaces
    result = parse_typed(data, Catalogue, path)
    indexed(result["surfaces"], "surface")
    commands = {surface["name"] for surface in result["surfaces"]
                if surface["kind"] == "cli-command"}
    for index, surface in enumerate(result["surfaces"]):
        string(surface["name"], f"{path}.surfaces[{index}].name", nonempty=True)
        if "command" in surface and surface["command"] not in commands | {"global"}:
            raise ValidationError(f"{path}.surfaces[{index}].command: unknown command "
                                  f"{surface['command']}")
    return result


def executable_behavior(value: object, path: str = "behavior") -> ExecutableBehavior:
    data = object_map(value, path)
    data.setdefault("required_capabilities", [])
    result = parse_typed(data, ExecutableBehavior, path)
    string(result["scenario"], f"{path}.scenario", nonempty=True)
    if not result["drivers"] or len(set(result["drivers"])) != len(result["drivers"]):
        raise ValidationError(f"{path}.drivers: expected nonempty unique drivers")
    return result


def parse_behavior(value: object, path: str = "behavior") -> Behavior:
    data = object_map(value, path)
    if "scenario" in data:
        # Validate executable-only required fields while retaining a partial shape
        # for inventory consumers that also handle gaps.
        data.setdefault("required_capabilities", [])
        executable_behavior(data, path)
    else:
        parse_typed(data, GapBehavior, path)
        string(required(data, "gap", path), f"{path}.gap", nonempty=True)
    result = parse_typed(data, Behavior, path)
    string(result["id"], f"{path}.id", nonempty=True)
    if "handler" in result:
        module, separator, function = result["handler"].partition(":")
        if not separator or not module.isidentifier() or not function.isidentifier():
            raise ValidationError(
                f"{path}.handler: handler must name a root module and function: {result['id']}")
    return result


def parse_gap(value: object, path: str = "gap") -> GapBehavior:
    """Check inventory gap metadata and require its nonempty explanation."""
    behavior = parse_behavior(value, path)
    result = parse_typed(behavior, GapBehavior, path)
    string(result["gap"], f"{path}.gap", nonempty=True)
    return result


def _behaviors(data: dict[str, object], path: str) -> None:
    data["behaviors"] = [parse_behavior(item, f"{path}.behaviors[{index}]")
                         for index, item in enumerate(array(
                             required(data, "behaviors", path), f"{path}.behaviors"))]


def parse_inventory(value: object, path: str = "inventory") -> Inventory:
    data = object_map(value, path)
    _behaviors(data, path)
    result = parse_typed(data, Inventory, path)
    indexed(result["behaviors"], "behavior")
    return result


def parse_scenario_group(value: object, path: str = "scenario group") -> ScenarioGroup:
    data = object_map(value, path)
    _behaviors(data, path)
    result = parse_typed(data, ScenarioGroup, path)
    indexed(result["behaviors"], "behavior")
    if "client" in result:
        entry = result["client"]["entry"]
        source = result["client"]["source"]
        if not re.fullmatch(r"blackbox_[a-z0-9_]+_main", entry):
            raise ValidationError(f"{path}.client.entry: invalid client entry point: {entry}")
        if Path(source).name != source or not source.endswith(".c"):
            raise ValidationError(f"{path}.client.source: invalid client source: {source}")
    return result


def parse_mappings(value: object, path: str = "mappings") -> MappingDocument:
    return parse_typed(value, MappingDocument, path)


def parse_requirements(value: object, path: str = "requirements") -> RequirementsDocument:
    result = parse_typed(value, RequirementsDocument, path)
    indexed(result["requirements"], "requirement")
    return result


def load_requirements(path: Path) -> RequirementsDocument:
    """Load an index and its direct category shards, or a legacy monolithic document."""
    result = parse_requirements(load_json(path), str(path))
    directory = path.parent.resolve()
    seen: set[Path] = set()
    for include in result.get("includes", []):
        relative = Path(include)
        shard = (directory / relative).resolve()
        if (relative.is_absolute() or relative.suffix != ".json"
                or not shard.is_relative_to(directory) or shard == path.resolve()):
            raise ValidationError(f"{path}: invalid requirement include path: {include}")
        if shard in seen:
            raise ValidationError(f"{path}: duplicate requirement include: {include}")
        seen.add(shard)
        document = parse_requirements(load_json(shard), str(shard))
        if "includes" in document:
            raise ValidationError(f"{shard}: recursive requirement includes are not supported")
        if document["scope"] != result["scope"] or any(
            item["interface"] != result["scope"] for item in document["requirements"]
        ):
            raise ValidationError(f"{shard}: requirement shard has incorrect interface scope")
        result["requirements"].extend(document["requirements"])
        result["limitations"].extend(document["limitations"])
    indexed(result["requirements"], "requirement")
    return result
