# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reference Flatpak setup adapter: print isolated target environment as JSON."""

import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
paths = {
    "FLATPAK_SYSTEM_DIR": "system",
    "FLATPAK_SYSTEM_CACHE_DIR": "system-cache",
    "FLATPAK_CONFIG_DIR": "config",
    "FLATPAK_DATA_DIR": "data",
    "FLATPAK_RUN_DIR": "run",
}
for directory in paths.values():
    (root / directory).mkdir(mode=0o700)
print(json.dumps({key: str(root / value) for key, value in paths.items()}))
