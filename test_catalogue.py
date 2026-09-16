# SPDX-License-Identifier: LGPL-2.1-or-later
"""Public-CLI regression tests; fixtures need neither GLib nor a built Flatpak."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).with_name("catalogue.py")

MAIN = """
static FlatpakCommand commands [] = {
  { N_(" Commands") },
  { "update", N_("Update, with punctuation"), flatpak_builtin_update,
    flatpak_complete_update, FALSE },
  { "upgrade", NULL, flatpak_builtin_update, flatpak_complete_update, TRUE },
  { "remotes", N_("List"), flatpak_builtin_remote_list, flatpak_complete_remote_list },
  { "remote-list", NULL, flatpak_builtin_remote_list, flatpak_complete_remote_list, TRUE },
  { NULL }
};
GOptionEntry global_entries [] = {
  { "help", '?', 0, G_OPTION_ARG_NONE, &help, NULL, NULL },
  { NULL }
};
static GOptionEntry empty_entries [] = {
  { "version", 0, 0, G_OPTION_ARG_NONE, &version, N_("Version"), NULL },
  { NULL }
};
"""

HEADER = """
#define FLATPAK_TYPE_PUBLIC flatpak_public_get_type ()
typedef struct _FlatpakPublic FlatpakPublic;
FLATPAK_EXTERN GType flatpak_public_get_type (void);
FLATPAK_EXTERN
G_DECLARE_FINAL_TYPE (FlatpakProgress, flatpak_progress, FLATPAK, PROGRESS, GObject)
/* flatpak_comment_not_a_function (void); */
FLATPAK_EXTERN
const char * const *
flatpak_public_read (
    FlatpakPublic *self,
    void (*callback) (int, int));
G_GNUC_DEPRECATED_FOR (flatpak_public_read)
FLATPAK_EXTERN void flatpak_public_old (void);
typedef enum {
  FLATPAK_TEST_NONE,
  FLATPAK_TEST_ONE = (1 << 0),
} FlatpakTestFlags;
struct _FlatpakPublicClass {
  GObjectClass parent_class;
  void (*changed) (FlatpakPublic *self);
};
"""

SIGNALS = """
static void
flatpak_progress_class_init (FlatpakProgressClass *klass)
{
  /**
   * FlatpakProgress::changed:
   * Emitted when progress changes.
   */
  signals[CHANGED] = g_signal_new (
    "changed", G_TYPE_FROM_CLASS (klass), G_SIGNAL_RUN_LAST, 0,
    NULL, NULL, NULL, G_TYPE_NONE, 0);
}
static void
flatpak_private_class_init (FlatpakPrivateClass *klass)
{
  /* No gtk-doc block: private signals must not enlarge the public denominator. */
  signals[CHANGED] = g_signal_new ("private-changed", G_TYPE_FROM_CLASS (klass),
                                  G_SIGNAL_RUN_LAST, 0, NULL, NULL, NULL, G_TYPE_NONE, 0);
}
"""


MESON = """
public_headers = [
  'flatpak-public.h', # a comment
]
install_headers(public_headers, subdir: 'flatpak')
sources = ['flatpak-public.c']
libflatpak = library('flatpak', sources: sources)
"""


def manual(entries: str) -> str:
    return f"""<?xml version="1.0"?>
<!DOCTYPE refentry PUBLIC "-//OASIS//DTD DocBook XML V4.5//EN"
  "https://example.invalid/never-fetch.dtd" [<!ENTITY value "VALUE">]>
<refentry xmlns:xi="http://www.w3.org/2001/XInclude">
  <refsynopsisdiv><arg>OPTION</arg><option>--synopsis-only</option></refsynopsisdiv>
  <refsect1><title>Options</title>
    <para>A reference to <option>--prose-only</option>.</para>
    <variablelist>{entries}</variablelist>
  </refsect1>
</refentry>"""


def option(*names: str) -> str:
    terms = "".join(f"<term><option>{name}</option></term>" for name in names)
    return f"<varlistentry>{terms}<listitem><para>Explanation.</para></listitem></varlistentry>"


class CatalogueCLI(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "output.json"
        self.write("app/flatpak-main.c", MAIN)
        self.write("doc/flatpak.xml", manual(option("-h", "--help") + option("--version")))
        self.write("doc/flatpak-update.xml", manual(
            option("--user") + option("-f", "--no-filter", "--filter=&value;")
            + option("-z")
            + '<para>See <option>--filter=OTHER</option> and <option>--no-filter</option>.</para>'
            + '<xi:include href="permissions.xml" xpointer="element(permissions)"/>'
        ))
        # Historical filename deliberately differs from the active command.
        self.write("doc/flatpak-remote-list.xml", manual(option("--user")))
        self.write("doc/permissions.xml", '<variablelist id="permissions">'
                   + option("--filesystem=<replaceable>PATH</replaceable>") + '</variablelist>')
        self.write("common/meson.build", MESON)
        self.write("common/flatpak-public.h", HEADER)
        self.write("common/flatpak-private.h", "FLATPAK_EXTERN void flatpak_private_hidden (void);")
        self.write("common/flatpak-public.c", SIGNALS)
        self.write(
            "common/flatpak-enum-types.h.template",
            "FLATPAK_EXTERN GType @enum_name@_get_type (void);",
        )
        self.git("init", "--quiet")
        self.new_commit()

    def write(self, path: str, text: str) -> None:
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True
        ).stdout.strip()

    def new_commit(self) -> None:
        self.git("-c", "user.name=Catalogue test", "-c", "user.email=catalogue@example.invalid",
                 "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                 "commit", "--quiet", "--allow-empty", "-m", "Fixture reference")

    def cli(self, *args: str, success: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--source-root", str(self.root),
             "--output", str(self.output), *args], capture_output=True, text=True, check=False,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("catalogue:", result.stderr)
        return result

    def data(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.output.read_text(encoding="utf-8"))
        return data

    def test_denominator_aliases_deprecated_api_signals_and_hashes(self) -> None:
        self.cli()
        data = self.data()
        self.assertEqual(set(data), {"schema", "reference", "limitations", "surfaces"})
        self.assertEqual(data["schema"], 1)
        items = {item["id"]: item for item in data["surfaces"]}
        self.assertEqual(set(items), {
            "cli.command.update", "cli.command.remotes",
            "cli.option.global.--help", "cli.option.global.--version",
            "cli.option.update.--user", "cli.option.remotes.--user",
            "cli.option.update.--filter", "cli.option.update.--no-filter",
            "cli.option.update.--filesystem",
            "library.function.flatpak_public_read", "library.function.flatpak_public_old",
            "library.signal.FlatpakProgress.changed",
        })
        for name, other in (("--filter", "--no-filter"), ("--no-filter", "--filter")):
            item = items[f"cli.option.update.{name}"]
            self.assertEqual(item["aliases"], [])
            self.assertEqual(item["documented_with"], [other])
            self.assertEqual(len(item["sources"]), 1)
        self.assertEqual(items["cli.option.global.--help"]["aliases"], ["-?", "-h"])
        self.assertEqual(
            items["library.signal.FlatpakProgress.changed"]["sources"][0]["anchor"],
            "FlatpakProgress::changed",
        )
        self.assertEqual(
            items["cli.option.update.--filesystem"]["sources"][0]["path"], "doc/permissions.xml"
        )
        self.assertTrue(items["library.function.flatpak_public_old"]["deprecated"])
        self.assertEqual(
            items["library.function.flatpak_public_old"]["replacement"], "flatpak_public_read"
        )
        self.assertFalse(items["library.function.flatpak_public_read"]["deprecated"])
        limitations = "\n".join(data["limitations"])
        self.assertIn("Excluded short-only option group update -z", limitations)
        for excluded in ("upgrade -> update", "remote-list -> remotes", "flatpak_public_get_type",
                         "flatpak_progress_get_type", "flatpak_test_flags_get_type",
                         "FlatpakPrivate::private-changed"):
            self.assertIn(excluded, limitations)
        hashes = data["reference"]["sources"]
        self.assertNotIn("common/flatpak-private.h", hashes)
        self.assertIn("common/flatpak-enum-types.h.template", hashes)
        for path, digest in hashes.items():
            self.assertEqual(digest, hashlib.sha256((self.root / path).read_bytes()).hexdigest())
        self.assertEqual(data["reference"]["commit"], self.git("rev-parse", "HEAD"))
        original = self.output.read_bytes()
        self.cli()
        self.assertEqual(original, self.output.read_bytes())

    def test_check_ignores_only_head_and_detects_source_and_output_drift(self) -> None:
        self.cli()
        original = self.output.read_bytes()
        self.new_commit()
        self.cli("--check")
        self.assertEqual(original, self.output.read_bytes())
        # Even a source comment changes the provenance, without changing IDs.
        self.write("common/flatpak-public.h", HEADER + "\n/* source drift */\n")
        self.assertIn("drift", self.cli("--check", success=False).stderr)
        self.write("common/flatpak-public.h", HEADER)
        data = self.data()
        data["surfaces"].pop()
        self.output.write_text(json.dumps(data), encoding="utf-8")
        self.assertIn("drift", self.cli("--check", success=False).stderr)

    def test_missing_docs_unknown_entity_and_include_fail_loudly(self) -> None:
        doc = "doc/flatpak-update.xml"
        (self.root / doc).unlink()
        self.assertIn("Missing command manual", self.cli(success=False).stderr)
        self.write(doc, manual(option("--value=&unknown;")))
        self.assertIn("Unresolved or malformed XML", self.cli(success=False).stderr)
        self.write(doc, manual('<xi:include href="missing.xml"/>'))
        self.assertIn("missing.xml", self.cli(success=False).stderr)
        self.assertFalse(self.output.exists())

    def test_shared_xml_entity_and_arbitrarily_named_option_section(self) -> None:
        document = manual("&permissions;")
        document = document.replace(
            '<!ENTITY value "VALUE">', '<!ENTITY permissions SYSTEM "permissions.xml">'
        )
        document = document.replace("<title>Options</title>", "<title>Sandbox permissions</title>")
        self.write("doc/flatpak-update.xml", document)
        self.cli()
        item = next(
            item for item in self.data()["surfaces"]
            if item["id"] == "cli.option.update.--filesystem"
        )
        self.assertEqual(item["sources"][0]["path"], "doc/permissions.xml")

    def test_unaccounted_public_declaration_and_signal_fail(self) -> None:
        self.write("common/flatpak-public.h", HEADER + "\nvoid flatpak_new_api (void);\n")
        self.assertIn("Unaccounted public declarations", self.cli(success=False).stderr)
        self.write("common/flatpak-public.h", HEADER)
        self.write(
            "common/flatpak-public.c",
            SIGNALS.replace("FlatpakProgress::changed:", "Not a signal block"),
        )
        self.assertIn("Undocumented signal registration", self.cli(success=False).stderr)

    def test_new_registration_missing_global_doc_fails(self) -> None:
        self.write("app/flatpak-main.c", MAIN.replace('"version"', '"new-global-option"'))
        self.assertIn("Global option mismatch", self.cli(success=False).stderr)

    def test_repeated_long_definitions_merge_sources_and_short_aliases(self) -> None:
        self.write("doc/flatpak-update.xml", manual(
            option("--no-filter", "--filter=FILE") + option("-f", "--filter=PATH")
            + '<xi:include href="permissions.xml"/>'
            + '<para>See <option>--filter=OTHER</option>.</para>'
        ))
        self.write(
            "doc/permissions.xml", '<variablelist>' + option("--filter=FILE") + '</variablelist>'
        )
        self.cli()
        items = {item["id"]: item for item in self.data()["surfaces"]
                 if item["id"].startswith("cli.option.update.")}
        self.assertEqual(
            set(items), {"cli.option.update.--filter", "cli.option.update.--no-filter"}
        )
        item = items["cli.option.update.--filter"]
        self.assertEqual(item["aliases"], ["-f"])
        self.assertEqual(item["documented_with"], ["--no-filter"])
        definitions = [
            source for source in item["sources"] if source["anchor"].startswith("varlistentry/")
        ]
        self.assertEqual(len(definitions), 3)
        self.assertNotEqual(definitions[0]["anchor"], definitions[1]["anchor"])
        self.assertEqual(definitions[2]["path"], "doc/permissions.xml")
        self.assertEqual(items["cli.option.update.--no-filter"]["aliases"], [])

    def test_header_list_reassignment_and_indirect_installation_fail(self) -> None:
        mutations = [
            MESON + "\npublic_headers = ['another.h']\n",
            MESON + "\npublic_headers = another_list\n",
            MESON + "\npublic_headers += ['another.h']\n",
            MESON.replace("install_headers(public_headers,", "install_headers(another_list,"),
            MESON.replace("install_headers(public_headers,", "install_headers(['another.h'],"),
        ]
        for mutation in mutations:
            with self.subTest(meson=mutation):
                self.write("common/meson.build", mutation)
                self.assertRegex(
                    self.cli(success=False).stderr,
                    "public_headers assignment|install_headers arguments",
                )
                self.assertFalse(self.output.exists())

    def test_indirect_library_sources_and_source_reassignment_fail(self) -> None:
        mutations = [
            MESON.replace("sources = ['flatpak-public.c']", "sources = another_list"),
            MESON + "\nsources += another_list\n",
            MESON + "\nsources = ['another.c']\n",
            MESON.replace("sources: sources", "sources: another_list"),
            MESON.replace("sources: sources", "another_list"),
            MESON.replace("sources: sources", "sources: files('another.c')"),
            MESON.replace("sources: sources", "sources: sources + another_list"),
        ]
        for mutation in mutations:
            with self.subTest(meson=mutation):
                self.write("common/meson.build", mutation)
                self.assertRegex(
                    self.cli(success=False).stderr,
                    "Unsupported Meson library source expression|source-list reassignment",
                )
                self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
