# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exercise the total estimate oracle without imposing ordering on estimates."""

import unittest
from typing import cast

from report_schema import EvidenceRecord
from run import Driver
from transaction_scenarios import _check_bytes_total


class ProgressDriver:
    def __init__(self) -> None:
        self.evidence: list[EvidenceRecord] = []

    def check(self, condition: bool, message: str) -> None:
        if not condition:
            raise AssertionError(message)


class BytesTotalTests(unittest.TestCase):
    def samples(self) -> list[list[str]]:
        return [
            ["bytes-total", "new", "1", "0", "0"],
            ["bytes-total", "changed", "1", "10", "0"],
            ["bytes-total", "changed", "0", "100", "4000"],
            ["bytes-total", "changed", "0", "2048", "2000"],
            ["bytes-total", "changed", "0", "0", "0"],
        ]

    def test_estimates_may_decrease_and_become_unknown(self) -> None:
        driver = ProgressDriver()
        _check_bytes_total(cast(Driver, driver), self.samples(), 2048)
        self.assertEqual(driver.evidence[0]["observation"], "progress-bytes-total")

    def test_rejects_missing_or_incorrect_total_observations(self) -> None:
        for mutation in ("no-calls", "no-initial", "estimating", "always-zero", "no-transfer"):
            rows = self.samples()
            if mutation == "no-calls":
                rows = []
            elif mutation == "no-initial":
                rows = rows[1:]
            elif mutation == "estimating":
                rows[1][4] = "100"
            elif mutation == "always-zero":
                for row in rows:
                    row[4] = "0"
            else:
                for row in rows:
                    row[3] = "0"
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                _check_bytes_total(cast(Driver, ProgressDriver()), rows, 2048)


if __name__ == "__main__":
    unittest.main()
