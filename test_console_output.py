# SPDX-License-Identifier: LGPL-2.1-or-later
"""Console policy, safe diagnostics, layout, and immediate delivery."""

import io
import re
import unittest
from pathlib import Path

from console_output import ConsoleOutput, safe_text, use_color
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
                             "artifact_integrity": {"status": "verified"}}
        report["coverage"] = CoverageModel(Path(__file__).parent).summarize(report)
        report["coverage"]["verification"] = {"status": "invalid", "reason": "changed definitions"}
        stream = Capture()
        console = ConsoleOutput([case], stream, color=False, clock=lambda: 25.0, started=5.0)
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
        console = ConsoleOutput([], stream, color=True, clock=lambda: 0, started=0)
        console.setup_error("unsupported", "\x1b[31munsupported\ncapability")
        self.assertEqual(stream.flushed, ["\x1b[33mUNSUPPORTED\x1b[0m setup: "
                                          "unsupported capability\n"])

    def test_alignment_duration_and_flush_for_each_status(self) -> None:
        cases: list[CaseResult] = [
            {"behavior_id": "short" if index == 0 else "long.case.id", "driver": driver,
             "profile": "user", "status": status}
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
            console = ConsoleOutput(cases, stream, color=color, clock=lambda: 12.42, started=0)
            for index, case in enumerate(cases, 1):
                console.case_finished(case, 12)
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


if __name__ == "__main__":
    unittest.main()
