# SPDX-License-Identifier: LGPL-2.1-or-later
"""Line-oriented progress output; report evidence is never modified here."""

import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TextIO

from report_schema import CaseResult, RunReport

_ESCAPES = re.compile(
    r"(?:\x1b\]|\x9d)[^\x07\x1b\x9c]*(?:\x07|\x1b\\|\x9c|$)"
    r"|(?:\x1b[P^_X]|[\x90\x98\x9e\x9f])[^\x1b\x9c]*(?:\x1b\\|\x9c|$)"
    r"|(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]|\x1b[ -/]*[@-~]"
)
_STATUSES = {
    "passed": ("PASS", 32),
    "failed": ("FAIL", 31),
    "setup-error": ("ERROR", 31),
    "unmet-prerequisite": ("UNMET", 33),
    "unsupported": ("UNSUPPORTED", 33),
}


def safe_text(text: str, limit: int = 240) -> str:
    """Remove terminal commands and collapse diagnostics to one bounded line."""
    text = _ESCAPES.sub("", text)
    text = "".join(" " if char.isspace() else char for char in text
                   if char.isspace() or not unicodedata.category(char).startswith("C"))
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def use_color(mode: str, stream: TextIO, environment: Mapping[str, str]) -> bool:
    if environment.get("NO_COLOR") or mode == "never":
        return False
    return mode == "always" or stream.isatty()


class ConsoleOutput:
    def __init__(self, cases: Sequence[CaseResult], stream: TextIO, *, color: bool,
                 clock: Callable[[], float], started: float) -> None:
        self.stream = stream
        self.color = color
        self.clock = clock
        self.started = started
        self.total = len(cases)
        self.completed = 0
        self.driver_width = max((len(safe_text(case["driver"])) for case in cases), default=0)
        self.case_width = max((len(safe_text(case["behavior_id"])) for case in cases), default=0)

    def paint(self, text: str, code: int) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.color else text

    def line(self, text: str) -> None:
        print(text, file=self.stream, flush=True)

    def case_finished(self, case: CaseResult, started: float) -> None:
        elapsed = self.clock() - started
        self.completed += 1
        label, code = _STATUSES[case["status"]]
        progress = f"[{self.completed:>{len(str(self.total))}}/{self.total}]"
        self.line(
            f"{self.paint(progress, 2)} {self.paint(f'{label:<11}', code)} "
            f"{safe_text(case['driver']):<{self.driver_width}} "
            f"{safe_text(case['behavior_id']):<{self.case_width}} {elapsed:.2f}s"
        )
        reasons = [case[key] for key in ("error", "cleanup_error") if key in case]
        reasons.extend(f"{capability}: {reason}" for capability, reason
                       in case.get("unsupported_capabilities", {}).items())
        if reasons:
            self.line("    " + safe_text("; ".join(reasons)))

    def setup_error(self, status: str, error: str) -> None:
        label, code = _STATUSES[status]
        self.line(self.paint(label, code) + " setup: " + safe_text(error))

    def summary(self, report: RunReport, output: Path, status: int) -> None:
        totals = Counter(case["status"] for case in report["results"]
                         if case["status"] != "not-selected")
        integrity = report["artifact_integrity"]["status"]
        verification = report["coverage"]["verification"]
        invalid = integrity != "verified" or verification["status"] != "current"
        heading = "INVALID" if invalid else "UNSUCCESSFUL" if status else "Selected cases passed"
        self.line("\n" + self.paint(heading, 31 if invalid or status else 32)
                  + f" | {self.clock() - self.started:.2f}s wall time")
        self.line("  " + ", ".join(f"{totals[key]} {label}"
                                  for key, (label, _) in _STATUSES.items()))
        if invalid:
            self.line("  " + safe_text(f"Artifact integrity: {integrity}; coverage verification: "
                                      f"{verification['status']}: {verification['reason']}"))
        self.line("  Full compatibility coverage is incomplete.")
        self.line("Results: " + safe_text(str(output / "report.json"), limit=4096))
        self.line("Coverage: " + safe_text(str(output / "coverage.md"), limit=4096))
