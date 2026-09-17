#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Run each phase from the suite root. Only "host" uses sudo.
set -euo pipefail

: "${BB_CI_ROOT:?Set BB_CI_ROOT to a new absolute work directory}"
: "${TMPDIR:?Set TMPDIR to a short absolute temporary directory}"
: "${FLATPAK_REFERENCE_COMMIT:?Set the pinned upstream commit}"
[[ "$BB_CI_ROOT" = /* && "$TMPDIR" = /* ]]
[[ "$FLATPAK_REFERENCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]
[[ $EUID -ne 0 ]] || { printf 'Run this script as an ordinary user.\n' >&2; exit 1; }

suite=$(pwd -P)
source_dir="$BB_CI_ROOT/source"
build_dir="$BB_CI_ROOT/build"
phase=${1:?Usage: bash ci/compatibility.sh init|host|build|probe|prepare|run}

if [[ "$phase" = init ]]; then
    # mkdir fails atomically on stale work rather than mixing runs or replacing it.
    mkdir "$BB_CI_ROOT"
    mkdir -p "$BB_CI_ROOT/logs" "$TMPDIR"
    exit 0
fi
[[ -d "$BB_CI_ROOT/logs" && -f "$suite/run.py" ]]

reference_environment() {
    export FLATPAK_BWRAP="$build_dir/subprojects/bubblewrap/flatpak-bwrap"
    export FLATPAK_DBUSPROXY=/usr/bin/xdg-dbus-proxy
    export FLATPAK_TRIGGERSDIR="$source_dir/triggers"
    export FLATPAK_VALIDATE_ICON="$build_dir/icon-validator/flatpak-validate-icon"
    export FLATPAK_PORTAL="$build_dir/portal/flatpak-portal"
    export LD_LIBRARY_PATH="$build_dir/common"
}

host() {
    # Ubuntu 24.04's AppArmor policy otherwise blocks unprivileged bwrap.
    # Change only the disposable GitHub-hosted VM, never a developer machine.
    [[ "${GITHUB_ACTIONS:-}" = true && "${RUNNER_ENVIRONMENT:-}" = github-hosted ]]
    sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
    sudo apt-get update
    sudo apt-get install --yes --no-install-recommends \
        build-essential git ca-certificates meson ninja-build pkg-config \
        bison gettext python3-pyparsing \
        libappstream-dev libarchive-dev libattr1-dev libcap-dev \
        libcurl4-openssl-dev libdconf-dev libfuse3-dev libgdk-pixbuf-2.0-dev \
        libglib2.0-dev libgpgme11-dev libjson-glib-dev libostree-dev \
        libseccomp-dev libsystemd-dev libxau-dev libxml2-dev libzstd-dev \
        bubblewrap dbus dbus-daemon dbus-bin fuse3 gnupg ostree \
        desktop-file-utils shared-mime-info xdg-dbus-proxy xdg-desktop-portal \
        xauth attr systemd
    dpkg-query -W > "$BB_CI_ROOT/logs/packages.txt"
}

build() {
    git init "$source_dir"
    git -C "$source_dir" remote add origin https://github.com/flatpak/flatpak.git
    git -C "$source_dir" fetch --depth=1 origin "$FLATPAK_REFERENCE_COMMIT"
    git -C "$source_dir" checkout --detach FETCH_HEAD
    [[ $(git -C "$source_dir" rev-parse HEAD) = "$FLATPAK_REFERENCE_COMMIT" ]]
    # Meson fetches libglnx, bubblewrap and variant-schema-compiler at the
    # revisions in this commit's wrap files. Ubuntu's bwrap is too old for 1.19.1.
    # Absolute system paths make the selector expectations below unambiguous.
    meson setup "$build_dir" "$source_dir" \
        --prefix="$BB_CI_ROOT/prefix" --sysconfdir=/etc --localstatedir=/var \
        -Dsystem_install_dir=/var/lib/flatpak \
        -Dsystem_dbus_proxy=/usr/bin/xdg-dbus-proxy \
        -Dtests=false -Dgir=disabled -Dgtkdoc=disabled -Dman=disabled \
        -Ddocbook_docs=disabled -Dselinux_module=disabled \
        -Dsystem_helper=disabled -Dmalcontent=disabled \
        -Dwayland_security_context=disabled
    meson compile -C "$build_dir" --jobs 2
    reference_environment
    # Explicit configuration of an uninstalled target. No host libflatpak fallback.
    uv run --locked python - "$suite" "$BB_CI_ROOT" <<'PY'
import json
import os
import sys
from pathlib import Path

suite, root = map(Path, sys.argv[1:])
build = root / "build"
helpers = ("FLATPAK_BWRAP", "FLATPAK_DBUSPROXY", "FLATPAK_TRIGGERSDIR",
           "FLATPAK_VALIDATE_ICON", "FLATPAK_PORTAL")
target = {
    "name": "Flatpak 1.19.1 reference " + os.environ["FLATPAK_REFERENCE_COMMIT"],
    "cli": str(build / "app/flatpak"),
    "adapter": ["python3", str(suite / "flatpak-adapter.py")],
    "environment": {
        **{key: os.environ[key] for key in helpers},
        "LD_LIBRARY_PATH": str(build / "common"),
        "BLACKBOX_SYSTEM_INSTALL_DIR": "/var/lib/flatpak",
        "BLACKBOX_SYSTEM_CONFIG_DIR": "/etc/flatpak",
    },
    "library": {
        "environment": {"PKG_CONFIG_PATH": str(build / "meson-uninstalled")},
        "runtime_library_dirs": [str(build / "common")],
    },
}
(root / "target.json").write_text(json.dumps(target, indent=2) + "\n")
PY
    {
        id
        uname -a
        git rev-parse HEAD
        git -C "$source_dir" rev-parse HEAD
        "$build_dir/app/flatpak" --version
        "$FLATPAK_BWRAP" --version
        bwrap --version
        xdg-dbus-proxy --version
        ostree --version
        cc --version
        meson --version
        uv --version
        uv run --locked python --version
        PKG_CONFIG_PATH="$build_dir/meson-uninstalled" pkg-config --modversion flatpak
        ldd "$build_dir/app/flatpak"
    } > "$BB_CI_ROOT/logs/tool-versions.txt" 2>&1
}

probe() {
    reference_environment
    # The selector backend uses host bwrap; Flatpak uses its newer bundled helper.
    # Match the backend's outer read-only mount and inner writable namespace.
    # Mapping root into the inner user namespace requires CAP_SETFCAP in its
    # parent namespace, as in system_selector_scenarios.Namespace.
    /usr/bin/bwrap --unshare-all --die-with-parent --new-session \
        --ro-bind / / --proc /proc --dev /dev --uid 0 --gid 0 --cap-add CAP_SETFCAP \
        /usr/bin/bwrap --unshare-all --die-with-parent --new-session \
        --bind / / --proc /proc --dev /dev --uid 0 --gid 0 \
        /usr/bin/true
    "$FLATPAK_BWRAP" --unshare-all --die-with-parent \
        --ro-bind / / --proc /proc --dev /dev /usr/bin/true
}

prepare() {
    reference_environment
    # Full preparation uses the reference's public exporters before any scenario.
    # It produces independent input artifacts, never expected target API results.
    uv run --locked python prepare.py "$BB_CI_ROOT/fixtures" \
        --flatpak "$build_dir/app/flatpak"
}

run() {
    uv run --locked python run.py --target "$BB_CI_ROOT/target.json" \
        --fixtures "$BB_CI_ROOT/fixtures" --output "$BB_CI_ROOT/results" --timeout 90
}

case "$phase" in
    host|build|probe|prepare|run)
        # pipefail keeps setup errors and failed compatibility checks fatal.
        "$phase" 2>&1 | tee "$BB_CI_ROOT/logs/$phase.log"
        ;;
    *) printf 'Unknown phase: %s\n' "$phase" >&2; exit 2 ;;
esac
