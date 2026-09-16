# SPDX-License-Identifier: LGPL-2.1-or-later
"""Checked JSON decoding against the suite's small TypedDict vocabulary."""

from functools import cache
from types import UnionType
from typing import (
    ForwardRef,
    Literal,
    Protocol,
    TypeVar,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

from json_validation import (
    JSONValue,
    ValidationError,
    array,
    boolean,
    integer,
    json_value,
    object_map,
    required,
    schema_one,
)


class _RequiredFields(Protocol):
    __required_keys__: frozenset[str]


@cache
def _fields(annotation: object) -> dict[str, object]:
    return get_type_hints(annotation)


def _validate(value: object, annotation: object, path: str) -> None:
    """Check declared types recursively, retaining JSON-compatible extensions.

    Only this small set of annotation forms is supported; new forms fail closed.
    Domain constraints belong in the caller's parser.
    """
    if annotation == JSONValue or (
        isinstance(annotation, ForwardRef) and annotation.__forward_arg__ == "JSONValue"
    ):
        json_value(value, path)
    elif is_typeddict(annotation):
        data = object_map(value, path)
        for key in cast(_RequiredFields, annotation).__required_keys__:
            required(data, key, path)
        for key, field_type in _fields(annotation).items():
            if key in data:
                _validate(data[key], field_type, f"{path}.{key}")
        if "schema" in _fields(annotation) and "schema" in data:
            schema_one(data, path)
    elif annotation is str:
        # Captured stdout/stderr may contain NUL; report text is not argv data.
        if not isinstance(value, str):
            raise ValidationError(f"{path}: expected a string")
    elif annotation is bool:
        boolean(value, path)
    elif annotation is int:
        integer(value, path)
    elif annotation is float:
        if type(value) not in (int, float):
            raise ValidationError(f"{path}: expected a number")
    elif annotation is type(None):
        if value is not None:
            raise ValidationError(f"{path}: expected null")
    elif get_origin(annotation) is Literal:
        if not any(type(value) is type(choice) and value == choice
                   for choice in get_args(annotation)):
            raise ValidationError(f"{path}: expected one of {get_args(annotation)}")
    elif get_origin(annotation) is list:
        element, = get_args(annotation)
        for index, item in enumerate(array(value, path)):
            _validate(item, element, f"{path}[{index}]")
    elif get_origin(annotation) is dict:
        key_type, element = get_args(annotation)
        for key, item in object_map(value, path).items():
            _validate(key, key_type, f"{path} key")
            _validate(item, element, f"{path}.{key}")
    elif get_origin(annotation) is UnionType:
        for alternative in get_args(annotation):
            try:
                _validate(value, alternative, path)
                return
            except ValidationError:
                pass
        raise ValidationError(f"{path}: value does not match {annotation}")
    else:
        raise ValidationError(f"{path}: unsupported field type {annotation}")


T = TypeVar("T")


def parse_typed(value: object, schema: type[T], path: str) -> T:
    """Return a detached DTO after recursively checking its declared field types.

    Unknown fields are retained and checked for JSON compatibility. Unsupported
    annotation forms fail closed. This boundary does not check domain references.
    """
    normalized = json_value(value, path)
    _validate(normalized, schema, path)
    # The recursive check above validates every declared field and required key.
    return cast(T, normalized)
