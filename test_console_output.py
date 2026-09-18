# SPDX-License-Identifier: LGPL-2.1-or-later
"""Console policy, safe diagnostics, layout, and immediate delivery."""

import io
import re
import unittest
from pathlib import Path

from console_output import (
    ConsoleOutput,
    coverage_rows,
    github_summary,
    markdown_cell,
    safe_text,
    slowest_cases,
    use_color,
)
from coverage_report import CoverageModel
from report_schema import CaseResult, RunReport


class Capture(io.StringIO):
    def __init__(self, tty: bool = False) -> None:
        super().__init__()
        self.tty = tty
        self.flushed: list[str] = []

    def isatty(self) -> bool:
        return self.tty

    def flush(self) -> None:
        self.flushed.append(self.getvalue())


class ConsoleTests(unittest.TestCase):
    def test_coverage_verification_can_invalidate_passing_cases(self) -> None:
        case: CaseResult = {"behavior_id": "case", "driver": "cli", "profile": "user",
                            "status": "passed"}
        report: RunReport = {"schema": 1, "results": [case],
                             "duration_seconds": 20.0,
                             "artifact_integrity": {"status": "verified"}}
        report["coverage"] = CoverageModel(Path(__file__).parent).summarize(report)
        report["coverage"]["verification"] = {"status": "invalid", "reason": "changed definitions"}
        stream = Capture()
        console = ConsoleOutput([case], stream, color=False)
        console.summary(report, Path("results"), 1)
        self.assertIn("INVALID | 20.00s wall time", stream.getvalue())
        self.assertIn("1 PASS", stream.getvalue())
        self.assertIn("Artifact integrity: verified; coverage verification: invalid",
                      stream.getvalue())
        self.assertNotIn("Selected cases passed", stream.getvalue())

    def test_color_policy(self) -> None:
        for tty in (False, True):
            for mode in ("auto", "always", "never"):
                for no_color in (None, "", "1", "0"):
                    with self.subTest(tty=tty, mode=mode, no_color=no_color):
                        env = {} if no_color is None else {"NO_COLOR": no_color}
                        self.assertEqual(use_color(mode, Capture(tty), env),
                                         not bool(no_color) and mode != "never"
                                         and (mode == "always" or tty))

    def test_safe_bounded_diagnostics(self) -> None:
        raw = "\x1b]0;title\x07\x1b[31mBad\x1b[0m\r\n\tvalue\x00\x08\u202e\x9b2J"
        self.assertEqual(safe_text(raw), "Bad value")
        self.assertEqual(safe_text("\x1bPsecret\x1b\\visible"), "visible")
        self.assertEqual(safe_text("x" * 500), "x" * 237 + "...")

    def test_setup_diagnostic_uses_its_status_color_and_flushes(self) -> None:
        stream = Capture()
        console = ConsoleOutput([], stream, color=True)
        console.setup_error("unsupported", "\x1b[31munsupported\ncapability")
        self.assertEqual(stream.flushed, ["\x1b[33mUNSUPPORTED\x1b[0m setup: "
                                          "unsupported capability\n"])

    def test_alignment_duration_and_flush_for_each_status(self) -> None:
        cases: list[CaseResult] = [
            {"behavior_id": "short" if index == 0 else "long.case.id", "driver": driver,
             "profile": "user", "status": status, "duration_seconds": 0.42}
            for index, (status, driver) in enumerate([
                ("passed", "cli"), ("failed", "library"), ("setup-error", "cli"),
                ("unmet-prerequisite", "cli"), ("unsupported", "library"),
            ])
        ]
        cases[1]["error"] = "\x1b[31mfailed\n" + "x" * 500
        cases[2]["cleanup_error"] = "cleanup failed"
        cases[4]["unsupported_capabilities"] = {"cli": "not implemented"}
        outputs = []
        for color in (False, True):
            stream = Capture()
            console = ConsoleOutput(cases, stream, color=color)
            for index, case in enumerate(cases, 1):
                console.case_finished(case)
                self.assertEqual(stream.flushed[-1], stream.getvalue())
                self.assertIn(f"[{index}/5]", stream.flushed[-1])
            output = stream.getvalue()
            self.assertNotIn("\r", output)
            lines = output.splitlines()
            plain = [re.sub(r"\x1b\[[0-9;]*m", "", line) for line in lines]
            outputs.append(plain)
            self.assertEqual(sum("0.42s" in line for line in lines), 5)
            self.assertIn("cleanup failed", output)
            self.assertIn("cli: not implemented", output)
            if color:
                for code in (31, 32, 33, 2):
                    self.assertIn(f"\x1b[{code}m", output)
            else:
                self.assertNotIn("\x1b", output)
            positions = [line.index("0.42s") for line in plain if line.startswith("[")]
            self.assertEqual(len(set(positions)), 1)
        self.assertEqual(*outputs)
        self.assertTrue(cases[1]["error"].startswith("\x1b[31m"))

    def test_saved_coverage_and_unverified_credit(self) -> None:
        report: RunReport = {"schema": 1, "artifact_integrity": {"status": "verified"}}
        coverage = CoverageModel(Path(__file__).parent).summarize(report)
        report["coverage"] = coverage
        coverage["verification"] = {"status": "current", "reason": "test"}
        metric = coverage["metrics"]["behaviors"]["cli"]
        metric.update({"passed": 17, "passed_percent": 12.5})
        self.assertEqual(coverage_rows(report)[0], ("CLI behaviors", "17 (12.5%)", "136"))
        self.assertEqual([row[2] for row in coverage_rows(report)],
                         ["136", "163", "44", "624", "223", "14"])
        self.assertIn("17 (12.5%)", github_summary(report, 0))
        for verification in ("stale", "unverified", "invalid"):
            coverage["verification"]["status"] = verification
            self.assertTrue(all(row[1] == "unverified" for row in coverage_rows(report)))
            self.assertNotIn("12.5%", github_summary(report, 0))
        coverage["verification"]["status"] = "current"
        report["artifact_integrity"]["status"] = "changed"
        self.assertIn("**INVALID**", github_summary(report, 0))
        self.assertNotIn("12.5%", github_summary(report, 0))
        self.assertTrue(all(row[1:] == ("unverified", "unverified")
                            for row in coverage_rows({"schema": 1})))

    def test_slowest_limit_ties_selection_and_markdown_escaping(self) -> None:
        cases: list[CaseResult] = [
            {"behavior_id": f"case-{index:02}", "driver": "cli", "profile": "user",
             "status": "failed", "duration_seconds": float(index // 2),
             "timings": {"setup_seconds": 0.0, "execution_seconds": float(index // 2),
                         "cleanup_seconds": 0.0}}
            for index in reversed(range(14))
        ]
        cases.extend([
            {"behavior_id": "blocked", "driver": "cli", "profile": "user",
             "status": "setup-error"},
            {"behavior_id": "excluded", "driver": "cli", "profile": "user",
             "status": "not-selected", "duration_seconds": 900.0},
        ])
        report: RunReport = {"schema": 1, "results": cases}
        self.assertEqual([case["behavior_id"] for case in slowest_cases(report)],
                         [f"case-{index:02}" for index in (12, 13, 10, 11, 8, 9, 6, 7, 4, 5)])
        cases[0]["behavior_id"] = "\x1b[31m|\n`[click](https://bad)<img>" + "x" * 500
        cases[0]["evidence"] = [{"stdout": "private credential"}]
        summary = github_summary(report, 1)
        self.assertNotIn("\x1b", summary)
        self.assertNotIn("private credential", summary)
        self.assertNotIn("<img>", summary)
        self.assertNotIn("[click]", summary)
        self.assertNotIn("x" * 241, summary)
        self.assertIn("**FAIL**", summary)
        self.assertIn("&#124;", summary)
        self.assertIn("&lt;img&gt;", summary)
        self.assertEqual(markdown_cell("a|\nb`c"), "a&#124; b&#96;c")
        self.assertEqual(markdown_cell("https://host mail@host"),
                         "https&#58;&#47;&#47;host mail&#64;host")
        self.assertEqual(markdown_cell("user's \"case\" | <b>& &#39;"),
                         "user's \"case\" &#124; &lt;b&gt;&amp; &amp;&#35;39;")
        self.assertEqual(sum(line.count("|") == 8 for line in summary.splitlines()), 12)


if __name__ == "__main__":
    unittest.main()
