# SPDX-License-Identifier: LGPL-2.1-or-later
"""Format static suite JSON without touching generated execution artifacts."""

import argparse
import json
from pathlib import Path

from json_validation import load_json


def static_paths(suite: Path) -> list[Path]:
    return sorted([
        *suite.glob("*.json"),
        *(suite / "scenario-data").rglob("*.json"),
        *(suite / "coverage-data").rglob("*.json"),
    ])


def format_files(suite: Path, *, write: bool = False) -> list[Path]:
    changed = []
    for path in static_paths(suite):
        formatted = json.dumps(load_json(path), indent=2) + "\n"
        if path.read_text() != formatted:
            changed.append(path)
            if write:
                path.write_text(formatted)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()
    suite = Path(__file__).resolve().parent
    for path in (changed := format_files(suite, write=args.write)):
        print(f"{'Formatted' if args.write else 'Needs formatting'}: {path.relative_to(suite)}")
    return int(bool(changed) and not args.write)


if __name__ == "__main__":
    raise SystemExit(main())
