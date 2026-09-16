# SPDX-License-Identifier: LGPL-2.1-or-later
"""Target configuration is validated before process construction."""

import unittest

from json_validation import ValidationError
from target_config import parse_environment, parse_target


class TargetConfigTests(unittest.TestCase):
    @staticmethod
    def target() -> dict[str, object]:
        return {"name": "test target", "cli": "flatpak", "adapter": ["python3", "adapter.py"]}

    def test_cli_only_defaults_and_detached_configuration(self) -> None:
        data = self.target()
        adapter = ["python3", "adapter.py", ""]
        environment = {"EMPTY": "", "PATH": "/usr/bin"}
        data.update(adapter=adapter, environment=environment)
        target = parse_target(data)
        adapter.append("later")
        environment["PATH"] = "/changed"
        self.assertEqual(target.adapter, ("python3", "adapter.py", ""))
        self.assertEqual(target.environment["PATH"], "/usr/bin")
        self.assertEqual(target.environment["EMPTY"], "")
        self.assertIsNone(target.library)
        self.assertEqual(target.unsupported_capabilities, {})

    def test_library_settings_have_concrete_defaults(self) -> None:
        data = self.target()
        data["library"] = {"runtime_library_dirs": ["/opt/target/lib"],
                           "environment": {"PKG_CONFIG_PATH": "/opt/target/lib/pkgconfig"}}
        library = parse_target(data).library
        self.assertIsNotNone(library)
        assert library is not None
        self.assertEqual(library.runtime_library_dirs, ("/opt/target/lib",))
        self.assertEqual(library.pkg_config, "pkg-config")
        self.assertEqual(library.package, "flatpak")
        self.assertEqual(library.cc, "cc")
        self.assertEqual(library.soname, "libflatpak.so.0")

    def test_invalid_root_and_missing_required_fields(self) -> None:
        values: tuple[object, ...] = (None, [], "target")
        for value in values:
            with self.subTest(value=value), self.assertRaisesRegex(ValidationError, "target"):
                parse_target(value)
        for key in ("name", "cli", "adapter"):
            data = self.target()
            del data[key]
            with self.subTest(key=key), self.assertRaisesRegex(ValidationError, f"target.{key}"):
                parse_target(data)

    def test_command_vectors_reject_wrong_types_and_nul(self) -> None:
        values: tuple[object, ...] = ([], "python3 adapter.py", [7], [""], ["python3", "a\0b"])
        for value in values:
            data = self.target()
            data["adapter"] = value
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValidationError, "target.adapter"),
            ):
                parse_target(data)

    def test_environment_is_not_an_untyped_subprocess_escape(self) -> None:
        values: tuple[object, ...] = ({"A": 1}, {"A": None}, {"A=B": "value"},
                                      {"": "value"}, {"A": "a\0b"}, [])
        for value in values:
            with self.subTest(value=value), self.assertRaisesRegex(ValidationError, "adapter"):
                parse_environment(value, "adapter")

    def test_library_nested_fields_identify_the_bad_path(self) -> None:
        data = self.target()
        data["library"] = {"runtime_library_dirs": ["/valid", False]}
        with self.assertRaisesRegex(ValidationError, r"target.library.runtime_library_dirs\[1\]"):
            parse_target(data)
        data["library"] = {"environment": {"PKG_CONFIG_PATH": 3}}
        with self.assertRaisesRegex(ValidationError, "target.library.environment.PKG_CONFIG_PATH"):
            parse_target(data)

    def test_misspelled_configuration_and_untyped_reasons_are_rejected(self) -> None:
        data = self.target()
        data["enviroment"] = {}
        with self.assertRaisesRegex(ValidationError, "target.enviroment"):
            parse_target(data)
        data = self.target()
        data["unsupported_capabilities"] = {"sandbox-execution": False}
        with self.assertRaisesRegex(ValidationError, "target.unsupported_capabilities"):
            parse_target(data)


if __name__ == "__main__":
    unittest.main()
