# SPDX-License-Identifier: LGPL-2.1-or-later
"""Compile real probes against controlled public headers and link symbols."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from library_features import FEATURES, missing_apis, probe_features
from report_schema import EvidenceRecord
from run import execute


@unittest.skipUnless(shutil.which("cc"), "requires a C compiler")
class LibraryFeatureTests(unittest.TestCase):
    def test_headers_and_link_library_must_both_provide_the_api(self) -> None:
        api = FEATURES[0].name
        for header, symbol in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(header=header, symbol=symbol), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "flatpak.h").write_text(
                    "#include <stddef.h>\n"
                    "typedef unsigned long long guint64;\n"
                    "typedef struct Progress FlatpakTransactionProgress;\n"
                    + (f"guint64 {api}(FlatpakTransactionProgress *);\n" if header else "")
                )
                implementation = root / "library.c"
                implementation.write_text(
                    f"unsigned long long {api}(void *p) {{ (void)p; return 0; }}\n"
                    if symbol else "int unrelated(void) { return 0; }\n"
                )
                evidence: list[EvidenceRecord] = []
                available = probe_features(
                    "cc", ["-O2", f"-I{root}", str(implementation)], dict(os.environ), root,
                    evidence, 10, execute,
                )
                self.assertEqual(available[api], header and symbol)
                self.assertEqual(missing_apis("transaction.progress", available), [])
                self.assertEqual(missing_apis("transaction.rate", available),
                                 [] if header and symbol else [api])
                # A dependent client must compile with either feature result, and
                # must not accidentally reference a missing symbol in its fallback.
                client = root / "client.c"
                client.write_text(
                    '#include <flatpak.h>\n#include "blackbox-features.h"\n'
                    "int main(void) {\n"
                    f"#if {FEATURES[0].macro}\n"
                    f"return {api}(NULL) != 0;\n"
                    "#else\nreturn 77;\n#endif\n}\n"
                )
                compiled = subprocess.run(
                    ["cc", "-Werror", f"-I{root}", str(client), str(implementation),
                     "-o", str(root / "client")], capture_output=True, text=True, check=False,
                )
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                self.assertEqual(subprocess.run([str(root / "client")], check=False).returncode,
                                 0 if header and symbol else 77)
                self.assertTrue(any(record.get("observation") == "library-api-availability"
                                    for record in evidence))

    def test_broken_toolchain_is_not_missing_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "flatpak.h").write_text("#error broken SDK\n")
            with self.assertRaisesRegex(ValueError, "library API probe baseline did not compile"):
                probe_features("cc", [f"-I{root}"], dict(os.environ), root, [], 10, execute)

    def test_changed_signature_is_unavailable_even_with_the_symbol_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            api = FEATURES[0].name
            (root / "flatpak.h").write_text(
                "#include <stddef.h>\ntypedef unsigned long long guint64;\n"
                "typedef struct Progress FlatpakTransactionProgress;\n"
                f"int {api}(FlatpakTransactionProgress *);\n"
            )
            implementation = root / "library.c"
            implementation.write_text(f"int {api}(void *p) {{ (void)p; return 0; }}\n")
            available = probe_features("cc", ["-O2", f"-I{root}", str(implementation)],
                                       dict(os.environ), root, [], 10, execute)
            self.assertFalse(available[api])


if __name__ == "__main__":
    unittest.main()
