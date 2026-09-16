# SPDX-License-Identifier: LGPL-2.1-or-later
"""Small, explicit validators for data entering the standalone suite."""

import json
import math
from pathlib import Path
from typing import TypeAlias

JSONValue: TypeAlias = (
    str | bool | int | float | list["JSONValue"] | dict[str, "JSONValue"] | None
)
JSONObject: TypeAlias = dict[str, JSONValue]


class ValidationError(ValueError):
    """A field did not meet the documented input shape."""


def object_map(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValidationError(f"{path}: expected an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValidationError(f"{path}: expected string object keys")
        result[key] = item
    return result


def array(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise ValidationError(f"{path}: expected an array")
    return list(value)


def string(value: object, path: str, *, nonempty: bool = False) -> str:
    if not isinstance(value, str) or "\0" in value or (nonempty and not value):
        qualifier = "nonempty " if nonempty else ""
        raise ValidationError(f"{path}: expected a {qualifier}string without NUL characters")
    return value


def boolean(value: object, path: str) -> bool:
    if type(value) is not bool:
        raise ValidationError(f"{path}: expected a boolean")
    return value


def integer(value: object, path: str, *, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        qualifier = f" >= {minimum}" if minimum is not None else ""
        raise ValidationError(f"{path}: expected an integer{qualifier}")
    return value


def strings(value: object, path: str, *, nonempty: bool = False) -> list[str]:
    return [string(item, f"{path}[{index}]", nonempty=nonempty)
            for index, item in enumerate(array(value, path))]


def string_map(value: object, path: str, *, nonempty: bool = False) -> dict[str, str]:
    return {key: string(item, f"{path}.{key}", nonempty=nonempty)
            for key, item in object_map(value, path).items()}


def required(data: dict[str, object], key: str, path: str) -> object:
    if key not in data:
        raise ValidationError(f"{path}.{key}: required field is missing")
    return data[key]


def schema_one(data: dict[str, object], path: str) -> None:
    if integer(required(data, "schema", path), f"{path}.schema") != 1:
        raise ValidationError(f"{path}.schema: expected supported schema 1")


def json_value(value: object, path: str = "JSON") -> JSONValue:
    """Normalize Python JSON-compatible values without leaking dynamic types."""
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValidationError(f"{path}: non-finite numbers are not JSON values")
        return value
    if isinstance(value, (list, tuple)):
        return [json_value(item, f"{path}[{index}]") for index, item in enumerate(value)]
    return {key: json_value(item, f"{path}.{key}")
            for key, item in object_map(value, path).items()}


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def decode_json(text: str, path: str = "JSON") -> JSONValue:
    try:
        raw: object = json.loads(text, object_pairs_hook=_unique_object)
        return json_value(raw, path)
    except (json.JSONDecodeError, ValidationError) as error:
        raise ValidationError(f"{path}: {error}") from error


def load_json(path: Path) -> JSONValue:
    return decode_json(path.read_text(), str(path))
