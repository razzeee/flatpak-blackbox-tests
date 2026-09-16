# SPDX-License-Identifier: LGPL-2.1-or-later
"""Export independent query inputs before any target scenario executes."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

from fixture_manifest import (
    FixtureManifest,
    FixturePolicyExtension,
    FixtureQueryEntries,
    FixtureQueryRef,
    FixtureQueryVersion,
    load_fixture,
    parse_fixture,
    parse_queries,
)

PROBE = r'''/* Independent sandbox synchronization fixture. */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
int main(void)
{
  char temporary[] = "/var/data/query-XXXXXX";
  char final[128];
  char buffer[4096];
  size_t count;
  int fd = mkstemp(temporary);
  FILE *input = fopen("/.flatpak-info", "rb");
  FILE *output = fd < 0 ? NULL : fdopen(fd, "wb");
  if (input == NULL || output == NULL)
    return 10;
  while ((count = fread(buffer, 1, sizeof buffer, input)) != 0)
    if (fwrite(buffer, 1, count, output) != count)
      return 11;
  if (ferror(input) || fclose(input) != 0 || fclose(output) != 0)
    return 12;
  snprintf(final, sizeof final, "%s.ready", temporary);
  if (rename(temporary, final) != 0)
    return 13;
  puts("query-probe-" VERSION);
  fflush(stdout);
  for (int i = 0; i < 60; i++)
    {
      if (access("/var/data/release", F_OK) == 0)
        return 0;
      sleep(1);
    }
  return 14;
}
'''


def png(size: int) -> bytes:
    """A valid, size-distinct RGB icon without an image-tool dependency."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))

    pixels = (b"\0" + bytes((size, 80, 160)) * size) * size
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def prepare(reference_cli: str, output: Path,
            fixture: FixtureManifest) -> FixtureQueryEntries:
    """Return {'queries': ...}; every artifact path is relative to output."""
    root = output / "query-inputs"
    root.mkdir()
    arch = str(fixture["arch"])
    foreign = "aarch64" if arch != "aarch64" else "x86_64"
    runtime = f"{fixture['runtime']}/{arch}/{fixture['branch']}"
    app = "org.flatpak.Query"
    second = "org.flatpak.QuerySecond"
    extension = app + ".Data"
    versions: dict[str, FixtureQueryVersion] = {}
    result: dict[str, object] = {"app": app, "second": second, "extension": extension,
                                 "foreign_arch": foreign, "versions": versions}

    def command(*args: str) -> str:
        return subprocess.check_output(args, text=True).strip()

    with tempfile.TemporaryDirectory(prefix="query-export-") as temporary:
        work = Path(temporary)
        source = work / "probe.c"
        source.write_text(PROBE)
        for version in ("A", "B"):
            repo = root / version
            shutil.copytree(output / "A" if version == "A" else root / "A", repo)
            refs: dict[str, FixtureQueryRef] = {}
            identities = [("app", app, arch, "master"),
                          ("app", app, arch, "test"),
                          ("app", second, arch, "test"),
                          ("app", second, foreign, "test"),
                          ("runtime", extension, arch, "test"),
                          ("runtime", extension, arch, "next")]
            for index, (kind, name, ref_arch, branch) in enumerate(identities):
                build = work / f"{version}-{index}"
                files = build / ("usr" if kind == "runtime" else "files")
                (files / "bin").mkdir(parents=True)
                command("cc", "-O2", "-Wall", "-Wextra", "-Werror",
                        f'-DVERSION="{version}"', str(source),
                        "-o", str(files / "bin/probe"))
                (files / "extra").mkdir()
                (files / "extra/payload").write_text(
                    "Excluded in partial installations\n")
                # files/extra is reserved for Flatpak extra-data deployment. Use
                # an ordinary directory for observable full/subset comparisons.
                (files / "subset-control").mkdir()
                (files / "subset-control/payload").write_text(
                    "Independent full-install payload\n")
                metadata = (f"[Runtime]\nname={name}\n" if kind == "runtime" else
                            f"[Application]\nname={name}\nruntime={runtime}\n"
                            f"sdk={runtime}\ncommand=probe\n[Context]\nshared=network;\n")
                if name == app:
                    ext_branch = "test" if version == "A" else "next"
                    search_term = "amberquartz" if version == "A" else "violetcobalt"
                    metadata += (f"[Extension {extension}]\ndirectory=data\n"
                                 f"version={ext_branch}\nno-autodownload=true\n"
                                 "autodelete=true\n")
                    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                           '<components version="0.8" origin="flatpak">\n'
                           '  <component type="desktop">'
                           f"<id>{app}</id><name>Query fixture</name>"
                           "<summary>Controlled query metadata</summary>"
                           f"<description><p>Query {search_term} "
                           "search description</p></description>"
                           "<project_license>MIT</project_license>"
                           '<releases><release version="1.2.3" date="2026-01-01"/>'
                           '</releases><content_rating type="oars-1.1">'
                           '<content_attribute id="violence-cartoon">'
                           'none</content_attribute>'
                           '</content_rating>  <bundle type="flatpak" '
                           f'runtime="{runtime}" sdk="{runtime}">'
                           f"app/{name}/{ref_arch}/{branch}</bundle>\n"
                           "  </component>\n</components>\n")
                    compressed = gzip.compress(xml.encode(), mtime=0)
                    xml_path = files / f"share/app-info/xmls/{app}.xml.gz"
                    xml_path.parent.mkdir(parents=True)
                    xml_path.write_bytes(compressed)
                    for size in (64, 128):
                        icon = (files / "share/app-info/icons/flatpak"
                                / f"{size}x{size}/{app}.png")
                        icon.parent.mkdir(parents=True)
                        icon.write_bytes(png(size))
                    if version == "A" and branch == "test":
                        (root / "appstream.xml").write_text(xml)
                        for size in (64, 128):
                            (root / f"icon-{size}.png").write_bytes(png(size))
                (build / "metadata").write_text(metadata)
                if kind == "runtime":
                    (build / "files").mkdir()
                else:
                    command(reference_cli, "build-finish", str(build))
                flags = ["--runtime"] if kind == "runtime" else []
                command(reference_cli, "build-export", "--disable-sandbox",
                        f"--arch={ref_arch}", *flags, str(repo), str(build), branch)
                ref = f"{kind}/{name}/{ref_arch}/{branch}"
                commit = command("ostree", f"--repo={repo}", "rev-parse", ref)
                sizes: dict[str, int] = {}
                for key in ("installed", "download"):
                    raw = command("ostree", f"--repo={repo}", "show",
                                  f"--print-metadata-key=xa.{key}-size", ref)
                    # ostree show presents these well-known keys in host byte order.
                    sizes[key] = int(raw.split()[-1])
                metadata_path = root / f"metadata-{version}-{index}"
                metadata_path.write_text(command("ostree", f"--repo={repo}",
                                                 "cat", ref, "/metadata") + "\n")
                refs[ref] = {"commit": commit,
                             "installed": sizes["installed"], "download": sizes["download"],
                             "metadata": str(metadata_path.relative_to(output))}
            command(reference_cli, "build-update-repo", str(repo))
            cache_xml = root / f"cache-appstream-{version}.xml"
            compressed_cache = subprocess.check_output(
                ["ostree", f"--repo={repo}", "cat", f"appstream/{arch}",
                 "/appstream.xml.gz"])
            cache_xml.write_bytes(gzip.decompress(compressed_cache))
            versions[version] = {
                "repo": str(repo.relative_to(output)), "refs": refs,
                "appstream": str(cache_xml.relative_to(output))}
        url_flags = ["--repo-url=https://example.invalid/query",
                     "--runtime-repo=https://example.invalid/runtime.flatpakrepo"]
        for suffix, flags in (("urls", url_flags), ("plain", [])):
            bundle = root / f"{suffix}.flatpak"
            command(reference_cli, "build-bundle", *flags, str(root / "A"),
                    str(bundle), app, "test")
            result[f"bundle_{suffix}"] = str(bundle.relative_to(output))
            # Public OSTree delta inspection prints superblock part sizes before
            # trying detached part files. Inline bundles have no detached files.
            inspection = subprocess.run(
                ["ostree", f"--repo={root / 'A'}", "static-delta", "show", str(bundle)],
                text=True, capture_output=True, check=False)
            part_sizes = re.findall(r"^PartMeta\d+: nobjects=\d+ size=\d+ usize=(\d+)$",
                                    inspection.stdout, re.MULTILINE)
            parts = re.search(r"^Number of parts: (\d+)$",
                              inspection.stdout, re.MULTILINE)
            if (parts is None or len(part_sizes) != int(parts[1]) or not part_sizes
                    or "Number of fallback entries: 0\n" not in inspection.stdout):
                raise RuntimeError(f"Cannot inspect bundle part sizes: {inspection}")
            result[f"bundle_{suffix}_size"] = sum(map(int, part_sizes))
        policy_repo = root / "policy"
        policy_app = "org.flatpak.QueryPolicy"
        policy_ref = f"app/{policy_app}/{arch}/test"
        policy_extensions: list[FixturePolicyExtension] = []
        policy_metadata = (f"[Application]\nname={policy_app}\nruntime={runtime}\n"
                           f"sdk={runtime}\ncommand=probe\n")
        for suffix, no_autodownload, autodelete in (
            ("Automatic", False, False), ("Optional", True, True)
        ):
            extension_name = f"{policy_app}.{suffix}"
            policy_metadata += (
                f"[Extension {extension_name}]\ndirectory={suffix.lower()}\nversion=test\n"
                f"no-autodownload={str(no_autodownload).lower()}\n"
                f"autodelete={str(autodelete).lower()}\n")
            build = work / f"policy-{suffix}"
            (build / "usr").mkdir(parents=True)
            (build / "files").mkdir()
            (build / "usr/payload").write_text(f"Policy fixture {suffix}\n")
            (build / "metadata").write_text(
                f"[Runtime]\nname={extension_name}\n[ExtensionOf]\nref={policy_ref}\n")
            command(reference_cli, "build-export", "--disable-sandbox", "--runtime",
                    f"--arch={arch}", str(policy_repo), str(build), "test")
            extension_ref = f"runtime/{extension_name}/{arch}/test"
            policy_extensions.append({
                "ref": extension_ref,
                "commit": command("ostree", f"--repo={policy_repo}", "rev-parse", extension_ref),
                "no_autodownload": no_autodownload, "autodelete": autodelete,
                "should_download": not no_autodownload, "should_delete": autodelete})
        policy_build = work / "policy-app"
        (policy_build / "files/bin").mkdir(parents=True)
        command("cc", "-O2", "-Wall", "-Wextra", "-Werror", '-DVERSION="policy"',
                str(source), "-o", str(policy_build / "files/bin/probe"))
        (policy_build / "metadata").write_text(policy_metadata)
        command(reference_cli, "build-finish", str(policy_build))
        command(reference_cli, "build-export", "--disable-sandbox", f"--arch={arch}",
                str(policy_repo), str(policy_build), "test")
        command(reference_cli, "build-update-repo", str(policy_repo))
        policy_metadata_path = root / "policy-metadata"
        policy_metadata_path.write_text(command(
            "ostree", f"--repo={policy_repo}", "cat", policy_ref, "/metadata") + "\n")
        result.update(
            policy_repo=str(policy_repo.relative_to(output)), policy_ref=policy_ref,
            policy_commit=command("ostree", f"--repo={policy_repo}", "rev-parse", policy_ref),
            policy_metadata=str(policy_metadata_path.relative_to(output)),
            policy_extensions=policy_extensions)
        # Separate refs keep the original enumeration and runtime contracts intact.
        selection_repo = root / "selection"
        shutil.copytree(output / "A", selection_repo)
        selection_commits: dict[str, str] = {}
        alternate = "org.flatpak.SelectionPlatform"
        selected = "org.flatpak.Selection"
        locale = selected + ".Locale"
        for kind, name in (("runtime", alternate), ("runtime", locale),
                           ("app", selected), ("app", selected + "Other")):
            build = work / name
            if name == alternate:
                shutil.copytree(output / fixture["assets"]["runtime_tree"], build)
                metadata = f"[Runtime]\nname={name}\n"
            elif name == locale:
                (build / "files").mkdir(parents=True)
                for language in ("de", "fr", "ja", "es"):
                    (build / "files" / language).mkdir(parents=True)
                    (build / "files" / language / "marker").write_text(language + "\n")
                metadata = (f"[Runtime]\nname={name}\n[ExtensionOf]\n"
                            f"ref=app/{selected}/{arch}/test\n")
            else:
                shutil.copytree(output / fixture["assets"]["app_tree"], build)
                used_runtime = runtime if name == selected else f"{alternate}/{arch}/test"
                metadata = (f"[Application]\nname={name}\nruntime={used_runtime}\n"
                            f"sdk={used_runtime}\ncommand=blackbox-probe\n")
                if name == selected:
                    metadata += (f"[Extension {locale}]\ndirectory=share/locale\n"
                                 "version=test\nlocale-subset=true\nautodelete=true\n")
            (build / "metadata").write_text(metadata)
            flags = ["--runtime"] if kind == "runtime" else []
            command(reference_cli, "build-export", "--disable-sandbox", f"--arch={arch}",
                    *flags, str(selection_repo), str(build), "test")
            ref = f"{kind}/{name}/{arch}/test"
            selection_commits[ref] = command("ostree", f"--repo={selection_repo}",
                                             "rev-parse", ref)
        command(reference_cli, "build-update-repo", str(selection_repo))
        result.update(selection_repo=str(selection_repo.relative_to(output)),
                      selection_commits=selection_commits)
    result["appstream"] = str((root / "appstream.xml").relative_to(output))
    result["icons"] = {str(size): str((root / f"icon-{size}.png").relative_to(output))
                       for size in (64, 128)}
    return {"queries": parse_queries(result, "fixture.queries", arch=arch)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--flatpak", default="flatpak")
    args = parser.parse_args()
    fixture = load_fixture(args.baseline / "fixture.json")
    args.output.mkdir(parents=True, exist_ok=False)
    for version in ("A", "B"):
        shutil.copytree(args.baseline / version, args.output / version)
    for asset in fixture["assets"].values():
        shutil.copytree(args.baseline / asset, args.output / asset, symlinks=True)
    fixture["queries"] = prepare(args.flatpak, args.output, fixture)["queries"]
    fixture["sha256"] = {
        path.relative_to(args.output).as_posix():
            hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(args.output.rglob("*")) if path.is_file()
    }
    (args.output / "fixture.json").write_text(json.dumps(parse_fixture(fixture), indent=2) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
