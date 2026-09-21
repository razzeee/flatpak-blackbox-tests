# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reference Flatpak setup adapter: print isolated target environment as JSON."""

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path


def repair_fixture(root: Path, operation: str, commit: str) -> None:
    """Backend-specific fault setup; never used to decide repair success."""
    data = Path(os.environ["XDG_DATA_HOME"]).resolve()
    if not data.is_relative_to(root) or not re.fullmatch(r"[0-9a-f]{64}", commit):
        raise ValueError("fault injection requires isolated data and a commit checksum")
    installation = data / "flatpak"
    if operation == "remove-payload":
        result = subprocess.run(
            ["ostree", f"--repo={installation / 'repo'}", "ls", "--checksum", commit,
             "/files/bin/blackbox-probe"], check=True, text=True, capture_output=True)
        checksums = re.findall(r"\b[0-9a-f]{64}\b", result.stdout)
        if len(checksums) != 1:
            raise ValueError(f"expected one fixture payload checksum: {result.stdout}")
        checksum, = checksums
        path = installation / "repo/objects" / checksum[:2] / (checksum[2:] + ".file")
        if not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError("expected an existing payload inside isolated state")
        path.unlink()
        print(json.dumps({"removed_payload": checksum, "commit": commit}))
    elif operation == "snapshot":
        entries = []
        for path in sorted(installation.rglob("*")):
            info = path.lstat()
            content = (os.readlink(path) if path.is_symlink() else
                       hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "")
            entries.append((str(path.relative_to(installation)), stat.S_IMODE(info.st_mode),
                            stat.S_IFMT(info.st_mode), info.st_uid, info.st_gid, content))
        digest = hashlib.sha256(json.dumps(entries).encode()).hexdigest()
        print(json.dumps({"entries": len(entries), "sha256": digest}))
    else:
        raise ValueError(f"unknown repair fixture operation: {operation}")


root = Path(sys.argv[1]).resolve()
if len(sys.argv) == 4:
    repair_fixture(root, sys.argv[2], sys.argv[3])
    raise SystemExit(0)
paths = {
    "FLATPAK_SYSTEM_DIR": "system",
    "FLATPAK_SYSTEM_CACHE_DIR": "system-cache",
    "FLATPAK_CONFIG_DIR": "config",
    "FLATPAK_DATA_DIR": "data",
    "FLATPAK_RUN_DIR": "run",
}
for directory in paths.values():
    (root / directory).mkdir(mode=0o700)
print(json.dumps({**{key: str(root / value) for key, value in paths.items()},
                  "BLACKBOX_REPAIR_FIXTURE": str(Path(__file__).resolve()),
                  "BLACKBOX_PREINSTALL_DIR": str(root / "config/preinstall.d")}))
