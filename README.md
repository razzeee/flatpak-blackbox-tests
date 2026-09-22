# Flatpak black-box tests

Compatibility tests for the Flatpak CLI and source-compatible libflatpak
implementations, using public interfaces and independently prepared fixtures.
See [COVERAGE.md](COVERAGE.md) for coverage measurements and known failures.

## Daily coverage charts

Default-branch CI publishes daily coverage to GitHub Pages, with separate pinned
and upstream-main views. It keeps the latest complete run for each UTC day. Missing
or unverified runs create gaps. Run and case timings include outcomes and separate
setup, execution, and cleanup times. Snapshots persist on `coverage-history`.
Select a run to filter its case outcomes or compare slow cases with an earlier run.
Case rows open timing histories. Shared and unrecorded time is listed separately.

The TypeScript/React site uses TanStack Charts. For local development with Node 22.12+:

```sh
npm --prefix web ci
npm --prefix web run dev
```

Copy published `history.json` to `web/public/history.json` to preview real data.

Select the Failed or Setup error count, then select a case to see its failure
message and expandable command output, exit statuses, API calls and observations.
Diagnostics retain the last 12 evidence records, prioritizing the most recent
commands, with a 4,000-character field limit and a 24,000-character budget per
case. Truncated output is labelled; the CI link leads to the full report artifacts
while they remain available. Older snapshots without diagnostics say so.

The active baseline is configured in `ci/baselines.json`. Add a release tag and
its peeled commit, then update `current` when upgrading; retain older definitions
for historical labels. The separate upstream track follows the `main` branch.
Manual runs accept a configured tag version or its exact resolved commit. Compare
old and new baselines using the same suite revision; their daily coverage and
timings stay separate.

CI fetches the selected full Git ref once and resolves it to a commit before
building. Tags must peel to their configured commit (annotated and lightweight
tags are supported); branches resolve to their current head. Reports record the
exact checked-out commit. Archived snapshots remain readable after their baseline
is removed from the active configuration.

## Requirements

- Linux, Python 3.10+, D-Bus, and working unprivileged user/mount namespaces.
- A reference Flatpak, OSTree, GPG, `ldconfig`, and a C compiler to prepare fixtures.
  Full fixture preparation also needs `pkg-config` and GIO development files for
  the independently packaged authenticator service.
- The target's public development headers and libraries, `pkg-config`, and `ldd`
  for library tests.
- Desktop services and tools, including a document portal, for the relevant cases.

Run as an ordinary user. Python execution uses only the standard library.
The [CI setup script](ci/compatibility.sh) lists the full Ubuntu dependencies.

## Prepare fixtures

Run these commands from the repository root:

```sh
python3 prepare.py /tmp/blackbox-fixtures --flatpak /usr/bin/flatpak
```

Use a new directory. Preparation creates versioned repositories, apps, runtimes,
and supplemental inputs with a checksummed `fixture.json` manifest. Fixtures are
architecture-specific and can be reused across target runs. `--basic` prepares
only the inputs needed by the basic cases.

Contract preparation verifies marker bytes in the exported OSTree commits.
SDK/base-extension copying cases require these payload-bearing fixtures and
report an unmet prerequisite for older fixtures with empty extensions.

## Configure a target

Copy [target.example.json](target.example.json) and edit it for your installation:

- `cli`: absolute path to the target executable.
- `adapter`: setup command; `flatpak-adapter.py` supports reference Flatpak.
- `environment`: target-specific settings and helper paths.
- `library.environment`: build settings such as `PKG_CONFIG_PATH`.
- `library.runtime_library_dirs`: absolute directories containing the target
  library, such as `/usr/lib64` or `/usr/lib/x86_64-linux-gnu`.

For system-selector cases, set `BLACKBOX_SYSTEM_INSTALL_DIR` and
`BLACKBOX_SYSTEM_CONFIG_DIR` to the target's compiled defaults. These are expected
locations, not directory redirects.

Custom adapters receive a fresh state directory and print a JSON object of
environment variables. Keep setup inside that directory; send diagnostics to
stderr. Exit 77 reports an unmet prerequisite.

Vendor-definition option cases use `BLACKBOX_PREINSTALL_DIR` to locate the public
`.preinstall` configuration directory. Adapters must point it inside the case's
fresh state. The reference adapter maps it to its isolated `preinstall.d`.
Ordinary runner commands receive EOF on stdin, so confirmation tests cannot
accidentally consume input supplied to the runner.

Repair scenarios also use the adapter's `BLACKBOX_REPAIR_FIXTURE` Python helper.
The runner invokes it with `STATE_DIRECTORY OPERATION APP_COMMIT`. The reference
adapter implements `remove-payload` by removing the fixture executable's OSTree
object, and `snapshot` by returning a deterministic digest of installation paths,
file types, ownership, modes, symlink targets and file contents. These operations
are setup evidence. Public offline redeployment and app execution establish repair
success. An adapter without the helper reports an unmet prerequisite for these cases.

## Run tests

```sh
python3 run.py \
  --target target.json \
  --fixtures /tmp/blackbox-fixtures \
  --output /tmp/blackbox-results
```

Use a new output directory for each run. Useful options:

- `--driver cli|library|all` selects an interface.
- `--scenario lifecycle` selects one scenario; `--help` lists all names.
- `--timeout 120` sets the per-command timeout in seconds.
- `--color auto|always|never` controls console color; `auto` uses color on a TTY.
  CI uses `always` for piped logs. A nonempty `NO_COLOR` disables color in every mode.
  Progress is flushed after each case and uses the timings saved in JSON.

Each case gets isolated state and a private session bus. If `/tmp` is too small,
set `TMPDIR` to a short path on a filesystem with enough space.

## Results

The output directory contains `report.json` with command evidence and provenance,
and `coverage.md` with the coverage summary. Failed checks, missing prerequisites,
unsupported capabilities, and setup errors make the run unsuccessful.

Console output and the GitHub Actions job summary show passing coverage and the
ten slowest executed cases. Unverified coverage receives no passing credit.
Reports store optional `duration_seconds` and per-case `timings` with
`setup_seconds`, `execution_seconds`, and `cleanup_seconds`. Setup includes state,
adapter, bus and repository startup; cleanup includes shutdown and state deletion.
Run duration includes shared preflight, client builds and final coverage accounting,
but excludes final report/summary writes. Cases blocked by preflight have no timings.
When `GITHUB_STEP_SUMMARY` is set, the runner appends there, then saves `job-summary.md`
as its delivery marker. Write failures return failure after saving the reports.
CI adds an unverified fallback summary if delivery failed or the runner never ran.
Without the environment variable, no extra summary file is created.

Library client compilation failures are setup errors, not failed behavior checks.
The runner probes optional public APIs against the target's headers and link library
and records the results in `library_provenance.api_features`. Cases requiring an
unavailable API report `unsupported`; unrelated cases still run. Unsupported cases
receive no passing credit and do not reduce coverage denominators.

A passing run covers only its selected, implemented cases. It does not establish
full Flatpak compatibility. Coverage reports are tied to the suite definitions;
changing those definitions requires a new run for current evidence.

```sh
python3 coverage_report.py --report /tmp/blackbox-results/report.json
```

## Development

### Supporting API differences

Register version-dependent APIs in `library_features.py`. Each entry supplies a
typed function-pointer declaration and the IDs of behaviors that require it. Include the
generated `blackbox-features.h` in the relevant C client and guard API-dependent
code with its `BLACKBOX_HAVE_<UPPERCASE_API_NAME>` macro. Probes use the same
compiler and flags as the client and never execute their test programs. A baseline
probe distinguishes a broken compiler/SDK setup from an unavailable API.

Use availability rather than version comparisons, so backports work. Each probe
declares `blackbox_probe` as a volatile function pointer with the signature the
test needs. This also checks signatures and keeps the linker reference under
optimization. Keep newer-API assertions in dedicated behaviors where possible, so
one missing API does not suppress older checks. Adding a feature does not add
coverage: the existing assertion mappings and recorded call traces still apply.

### Correcting historical classifications

History corrections live in `web/scripts/corrections.ts`. Both `history record`
and `history update` apply them. To migrate a saved history file independently:

```sh
npm --prefix web run history -- migrate \
  --history coverage-site/history.json --output corrected-history.json
```

Omit `--output` to replace the input atomically. Migrations are idempotent and
record their ID and changed-case count in each affected snapshot's `corrections`.
The library-client-build correction requires the recorded compilation diagnostic,
no case timings, and no case evidence. It changes `failed` to `setup-error` and
updates outcome counts. It preserves diagnostics, coverage metrics, timestamps,
suite/target commits and run URLs. Historical blocked tests remain unexecuted;
new runs must not be presented as results from the original date.

### Checks

```sh
uv sync --locked
uv run --locked ruff check .
uv run --locked ty check .
uv run --locked mypy
uv run --locked python format_json.py --check
uv run --locked python -m unittest discover -p 'test_*.py'
```

Use `python3 format_json.py --write` to format static JSON. Set
`BLACKBOX_TEST_FIXTURE` to a prepared `fixture.json` to include its optional
round-trip unit test.

[`scenario-data/`](scenario-data/) groups cases with all their mappings by primary
CLI command (`cli/`) or public libflatpak type (`library/`), with subgroups for
larger groups. Requirement indexes under [`coverage-data/`](coverage-data/) mirror
those groups. Category metadata keeps its meaning. Cross-command/type cases have
one home. Shared baseline registrations remain in `inventory.json` and
`coverage-data/mapping.json`; follow their requirement IDs to the owning command
or type. Add public assertions and map existing requirements without changing
coverage denominators. Nested JSON participates in discovery and report hashes.

Use `surface_assertions` for focused CLI-option, library-function, or library-signal
checks that do not establish a complete catalogued behavior obligation. Each entry
needs the interface ID and an assertion rationale. Library function and signal
credit also requires the matching call trace or signal emission in a passing case.
These annotations never add behavior or CLI-command credit.

Use `equivalent_options` instead when a case verifies ordinary results under a
default-equivalent or context-inapplicable option without demonstrating its
specific effect. These checks never increase the behavioral CLI-option metric.
Reports include separate `cli_option_accounting` with equivalence checks and
the deduplicated union of both kinds. Passing equivalence credit requires a
current, complete, verified passing case and a recorded CLI invocation containing
the option. Wrapped invocations record their exact `cli_argv` suffix; option-like
payload arguments cannot establish credit. Inventory accounting is not full
behavior coverage. In particular,
native-bundle or native-OSTree equivalence does not establish OCI signing behavior.

Filesystem-synchronization option cases require `strace` and permission to trace
the selected target. They compare actual `fsync`/`fdatasync` calls while separately
checking public output content and repository integrity.

To check the generated interface catalogue against a separate Flatpak checkout:

```sh
python3 catalogue.py --source-root ../flatpak --output coverage-data/surfaces.json --check
```

## CI

Every push and pull request runs lint, type and formatting checks, unit tests on
Python 3.10 and 3.14, and the full compatibility suite against a pinned reference
Flatpak build. Compatibility failures remain failures; reports and diagnostic
logs are uploaded even when a run fails.

CI builds the system helper from the same selected commit. After fixture
preparation, `ci/system_helper.py` provisions two ordinary users, a named system
installation and scoped polkit rules on the disposable GitHub-hosted VM. Its probe
checks the helper's bus-owner PID, authorized installation, exact commits visible
to both users, and rejection of the second user's remote modification. The helper
stays available during the suite; an always-run cleanup step stops it, removes the
test users and installation, and restores any previous polkit action policy.
Commands and helper output are included in the uploaded logs.

The provisioning probe earns no behavior coverage itself. Six `multiuser-*`
library scenarios use this environment through the normal runner and report:
system install, update, uninstall, remote persistence, installation no-interaction
and transaction no-interaction inheritance/override. Each case resets the named
installation, uses distinct ordinary users, verifies the library loaded by each
user, and preserves nested command records and actual API-call traces.

These cases opt into `execution_environment: provisioned-system` and require
`BLACKBOX_SYSTEM_TEST_ROOT` in the target environment. CI sets it automatically.
The helper and loaded library must belong to the selected target build; the runner
needs noninteractive sudo to switch users. Local Podman reproduction additionally
requires `BLACKBOX_SYSTEM_TEST_CONTAINER=1`; the privileged bridge checks the
container marker. Missing provisioning is an unmet prerequisite.

The runner compiles `fixture-polkit-agent.c` from the current suite using
`polkit-agent-1` development files. This separate process registers for the exact
client PID, records real authorization requests and rejects all of them. Interactive
controls must reach it; no-interaction attempts must not. Every attempt must still
fail authorization and preserve installed state. The fixture exits with its parent.
The suite definition includes the privileged Python bridge under `ci/`, so changes
to those assertions invalidate earlier coverage evidence.

Both [workflows](.github/workflows/) can also be started from GitHub's Actions tab.

At **21:00 UTC daily**, compatibility tests also run against upstream
`flatpak/flatpak`'s latest `main`. Each run resolves the branch to an exact commit
and records it in the target configuration and uploaded `logs/reference-commit.txt`.
Scheduled runs use a separate concurrency group from push and PR checks.

## License

[LGPL-2.1-or-later](COPYING).
