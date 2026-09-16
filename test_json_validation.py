# SPDX-License-Identifier: LGPL-2.1-or-later
"""The JSON boundary rejects ambiguous and non-JSON input."""

import unittest

from json_validation import ValidationError, decode_json, integer, json_value


class JsonValidationTests(unittest.TestCase):
    def test_duplicate_keys_include_the_input_context(self) -> None:
        with self.assertRaisesRegex(ValidationError, "target: duplicate JSON key: name"):
            decode_json('{"name": "first", "name": "second"}', "target")

    def test_nonfinite_numbers_are_not_accepted_as_json(self) -> None:
        for number in ("NaN", "Infinity", "-Infinity", "1e999"):
            with self.subTest(number=number), self.assertRaises(ValidationError):
                decode_json('{"value": ' + number + '}', "input")

    def test_booleans_and_floats_are_not_integer_fields(self) -> None:
        for value in (True, False, 1.0, "1"):
            with self.subTest(value=value), self.assertRaisesRegex(ValidationError, "schema"):
                integer(value, "schema")

    def test_json_payloads_are_detached_and_preserve_valid_output_text(self) -> None:
        source = {"text": "before\0after", "items": [1, {"value": True}]}
        parsed = json_value(source)
        source["text"] = "changed"
        self.assertEqual(parsed, {"text": "before\0after", "items": [1, {"value": True}]})
        self.assertEqual(json_value((1, "two")), [1, "two"])

    def test_non_json_objects_and_keys_are_rejected(self) -> None:
        for value in (b"bytes", {1: "value"}, object()):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                json_value(value)


if __name__ == "__main__":
    unittest.main()
