# SPDX-License-Identifier: LGPL-2.1-or-later
"""Check help assertions against GLib's locale-dependent usage rendering."""

import subprocess
import unittest

from global_option_scenarios import _help


class HelpOutput:
    def __init__(self, output: str) -> None:
        self.output = output

    def cli_call(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(arguments, 0, self.output, "")

    def check(self, condition: bool, message: str) -> None:
        if not condition:
            raise AssertionError(message)


class HelpRenderingTests(unittest.TestCase):
    def test_global_and_command_usage_allow_locale_renderings(self) -> None:
        for ellipsis in ("…", "...", "?", ""):
            for command in (None, "build"):
                with self.subTest(ellipsis=ellipsis, command=command):
                    arguments = "COMMAND" if command is None else "DIRECTORY [COMMAND]"
                    prefix = "" if command is None else command + " "
                    output = (f"Usage:\n  /opt/bin/flatpak {prefix}[OPTION{ellipsis}] {arguments}\n"
                              "\nHelp Options:\n  -h, --help  Show help options\n")
                    self.assertEqual(_help(HelpOutput(output), command), output)

    def test_usage_must_identify_the_requested_command(self) -> None:
        output = "Usage:\n  flatpak install [OPTION?] REF\n\n  --help  Show help\n"
        with self.assertRaisesRegex(AssertionError, "command-specific usage"):
            _help(HelpOutput(output), "build")

    def test_help_option_must_have_a_description(self) -> None:
        output = "Usage:\n  flatpak [OPTION?] COMMAND\n\n  --help\n"
        with self.assertRaisesRegex(AssertionError, "described --help"):
            _help(HelpOutput(output), None)


if __name__ == "__main__":
    unittest.main()
