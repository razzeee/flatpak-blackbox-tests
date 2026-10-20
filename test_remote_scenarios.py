# SPDX-License-Identifier: LGPL-2.1-or-later
"""Negative controls for the public library remote ordering contract."""

import itertools
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from remote_scenarios import RemoteRow, remote_priority_order
from run import ContractFailure, Driver


class RemotePriorityOrderTests(unittest.TestCase):
    url = "http://repository.example/repo"
    first: RemoteRow = ("remote-z-first", url, "Earlier tied remote", "20")
    second: RemoteRow = ("remote-a-second", url, "Later tied remote", "20")
    low: RemoteRow = ("remote-low", url, "Lower priority remote", "10")

    def exercise(self, rows: list[RemoteRow]) -> None:
        driver = Driver("library", "/target/flatpak", None, {}, Path("."), [], 1)
        listed = False

        def output(operation: str, *arguments: str) -> str:
            nonlocal listed
            if operation == "remote-create":
                return ""
            if operation == "remote-list":
                if not listed:
                    listed = True
                    return ""
                return "\n".join("\t".join(str(field) for field in row) for row in rows)
            if operation == "remote-query":
                row = next(row for row in rows if row[0] == arguments[0])
                return "\t".join(str(field) for field in row)
            self.fail(f"unexpected operation: {operation}")

        with patch.object(driver, "success", side_effect=output) as success:
            remote_priority_order(driver, Mock(), self.url, Mock())
        self.assertEqual([c for c in success.call_args_list if c.args[0] == "remote-create"], [
            call("remote-create", *self.first),
            call("remote-create", *self.second),
            call("remote-create", *self.low),
        ])

    def test_only_descending_priority_and_ascending_name_order_passes(self) -> None:
        expected = [self.second, self.first, self.low]
        for rows in itertools.permutations(expected):
            with self.subTest(names=[row[0] for row in rows]):
                if list(rows) == expected:
                    self.exercise(list(rows))
                else:
                    with self.assertRaisesRegex(ContractFailure, "expected remotes"):
                        self.exercise(list(rows))

    def test_missing_duplicate_and_changed_rows_fail(self) -> None:
        for rows in (
            [self.second, self.first],
            [self.second, self.first, self.low, self.low],
            [self.second, self.first, (*self.low[:3], "20")],
        ):
            with self.subTest(rows=rows), self.assertRaisesRegex(
                ContractFailure, "expected remotes"
            ):
                self.exercise(rows)


if __name__ == "__main__":
    unittest.main()
