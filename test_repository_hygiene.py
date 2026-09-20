# SPDX-License-Identifier: LGPL-2.1-or-later
"""Keep local implementation details out of tracked repository content."""

import subprocess
import unittest
from pathlib import Path


class RepositoryHygieneTests(unittest.TestCase):
    def test_tracked_files_do_not_contain_local_identifiers(self) -> None:
        root = Path(__file__).resolve().parent
        paths = subprocess.run(
            ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
        ).stdout.split(b"\0")
        forbidden_identifier = "open" + "code"

        matches = []
        for raw_path in paths:
            if not raw_path:
                continue
            path = root / raw_path.decode()
            text = path.read_text(errors="ignore")
            if forbidden_identifier in text.lower():
                matches.append(str(path.relative_to(root)))

        self.assertEqual(matches, [], "local implementation identifier found in tracked files")


if __name__ == "__main__":
    unittest.main()
