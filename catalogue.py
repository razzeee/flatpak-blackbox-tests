# SPDX-License-Identifier: LGPL-2.1-or-later
"""Generate the source interface denominator, never a behavior-coverage claim.

Python 3.10+, standard library only. Consumers need only the committed JSON.
The parser checks a documented subset of C, Meson and XML syntax; it is not a
general compiler or build-system interpreter. --check regenerates and compares
everything except reference.commit, so unrelated commits do not stale it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Literal, TypedDict

Kind = Literal["cli-command", "cli-option", "library-function", "library-signal"]


class Source(TypedDict):
    path: str
    anchor: str


class SurfaceRequired(TypedDict):
    id: str
    kind: Kind
    name: str
    sources: list[Source]


class Surface(SurfaceRequired, total=False):
    aliases: list[str]
    documented_with: list[str]
    command: str
    owner: str
    deprecated: bool
    replacement: str


class Reference(TypedDict):
    commit: str
    sources: dict[str, str]


class Catalogue(TypedDict):
    schema: int
    reference: Reference
    limitations: list[str]
    surfaces: list[Surface]


class CatalogueError(ValueError):
    """A source construct cannot be accounted for safely."""


POLICY = [
    (
        "This is a source interface denominator, not behavior coverage. An entry does "
        "not establish that any test exercises its behavior, arguments, outcomes or errors."
    ),
    (
        "CLI commands are active entries in app/flatpak-main.c commands[]. Deprecated "
        "command aliases are excluded individually below. Standalone executables, "
        "D-Bus interfaces, environment variables and file formats are outside this denominator."
    ),
    (
        "Command options count every distinct documented long spelling in the command "
        "manual's option definitions, including local XML includes, with value arguments "
        "stripped. Sharing a documentation group does not imply semantic equivalence. "
        "Short spellings are aliases metadata only for groups with exactly one long "
        "spelling; multi-long groups record other long spellings as documented_with. "
        "Duplicate definitions of the same long spelling merge their source references. Repeated "
        "options such as --user count separately for each command. Synopsis placeholders, "
        "prose references, option values and short-only groups do not count. Undocumented "
        "command switches and GLib-generated help switches are outside this denominator."
    ),
    (
        "Global options come from flatpak.xml and are checked against global_entries[] "
        "and empty_entries[]. user_entries[] is command-specific, not an additional "
        "global option group."
    ),
    (
        "Library functions are explicit flatpak_* callable declarations in the literal "
        "public_headers list in common/meson.build, including deprecated functions. "
        "Macros, callbacks, class vfunc slots, private headers and generated plumbing "
        "are excluded. All type-registration get_type functions are excluded individually "
        "below, consistently for explicit declarations, G_DECLARE_* and generated enums."
    ),
    (
        "Library signals require a gtk-doc Owner::signal block and a matching "
        "g_signal_new registration for a public GType. Inherited GLib signals and "
        "private-class signals are excluded. Common library C sources listed in Meson "
        "are scanned without a built tree or preprocessing; conditional public "
        "declarations are counted regardless of the local build configuration."
    ),
    (
        "Meson discovery supports one literal public_headers assignment installed by "
        "one direct install_headers(public_headers, ...) call. Header reassignment, "
        "augmentation and alternative installer arguments are rejected. Library source "
        "discovery supports literal file lists assigned to names ending in sources, "
        "literal-list augmentation, and direct library/static_library source arguments. "
        "Source-list reassignment and indirect or computed source expressions are rejected."
    ),
    (
        "Meson parsing is a static subset, not a guarantee that future build structures "
        "are understood. It does not evaluate conditions, follow subdir/include calls, "
        "or resolve dependency-provided sources. The known generated inputs enums, "
        "flatpak_gdbus, flatpak_document_gdbus, systemd_gdbus, flatpak_variant and "
        "wl_security_context are excluded from signal discovery without interpreting "
        "their generator definitions. New build indirection or generated public APIs "
        "require a catalogue-parser review."
    ),
    (
        "XML is parsed offline with the standard library. Internal entities and local "
        "SYSTEM XML entities/includes with one root element are supported and hashed. "
        "External DTDs are not "
        "fetched; unresolved entities, includes and unsupported XPointer syntax are errors."
    ),
]


def uncomment(text: str) -> str:
    """Remove C comments without mistaking quoted comment markers for comments."""
    return re.sub(
        r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
        lambda m: re.sub(r"[^\n]", " ", m[0]) if m[0].startswith(("/*", "//")) else m[0],
        text,
        flags=re.DOTALL,
    )


def split_c(text: str, delimiter: str = ",") -> list[str]:
    """Split at top-level delimiters, respecting strings and nested C syntax."""
    stack: list[str] = []
    start = 0
    parts: list[str] = []
    for match in re.finditer(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|.', text, re.DOTALL):
        token = match[0]
        if token in ("(", "{", "["):
            stack.append({"(": ")", "{": "}", "[": "]"}[token])
        elif token in (")", "}", "]"):
            if not stack or stack.pop() != token:
                raise CatalogueError("Unbalanced C declaration/table")
        elif token == delimiter and not stack:
            parts.append(text[start:match.start()].strip())
            start = match.end()
    if stack:
        raise CatalogueError("Unbalanced C declaration/table")
    parts.append(text[start:].strip())
    return [part for part in parts if part]


def array(text: str, name: str) -> list[list[str]]:
    match = re.search(r"\b" + re.escape(name) + r"\s*\[\s*\]\s*=\s*\{(.*?)\}\s*;", text, re.DOTALL)
    if match is None:
        raise CatalogueError(f"Missing literal C array {name}[]")
    result: list[list[str]] = []
    for row in split_c(match[1]):
        if not row.startswith("{") or not row.endswith("}"):
            raise CatalogueError(f"Unrecognized row in {name}[]: {row}")
        result.append(split_c(row[1:-1]))
    return result


def string_literal(value: str) -> str:
    if not re.fullmatch(r'"[a-zA-Z0-9_-]+"', value):
        raise CatalogueError(f"Expected an interface-name string literal: {value}")
    return value[1:-1]


def meson_inputs(text: str) -> tuple[list[str], list[str]]:
    """Validate the supported discovery subset, without evaluating Meson."""
    clean = re.sub(
        r"'[^']*'|\"[^\"]*\"|#[^\n]*",
        lambda match: "" if match[0].startswith("#") else match[0],
        text,
    )
    statements = split_c(clean, "\n")
    assignments: dict[str, list[tuple[str, str]]] = {}
    for statement in statements:
        match = re.fullmatch(r"(\w+)\s*(\+?=)\s*(.*)", statement, re.DOTALL)
        if match:
            assignments.setdefault(match[1], []).append((match[2], match[3]))
    header_assignments = assignments.get("public_headers", [])
    if len(header_assignments) != 1 or header_assignments[0][0] != "=":
        raise CatalogueError("Expected one explicit literal public_headers assignment")
    header_list = re.fullmatch(r"\[([^\]]*)\]", header_assignments[0][1], re.DOTALL)
    if header_list is None:
        raise CatalogueError("Nonliteral public_headers assignment")
    headers: list[str] = []
    for value in split_c(header_list[1]):
        match = re.fullmatch(r"['\"]([^'\"]+\.h)['\"]", value)
        if match is None:
            raise CatalogueError("Nonliteral public_headers list member")
        headers.append(match[1])
    if not headers or len(headers) != len(set(headers)):
        raise CatalogueError("Empty or duplicate public_headers list")

    generated = {
        "enums", "flatpak_gdbus", "flatpak_document_gdbus", "systemd_gdbus",
        "flatpak_variant", "wl_security_context",
    }
    source_names = {name for name in assignments if name.endswith("sources")}
    c_sources: set[str] = set()

    def source_expression(expression: str, references: set[str]) -> None:
        for part in split_c(expression, "+"):
            literal = re.fullmatch(r"['\"]([^'\"]+\.(?:c|h))['\"]", part)
            indexed = re.fullmatch(r"(\w+)\[\d+\]", part)
            if literal:
                if literal[1].endswith(".c"):
                    c_sources.add(literal[1])
            elif part.startswith("[") and part.endswith("]"):
                for member in split_c(part[1:-1]):
                    source_expression(member, references)
            elif (
                part in generated or part in references
                or (indexed and indexed[1] in generated)
            ):
                continue
            else:
                raise CatalogueError(f"Unsupported Meson library source expression: {part}")

    for name in sorted(source_names):
        definitions = assignments[name]
        if definitions[0][0] != "=" or sum(op == "=" for op, _ in definitions) != 1:
            raise CatalogueError(f"Unsupported Meson source-list reassignment: {name}")
        for _, expression in definitions:
            source_expression(expression, set())

    installed = 0
    libraries = 0
    for statement in statements:
        installer = re.fullmatch(r"install_headers\s*\((.*)\)", statement, re.DOTALL)
        if installer:
            args = split_c(installer[1])
            if not args or args[0] != "public_headers" or any(
                not re.match(r"\w+\s*:", arg) for arg in args[1:]
            ):
                raise CatalogueError("Unsupported install_headers arguments")
            installed += 1
        library = re.fullmatch(
            r"(?:\w+\s*=\s*)?(?:static_library|library)\s*\((.*)\)",
            statement, re.DOTALL,
        )
        if library:
            args = split_c(library[1])
            if not args or not re.fullmatch(r"['\"][^'\"]+['\"]", args[0]):
                raise CatalogueError("Unsupported Meson library target name")
            for arg in args[1:]:
                keyword = re.match(r"(\w+)\s*:\s*(.*)", arg, re.DOTALL)
                if keyword and keyword[1] != "sources":
                    continue
                source_expression(keyword[2] if keyword else arg, source_names | {"public_headers"})
            libraries += 1
    if installed != 1 or len(re.findall(r"\binstall_headers\s*\(", clean)) != installed:
        raise CatalogueError("Expected one direct install_headers(public_headers, ...) call")
    calls = len(re.findall(r"\b(?:static_library|library)\s*\(", clean))
    if not libraries or libraries != calls:
        raise CatalogueError("Unsupported or missing direct Meson library declarations")
    if not c_sources:
        raise CatalogueError("No common C sources found in Meson")
    return headers, sorted(c_sources)


class Generator:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.hashes: dict[str, str] = {}
        self.surfaces: dict[str, Surface] = {}
        self.exclusions: set[str] = set()
        self.origins: dict[ET.Element, str] = {}

    def read(self, path: str) -> str:
        file = self.root / path
        if not file.resolve().is_relative_to(self.root):
            raise CatalogueError(f"Source escapes repository: {path}")
        data = file.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if path in self.hashes and self.hashes[path] != digest:
            raise CatalogueError(f"Source changed during generation: {path}")
        self.hashes[path] = digest
        return data.decode("utf-8")

    def local_path(self, parent: str, href: str) -> str:
        if re.search(r"^[a-zA-Z][a-zA-Z0-9+.-]*:|[#?]", href):
            raise CatalogueError(f"Non-local XML reference in {parent}: {href}")
        path = (self.root / parent).parent / href
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError as exc:
            raise CatalogueError(f"XML reference escapes repository: {href}") from exc

    def add(self, item: Surface) -> None:
        if item["id"] in self.surfaces:
            raise CatalogueError(f"Duplicate interface ID: {item['id']}")
        self.surfaces[item["id"]] = item

    def xml(self, path: str, ancestors: tuple[str, ...] = ()) -> ET.Element:
        if path in ancestors:
            raise CatalogueError(f"Cyclic XML include/entity: {' -> '.join((*ancestors, path))}")
        text = self.read(path)
        # ElementTree resolves internal entities, but not external ones. Expand
        # local SYSTEM entities ourselves, recording the exact bytes consumed.
        external = re.compile(r'<!ENTITY\s+([\w.-]+)\s+SYSTEM\s+[\'"]([^\'"]+)[\'"]\s*>')
        entities: dict[str, ET.Element] = {}
        for entity in external.finditer(text):
            target = self.local_path(path, entity[2])
            entities[entity[1]] = self.xml(target, (*ancestors, path))
            text = text.replace(f"&{entity[1]};", f'<catalogue-local-entity name="{entity[1]}"/>')
        text = external.sub("", text)
        try:
            tree = ET.fromstring(text)
        except ET.ParseError as exc:
            raise CatalogueError(f"Unresolved or malformed XML in {path}: {exc}") from exc
        for element in tree.iter():
            self.origins[element] = path
        for parent in list(tree.iter()):
            for index, child in reversed(list(enumerate(parent))):
                if child.tag == "catalogue-local-entity":
                    parent.remove(child)
                    parent.insert(index, entities[child.attrib["name"]])
                    continue
                if child.tag != "{http://www.w3.org/2001/XInclude}include":
                    continue
                if child.get("parse", "xml") != "xml" or "href" not in child.attrib:
                    raise CatalogueError(f"Unsupported XML include in {path}: {child.attrib}")
                target = self.local_path(path, child.attrib["href"])
                included = self.xml(target, (*ancestors, path))
                pointer = child.get("xpointer")
                selected = [included]
                if pointer:
                    id_match = re.fullmatch(r"(?:element\(([\w.-]+)\)|([\w.-]+))", pointer)
                    if id_match:
                        identifier = id_match[1] or id_match[2]
                        selected = [e for e in included.iter() if e.get("id") == identifier]
                    elif pointer.startswith("xpointer(//") and pointer.endswith(")"):
                        query = pointer[len("xpointer("):-1]
                        try:
                            selected = included.findall("." + query)
                        except (SyntaxError, KeyError) as exc:
                            raise CatalogueError(
                                f"Unsupported XPointer in {path}: {pointer}"
                            ) from exc
                    else:
                        raise CatalogueError(f"Unsupported XPointer in {path}: {pointer}")
                    if not selected:
                        raise CatalogueError(f"Unresolved XPointer in {path}: {pointer}")
                parent.remove(child)
                for entry in reversed(selected):
                    parent.insert(index, entry)
        return tree

    def options(self, command: str, path: str) -> set[str]:
        tree = self.xml(path)
        # Definitions, not section titles, determine membership: manuals can
        # have separate permission/build option groups with arbitrary titles.
        spellings: set[str] = set()
        occurrences: Counter[tuple[str, str]] = Counter()
        for entry in tree.iter("varlistentry"):
            names: list[str] = []
            for term in entry.findall("term"):
                options = list(term.iter("option"))
                if not options and "".join(term.itertext()).strip().startswith("-"):
                    raise CatalogueError(f"Option definition without <option> markup in {path}")
                for option in options:
                    value = "".join(option.itertext()).strip()
                    match = re.match(r"(--?[a-zA-Z0-9?][a-zA-Z0-9-]*)(?=$|[=\s\[])", value)
                    if match is None:
                        if value.startswith("-"):
                            raise CatalogueError(f"Unparsed option definition in {path}: {value}")
                        continue  # Nested value tables are not option definitions.
                    if match[1] not in names:
                        names.append(match[1])
            longs = [name for name in names if name.startswith("--")]
            if not longs:
                if names:
                    self.exclusions.add(
                        f"Excluded short-only option group {command} {'/'.join(names)} ({path})."
                    )
                continue
            origin = self.origins[entry]
            for name in longs:
                occurrences[origin, name] += 1
                anchor = f"varlistentry/term/option: {name}"
                if occurrences[origin, name] > 1:
                    anchor += f" (definition {occurrences[origin, name]})"
                sources: list[Source] = [{"path": origin, "anchor": anchor}]
                if origin != path:
                    sources.append({"path": path, "anchor": f"XML include/entity of {origin}"})
                aliases = (
                    sorted(short for short in names if not short.startswith("--"))
                    if len(longs) == 1 else []
                )
                documented_with = sorted(other for other in longs if other != name)
                identifier = f"cli.option.{command}.{name}"
                previous = self.surfaces.get(identifier)
                if previous is not None:
                    previous["sources"].extend(
                        source for source in sources if source not in previous["sources"]
                    )
                    previous["aliases"] = sorted({*previous.get("aliases", []), *aliases})
                    if documented_with:
                        previous["documented_with"] = sorted({
                            *previous.get("documented_with", []), *documented_with,
                        })
                    self.exclusions.add(
                        f"Collapsed duplicate option definition {command} {name} ({path}); "
                        "identical long spellings count once, with merged source references."
                    )
                    continue
                spellings.add(name)
                item: Surface = {
                    "id": identifier, "kind": "cli-option", "name": name,
                    "command": command, "sources": sources, "aliases": aliases,
                }
                if documented_with:
                    item["documented_with"] = documented_with
                self.add(item)
        if not spellings:
            raise CatalogueError(f"No long-option definitions in {path}")
        return spellings

    def cli(self) -> None:
        path = "app/flatpak-main.c"
        text = uncomment(self.read(path))
        commands: dict[str, tuple[str, bool]] = {}
        for fields in array(text, "commands"):
            if fields == ["NULL"] or (len(fields) == 1 and fields[0].startswith("N_(")):
                continue
            if len(fields) not in (4, 5) or not re.fullmatch(r"flatpak_builtin_\w+", fields[2]):
                raise CatalogueError(f"Unrecognized command registration: {fields}")
            name = string_literal(fields[0])
            if name in commands or (len(fields) == 5 and fields[4] not in ("TRUE", "FALSE")):
                raise CatalogueError(f"Invalid/duplicate command registration: {fields}")
            commands[name] = (fields[2], len(fields) == 5 and fields[4] == "TRUE")
        active = {name: fn for name, (fn, deprecated) in commands.items() if not deprecated}
        if not active:
            raise CatalogueError("No active commands found")
        for alias, (fn, deprecated) in sorted(commands.items()):
            if deprecated:
                canonical = [name for name, function in active.items() if fn == function]
                if len(canonical) != 1:
                    raise CatalogueError(f"Cannot resolve deprecated command alias {alias}")
                self.exclusions.add(
                    f"Excluded deprecated command alias {alias} -> {canonical[0]} "
                    f"({path}: commands[]); same handler, not a separate canonical command."
                )
        for name in sorted(active):
            # The current tree uses canonical filenames; older trees use the
            # deprecated *-list names. Derive those alternatives from the table.
            candidates = [name, *sorted(
                alias for alias, (fn, deprecated) in commands.items()
                if deprecated and fn == active[name]
            )]
            documents = [f"doc/flatpak-{candidate}.xml" for candidate in candidates
                         if (self.root / f"doc/flatpak-{candidate}.xml").is_file()]
            if not documents:
                raise CatalogueError(f"Missing command manual for {name}; tried {candidates}")
            if len(documents) != 1:
                raise CatalogueError(f"Ambiguous command manuals for {name}: {documents}")
            doc = documents[0]
            self.add({
                "id": f"cli.command.{name}", "kind": "cli-command", "name": name,
                "sources": [{"path": path, "anchor": f'commands[]: "{name}"'},
                            {"path": doc, "anchor": "refentry"}],
            })
            self.options(name, doc)
        documented = self.options("global", "doc/flatpak.xml")
        registered: set[str] = set()
        for table in ("global_entries", "empty_entries"):
            for fields in array(text, table):
                if fields == ["NULL"]:
                    continue
                if len(fields) != 7:
                    raise CatalogueError(f"Unrecognized option registration in {table}: {fields}")
                name = "--" + string_literal(fields[0])
                registered.add(name)
                item = self.surfaces.get(f"cli.option.global.{name}")
                if item is not None:
                    item["sources"].append({"path": path, "anchor": f'{table}[]: "{name[2:]}"'})
                    if fields[1] != "0":
                        short = re.fullmatch(r"'([a-zA-Z0-9?])'", fields[1])
                        if short is None:
                            raise CatalogueError(
                                f"Unrecognized short option in {table}: {fields[1]}"
                            )
                        item["aliases"] = sorted({*item.get("aliases", []), "-" + short[1]})
        if registered != documented:
            raise CatalogueError(
                f"Global option mismatch: undocumented={sorted(registered - documented)}, "
                f"unregistered={sorted(documented - registered)}"
            )

    def library(self) -> None:
        meson_path = "common/meson.build"
        meson = self.read(meson_path)
        headers, c_sources = meson_inputs(meson)
        public_types: set[str] = set()
        enum_types: set[tuple[str, str]] = set()
        for header in headers:
            if "private" in header:
                raise CatalogueError(f"Private header in public_headers: {header}")
            path = f"common/{header}"
            text = uncomment(self.read(path))
            text = re.sub(r"(?m)^\s*#(?:[^\n\\]|\\\n)*", "", text)
            public_types.update(re.findall(r"typedef\s+struct\s+_?(Flatpak\w+)\s+\1\s*;", text))
            for enum_match in re.finditer(
                r"typedef\s+enum\s*(?:\w+\s*)?\{[^}]*\}\s*(Flatpak\w+)\s*;", text, re.DOTALL
            ):
                enum_types.add((enum_match[1], path))
            # Every export marker must start a recognized declaration. A macro
            # declaration has no semicolon, so handle it before ordinary C units.
            text = re.sub(r"\bG_BEGIN_DECLS\b|\bG_END_DECLS\b", "", text)
            declarations = list(re.finditer(
                r"\bFLATPAK_EXTERN\s+(?:G_DECLARE_\w+\s*\([^)]*\)|[^;]+;)", text, re.DOTALL
            ))
            if len(declarations) != len(re.findall(r"\bFLATPAK_EXTERN\b", text)):
                raise CatalogueError(f"Unparsed public export marker in {path}")
            found: set[str] = set()
            declared_macros = 0
            for declaration in declarations:
                unit = declaration[0]
                macro = re.fullmatch(
                    r"FLATPAK_EXTERN\s+G_DECLARE_(?:FINAL|DERIVABLE|INTERFACE)_TYPE\s*"
                    r"\(\s*(Flatpak\w+)\s*,\s*(flatpak_\w+)\s*,[^)]*\)", unit, re.DOTALL
                )
                if macro:
                    declared_macros += 1
                    public_types.add(macro[1])
                    self.exclude_type(
                        macro[2] + "_get_type", path, "G_DECLARE_* implicit declaration"
                    )
                    continue
                function = re.search(r"\b(flatpak_\w+)\s*\(", unit)
                if function is None:
                    raise CatalogueError(f"Unrecognized public declaration in {path}: {unit}")
                name = function[1]
                # Validate balanced arguments, reject multiple declarations.
                if len(split_c(unit, ";")) != 1 or "G_DECLARE_" in unit:
                    raise CatalogueError(f"Unrecognized public declaration in {path}: {unit}")
                found.add(name)
                if name.endswith("_get_type"):
                    self.exclude_type(name, path, "explicit declaration")
                    continue
                prefix = text[:declaration.start()]
                annotation = re.search(
                    r"G_GNUC_DEPRECATED(?:_FOR\s*\(\s*(\w+)\s*\))?\s*$", prefix
                )
                item: Surface = {
                    "id": f"library.function.{name}", "kind": "library-function", "name": name,
                    "sources": [{"path": path, "anchor": name}],
                    "deprecated": annotation is not None or "DEPRECATED" in unit,
                }
                if annotation and annotation[1]:
                    item["replacement"] = annotation[1]
                self.add(item)
            if declared_macros != len(re.findall(r"\bG_DECLARE_\w+\s*\(", text)):
                raise CatalogueError(f"Unaccounted G_DECLARE_* public type in {path}")
            # Catch future public functions that omit/change the export marker.
            without_annotations = re.sub(r"G_GNUC_DEPRECATED_FOR\s*\([^)]*\)", "", text)
            candidates = set(re.findall(
                r"\b(flatpak_\w+)\s*\([^;{}]*\)\s*[^;{}]*;", without_annotations
            ))
            if candidates - found:
                raise CatalogueError(
                    f"Unaccounted public declarations in {path}: {sorted(candidates - found)}"
                )
        if enum_types:
            template_path = "common/flatpak-enum-types.h.template"
            template = self.read(template_path)
            if not re.search(r"GType\s+@enum_name@_get_type\s*\(void\)", template):
                raise CatalogueError("Unrecognized generated enum declaration template")
            for enum, path in sorted(enum_types):
                snake = re.sub(
                    r"([a-z0-9])([A-Z])", r"\1_\2",
                    re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", enum),
                ).lower()
                self.exclude_type(
                    snake + "_get_type", path, f"generated enum {enum}; {template_path}"
                )
        for source in c_sources:
            self.signals(f"common/{source}", public_types)

    def exclude_type(self, name: str, path: str, reason: str) -> None:
        self.exclusions.add(
            f"Excluded type-registration function {name} ({path}: {reason}); GType plumbing."
        )

    def signals(self, path: str, public_types: set[str]) -> None:
        text = self.read(path)
        clean = uncomment(text)
        classes = list(re.finditer(
            r"\b\w+_class_init\s*\(\s*(\w+)Class\s*\*\s*\w+\s*\)\s*\{", clean
        ))
        blocks = list(re.finditer(r"/\*\*.*?\*/", text, re.DOTALL))
        documented: dict[int, tuple[str, str]] = {}
        for block in blocks:
            signal_match = re.search(r"(?m)^\s*\*\s*(\w+)::([\w-]+):\s*$", block[0])
            if signal_match:
                documented[block.end()] = (signal_match[1], signal_match[2])
        consumed: set[int] = set()
        for registration in re.finditer(r"\b(g_signal_new\w*)\s*\(", clean):
            if registration[1] != "g_signal_new":
                raise CatalogueError(
                    f"Unsupported signal registration form in {path}: {registration[0]}"
                )
            name_match = re.match(r'\s*"([\w-]+)"\s*,', clean[registration.end():])
            if name_match is None:
                raise CatalogueError(f"Nonliteral signal name in {path}")
            name = name_match[1]
            owners = [match for match in classes if match.start() < registration.start()]
            if not owners:
                raise CatalogueError(
                    f"Signal registration outside recognized class_init in {path}: {name}"
                )
            owner_match = owners[-1]
            prefix = clean[owner_match.end() - 1:registration.start()]
            braces = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', "", prefix)
            if braces.count("{") <= braces.count("}"):
                raise CatalogueError(f"Signal registration outside class_init in {path}: {name}")
            registered_owner = owner_match[1]
            if registered_owner not in public_types:
                self.exclusions.add(
                    f"Excluded private-class signal {registered_owner}::{name} ({path}); "
                    "owner is not a public GType."
                )
                continue
            preceding = [end for end in documented if end <= registration.start()]
            if not preceding:
                raise CatalogueError(f"Undocumented signal registration in {path}: {name}")
            end = max(preceding)
            owner, signal = documented[end]
            between = uncomment(text[end:registration.start()])
            if signal != name or owner != registered_owner or ";" in between or end in consumed:
                raise CatalogueError(f"Cannot associate signal registration in {path}: {name}")
            consumed.add(end)
            self.add({
                "id": f"library.signal.{owner}.{signal}", "kind": "library-signal",
                "name": signal, "owner": owner,
                "sources": [{"path": path, "anchor": f"{owner}::{signal}"},
                            {"path": path, "anchor": f'g_signal_new ("{signal}"'}],
            })
        for end, (owner, signal) in documented.items():
            if owner in public_types and end not in consumed:
                raise CatalogueError(
                    f"Public signal has no registration in {path}: {owner}::{signal}"
                )

    def generate(self) -> Catalogue:
        self.cli()
        self.library()
        commit = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            check=True, text=True, capture_output=True,
        ).stdout.strip()
        return {
            "schema": 1,
            "reference": {"commit": commit, "sources": dict(sorted(self.hashes.items()))},
            "limitations": POLICY + sorted(self.exclusions),
            "surfaces": [self.surfaces[key] for key in sorted(self.surfaces)],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--check", action="store_true", help="fail on drift, ignoring only reference.commit"
    )
    args = parser.parse_args()
    try:
        catalogue = Generator(args.source_root).generate()
        if args.check:
            existing = json.loads(args.output.read_text(encoding="utf-8"))
            if not isinstance(existing, dict) or not isinstance(existing.get("reference"), dict):
                raise CatalogueError("Invalid existing catalogue schema")
            if not isinstance(existing["reference"].get("commit"), str):
                raise CatalogueError("Missing or invalid existing reference.commit")
            existing["reference"]["commit"] = catalogue["reference"]["commit"]
            if existing != catalogue:
                raise CatalogueError(f"Catalogue drift detected: regenerate {args.output}")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(catalogue, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        counts = Counter(item["kind"] for item in catalogue["surfaces"])
        print(json.dumps({"counts": dict(sorted(counts.items())),
                          "source_files": len(catalogue["reference"]["sources"]),
                          "exclusions": len(catalogue["limitations"]) - len(POLICY)},
                         sort_keys=True))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"catalogue: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
