#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Run each phase from the suite root. Provisioning uses sudo on disposable CI only.
set -euo pipefail

: "${BB_CI_ROOT:?Set BB_CI_ROOT to a new absolute work directory}"
phase=${1:?Usage: bash ci/compatibility.sh init|host|checkout|build|probe|prepare|system|run|cleanup|summary}
if [[ "$phase" = summary ]]; then
    # This must also work when init, dependencies, or the runner failed early.
    # Actions assigns a different summary path to each step; use the delivery marker.
    if [[ ! -s "$BB_CI_ROOT/results/job-summary.md" ]]; then
        printf '\n\n## Flatpak compatibility\n\n**INCOMPLETE**\n\nNo completed report summary is available. See the job logs and uploaded artifacts. Coverage and timings are unverified.\n' \
            >> "${GITHUB_STEP_SUMMARY:?Actions summary path is required}"
    fi
    exit 0
fi
: "${TMPDIR:?Set TMPDIR to a short absolute temporary directory}"
if [[ "$phase" != init && "$phase" != host && "$phase" != checkout ]]; then
    : "${FLATPAK_REFERENCE_COMMIT:?Set the resolved upstream commit}"
    [[ "$FLATPAK_REFERENCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]
fi
[[ "$BB_CI_ROOT" = /* && "$TMPDIR" = /* ]]
[[ $EUID -ne 0 ]] || { printf 'Run this script as an ordinary user.\n' >&2; exit 1; }

suite=$(pwd -P)
source_dir="$BB_CI_ROOT/source"
build_dir="$BB_CI_ROOT/build"

if [[ "$phase" = init ]]; then
    umask 022
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
        libpolkit-agent-1-dev libpolkit-gobject-1-dev polkitd \
        libseccomp-dev libsystemd-dev libxau-dev libxml2-dev libzstd-dev \
        bubblewrap dbus dbus-daemon dbus-bin dbus-tests fuse3 gnupg ostree strace \
        desktop-file-utils shared-mime-info xdg-dbus-proxy xdg-desktop-portal \
        xauth attr systemd
    dpkg-query -W > "$BB_CI_ROOT/logs/packages.txt"
}

checkout() {
    : "${FLATPAK_BASELINE_REF:?Select a full tag or branch ref}"
    git check-ref-format "$FLATPAK_BASELINE_REF"
    case "$FLATPAK_BASELINE_REF" in
        refs/tags/*)
            [[ "${FLATPAK_REFERENCE_COMMIT:-}" =~ ^[0-9a-f]{40}$ ]] || {
                printf 'Tag baselines require an expected commit.\n' >&2; return 1;
            } ;;
        refs/heads/*) ;;
        *) printf 'Select refs/tags/... or refs/heads/...\n' >&2; return 1 ;;
    esac
    git init "$source_dir"
    git -C "$source_dir" remote add origin https://github.com/flatpak/flatpak.git
    git -C "$source_dir" fetch --depth=1 origin "$FLATPAK_BASELINE_REF"
    local commit
    commit=$(git -C "$source_dir" rev-parse --verify 'FETCH_HEAD^{commit}')
    if [[ "$FLATPAK_BASELINE_REF" == refs/tags/* && "$commit" != "$FLATPAK_REFERENCE_COMMIT" ]]; then
        printf 'Tag %s resolves to %s; expected %s\n' \
            "$FLATPAK_BASELINE_REF" "$commit" "$FLATPAK_REFERENCE_COMMIT" >&2
        return 1
    fi
    git -C "$source_dir" checkout --detach "$commit"
    printf '%s\n' "$commit" > "$BB_CI_ROOT/logs/reference-commit.txt"
    printf '%s\n' "$FLATPAK_BASELINE_REF" > "$BB_CI_ROOT/logs/reference-ref.txt"
    if [[ -n "${GITHUB_ENV:-}" ]]; then
        printf 'FLATPAK_REFERENCE_COMMIT=%s\n' "$commit" >> "$GITHUB_ENV"
    fi
}

build() {
    [[ $(git -C "$source_dir" rev-parse HEAD) = "$FLATPAK_REFERENCE_COMMIT" ]]
    # Meson fetches subprojects at the revisions in this commit's wrap files.
    # Use the bundled bubblewrap required by the selected Flatpak source.
    # Absolute system paths make the selector expectations below unambiguous.
    meson setup "$build_dir" "$source_dir" \
        --prefix="$BB_CI_ROOT/prefix" --sysconfdir=/etc --localstatedir=/var \
        -Dsystem_install_dir=/var/lib/flatpak \
        -Dsystem_dbus_proxy=/usr/bin/xdg-dbus-proxy \
        -Dtests=false -Dgir=disabled -Dgtkdoc=disabled -Dman=disabled \
        -Ddocbook_docs=disabled -Dselinux_module=disabled \
        -Dsystem_helper=enabled -Dmalcontent=disabled \
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
    "name": "Flatpak reference " + os.environ["FLATPAK_REFERENCE_COMMIT"],
    "cli": str(build / "app/flatpak"),
    "adapter": ["python3", str(suite / "flatpak-adapter.py")],
    "environment": {
        **{key: os.environ[key] for key in helpers},
        "LD_LIBRARY_PATH": str(build / "common"),
        "BLACKBOX_SYSTEM_INSTALL_DIR": "/var/lib/flatpak",
        "BLACKBOX_SYSTEM_CONFIG_DIR": "/etc/flatpak",
        "BLACKBOX_SYSTEM_TEST_ROOT": str(root),
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
    # Inherit GITHUB_STEP_SUMMARY for the parent runner's report-based summary.
    # Case environments are sanitized and never receive that output path.
    uv run --locked python run.py --target "$BB_CI_ROOT/target.json" \
        --fixtures "$BB_CI_ROOT/fixtures" --output "$BB_CI_ROOT/results" --timeout 90 \
        --color always "$@"
}

system() {
    [[ "${GITHUB_ACTIONS:-}" = true && "${RUNNER_ENVIRONMENT:-}" = github-hosted ]]
    sudo env GITHUB_ACTIONS=true RUNNER_ENVIRONMENT=github-hosted \
        python3 ci/system_helper.py start "$BB_CI_ROOT"
    sudo env GITHUB_ACTIONS=true RUNNER_ENVIRONMENT=github-hosted \
        python3 ci/system_helper.py probe "$BB_CI_ROOT"
}

cleanup() {
    [[ "${GITHUB_ACTIONS:-}" = true && "${RUNNER_ENVIRONMENT:-}" = github-hosted ]]
    sudo env GITHUB_ACTIONS=true RUNNER_ENVIRONMENT=github-hosted \
        python3 ci/system_helper.py stop "$BB_CI_ROOT"
}

case "$phase" in
    host|checkout|build|probe|prepare|system|run|cleanup)
        # pipefail preserves runner/setup failures; the runner classifies the
        # narrow CI exception for completed scenario assertion failures.
        "$phase" "${@:2}" 2>&1 | tee "$BB_CI_ROOT/logs/$phase.log"
        ;;
    *) printf 'Unknown phase: %s\n' "$phase" >&2; exit 2 ;;
esac
