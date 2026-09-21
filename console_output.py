# SPDX-License-Identifier: LGPL-2.1-or-later
"""Line-oriented progress output; report evidence is never modified here."""

import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from html import escape
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


def coverage_rows(report: RunReport) -> list[tuple[str, str, str]]:
    """Use saved coverage accounting, never infer passing credit from case counts."""
    coverage = report.get("coverage")
    verified = (coverage is not None and coverage["verification"]["status"] == "current"
                and report.get("artifact_integrity", {}).get("status") == "verified")
    rows = []
    for group, key, label in (
        ("behaviors", "cli", "CLI behaviors"),
        ("behaviors", "library", "Library behaviors"),
        ("surfaces", "cli-command", "CLI commands"),
        ("surfaces", "cli-option", "CLI options"),
        ("surfaces", "library-function", "Library functions"),
        ("surfaces", "library-signal", "Library signals"),
    ):
        metrics = (coverage["metrics"]["behaviors"] if group == "behaviors"
                   else coverage["metrics"]["surfaces"]) if coverage else {}
        metric = metrics.get(key)
        passing = "unverified"
        total = str(metric["total"]) if metric else "unverified"
        if verified and metric and metric["passed"] is not None:
            percent = metric["passed_percent"]
            if percent is not None:
                passing = f"{metric['passed']} ({percent:.1f}%)"
        rows.append((label, passing, total))
    return rows


def option_accounting_rows(report: RunReport) -> list[tuple[str, str, str]]:
    coverage = report.get("coverage")
    accounting = coverage.get("cli_option_accounting") if coverage else None
    if not accounting:
        return []
    verified = (coverage is not None and coverage["verification"]["status"] == "current"
                and report.get("artifact_integrity", {}).get("status") == "verified")
    rows = []
    for label, metric in (("Equivalence checks", accounting["equivalence_checks"]),
                          ("Accounted options", accounting["accounted"])):
        passing = "unverified"
        if verified and metric["passed"] is not None and metric["passed_percent"] is not None:
            passing = f"{metric['passed']} ({metric['passed_percent']:.1f}%)"
        rows.append((label, passing, str(metric["total"])))
    return rows


def slowest_cases(report: RunReport) -> list[CaseResult]:
    return sorted(
        (case for case in report.get("results", []) if "duration_seconds" in case
         and case["status"] not in ("not-selected", "unsupported", "pending")),
        key=lambda case: (-case["duration_seconds"], case["behavior_id"],
                          case["driver"], case["profile"]),
    )[:10]


def timing_cells(case: CaseResult) -> list[str]:
    timings = case.get("timings")
    return [f"{case['duration_seconds']:.2f}s", *(
        f"{timings[key]:.2f}s" if timings else "unverified"
        for key in ("setup_seconds", "execution_seconds", "cleanup_seconds")
    )]


def result_heading(report: RunReport, status: int) -> str:
    if (report.get("artifact_integrity", {}).get("status") != "verified"
            or report.get("coverage", {}).get("verification", {}).get("status") != "current"):
        return "INVALID"
    return "UNSUCCESSFUL" if status else "Selected cases passed"


def markdown_cell(text: str) -> str:
    # Entity-encode Markdown syntax as well as HTML. Bound before expansion.
    return re.sub(r"[\\`*_{}\[\]()#+.!|~:/@-]", lambda match: f"&#{ord(match[0])};",
                  escape(safe_text(text), quote=False))


def github_summary(report: RunReport, status: int) -> str:
    """Render GFM without evidence, environment values, or terminal formatting."""
    totals = Counter(case["status"] for case in report.get("results", [])
                     if case["status"] != "not-selected")
    duration = report.get("duration_seconds")
    runtime = f"{duration:.2f}s" if duration is not None else "unverified"
    integrity = report.get("artifact_integrity", {}).get("status", "unverified")
    coverage = report.get("coverage")
    verification = coverage["verification"]["status"] if coverage else "unverified"
    lines = ["## Flatpak compatibility", "", f"**{result_heading(report, status)}**",
             f"Run wall time: {runtime}", "",
             f"Artifact integrity: {markdown_cell(integrity)}; "
             f"coverage verification: {markdown_cell(verification)}", "",
             ", ".join(f"{totals[key]} {label}" for key, (label, _) in _STATUSES.items()), "",
             "| Coverage | Passing | Total |", "| --- | ---: | ---: |"]
    lines.extend("| " + " | ".join(row) + " |" for row in coverage_rows(report))
    if accounting := option_accounting_rows(report):
        lines += ["", "Separate option inventory; equivalence is not behavioral coverage.", "",
                  "| Inventory | Passing | Total |", "| --- | ---: | ---: |"]
        lines.extend("| " + " | ".join(row) + " |" for row in accounting)
    lines.extend(["", "Full compatibility coverage is incomplete.", "",
                  "### Slowest selected cases", "",
                  "| Case | Driver | Status | Total | Setup | Execution | Cleanup |",
                  "| --- | --- | --- | ---: | ---: | ---: | ---: |"])
    for case in slowest_cases(report):
        label = _STATUSES.get(case["status"], (case["status"], 0))[0]
        label = markdown_cell(label)
        if case["status"] != "passed":
            label = f"**{label}**"
        cells = [markdown_cell(case["behavior_id"]), markdown_cell(case["driver"]),
                 label, *timing_cells(case)]
        lines.append("| " + " | ".join(cells) + " |")
    if not slowest_cases(report):
        lines.extend(["", "No executed case timings available."])
    return "\n".join(lines) + "\n"


class ConsoleOutput:
    def __init__(self, cases: Sequence[CaseResult], stream: TextIO, *, color: bool) -> None:
        self.stream = stream
        self.color = color
        self.total = len(cases)
        self.completed = 0
        self.driver_width = max((len(safe_text(case["driver"])) for case in cases), default=0)
        self.case_width = max((len(safe_text(case["behavior_id"])) for case in cases), default=0)

    def paint(self, text: str, code: int) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.color else text

    def line(self, text: str) -> None:
        print(text, file=self.stream, flush=True)

    def case_finished(self, case: CaseResult) -> None:
        elapsed = case.get("duration_seconds")
        runtime = f"{elapsed:.2f}s" if elapsed is not None else "not timed"
        self.completed += 1
        label, code = _STATUSES[case["status"]]
        progress = f"[{self.completed:>{len(str(self.total))}}/{self.total}]"
        self.line(
            f"{self.paint(progress, 2)} {self.paint(f'{label:<11}', code)} "
            f"{safe_text(case['driver']):<{self.driver_width}} "
            f"{safe_text(case['behavior_id']):<{self.case_width}} {runtime}"
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
        integrity = report.get("artifact_integrity", {}).get("status", "unverified")
        coverage = report.get("coverage")
        verification = coverage["verification"] if coverage else {
            "status": "unverified", "reason": "No coverage report available",
        }
        invalid = integrity != "verified" or verification["status"] != "current"
        heading = result_heading(report, status)
        duration = report.get("duration_seconds")
        runtime = f"{duration:.2f}s" if duration is not None else "unverified"
        self.line("\n" + self.paint(heading, 31 if invalid or status else 32)
                  + f" | {runtime} wall time")
        self.line("  " + ", ".join(f"{totals[key]} {label}"
                                  for key, (label, _) in _STATUSES.items()))
        if invalid:
            self.line("  " + safe_text(f"Artifact integrity: {integrity}; coverage verification: "
                                      f"{verification['status']}: {verification['reason']}"))
        self.line("  Full compatibility coverage is incomplete.")
        self.line("\nCoverage                    Passing           Total")
        for label, passing, total in coverage_rows(report):
            self.line(f"  {label:<24} {passing:>16} {total:>7}")
        if accounting := option_accounting_rows(report):
            self.line("\nOption inventory (equivalence is not behavioral coverage)")
            for label, passing, total in accounting:
                self.line(f"  {label:<24} {passing:>16} {total:>7}")
        self.line("\nSlowest selected cases:")
        self.line(f"  {'Status':<11} {'Driver':<{self.driver_width}} "
                  f"{'Case':<{self.case_width}}     Total     Setup Execution   Cleanup")
        for case in slowest_cases(report):
            label, code = _STATUSES.get(case["status"], (safe_text(case["status"]), 33))
            self.line(f"  {self.paint(f'{label:<11}', code)} "
                      f"{safe_text(case['driver']):<{self.driver_width}} "
                      f"{safe_text(case['behavior_id']):<{self.case_width}} "
                      + " ".join(f"{cell:>9}" for cell in timing_cells(case)))
        if not slowest_cases(report):
            self.line("  No executed case timings available.")
        self.line("Results: " + safe_text(str(output / "report.json"), limit=4096))
        self.line("Coverage: " + safe_text(str(output / "coverage.md"), limit=4096))
