# Black-box compatibility tests

This standalone suite tests a selected CLI and source-compatible libflatpak
implementation through public interfaces. It covers installation lifecycles,
remote configuration, sandbox observations, build/distribution output, library
objects, transactions, cancellation, signals, and isolated system selectors.
The current full run contains 326 driver/profile cases, with 308 passing,
17 failing checks and one unmet prerequisite against reference Flatpak 1.19.1.

For measured percentages, denominators, and known reference discrepancies, read
[`COVERAGE.md`](COVERAGE.md). Each execution now writes `coverage.md` and embeds
the accounting in `report.json`.

JSON inputs are validated before use. Target configurations, fixture manifests,
execution reports, and coverage catalogues have concrete Python types, with
diagnostics that identify malformed fields. The loader rejects duplicate keys,
non-finite numbers, and booleans where integers are required. Target and fixture
schemas reject unknown fields; report and catalogue schemas retain extra JSON
metadata without giving it coverage meaning. Captured command output may contain
NUL characters, but subprocess arguments and environment strings may not.

## Requirements

Execution requires Linux, Python 3.10 or later, `dbus-daemon`, a working target
installation, and support for running its sandboxed apps as the current user.
The library driver also needs a C compiler, `pkg-config`, `ldd`, and the target's
public development headers and libraries. Python uses only the standard library.
Build/distribution and richer query cases also use `ostree`, GPG tools, and public
distribution formats as independent input builders or result inspectors. Selected
bus/desktop cases need tools such as `gdbus`, `dbus-send`, and a document portal.

Fixture preparation additionally needs reference `flatpak`, `ostree`, `ldconfig`,
GPG tools, and a native C compiler. It bundles the host's libc and loader into a
small runtime. Prepare fixtures for each tested architecture on a host compatible
with the execution host's kernel. Fixture preparation is independent of the
target implementation.

Run as an ordinary user. System selector cases use two disposable bubblewrap
user/mount namespace layers, with the host filesystem read-only and installation
state private to the case. They need working unprivileged and nested namespaces.
They do not cover non-root system-helper authorization, polkit, or multiple-user
access. Those contracts retain their coverage gaps.

## Prepare fixtures

From this directory:

```sh
python3 prepare.py /tmp/blackbox-fixtures --flatpak /usr/bin/flatpak
```

The output directory must not already exist. Preparation builds two snapshots,
`A/` and `B/`, with a runtime and an app that prints its version. `fixture.json`
records refs, commits, architecture, reference tool versions, and file checksums.
The runner verifies those checksums before executing tests.

Default preparation also creates independent query/bundle/extension fixtures,
transaction failure and EOL inputs, token-gated authentication repositories,
OCI and alternate-architecture repositories, lifecycle inputs, and disposable
test signing keys. `--basic` omits supplemental workflow fixtures
and is suitable only for cases that do not require them. The runtime and app
include a small probe for file access, environment, arguments, and synchronization.

Query fixture preparation also exports distinct A/B AppStream description keywords
and a separate selection repository. Its two apps use different runtimes, and a
locale-subset extension carries independently recognizable language files. The
optional `queries.selection_repo` and `queries.selection_commits` fields retain
schema-1 compatibility with older manifests. When provided, the commit map must
contain all four selection refs for the manifest's architecture; incomplete maps
are rejected before target execution. Regenerate fixtures to run the new
search/update, runtime-filter and config-unset cases with these inputs.

The transaction subpath cases also require the query fixture's
`files/subset-control/payload`. This independent full-install marker is outside
the reserved `files/extra` directory. Regenerate with the full `prepare.py`
command when using fixtures prepared before this marker was added.
Only `tx-update-subpaths-default` and `tx-disable-related` require the selection
repository and its commit map. The other transaction-contract cases accept query
fixtures without those optional fields.

The six SDK/debug, operation-cause, migration, dependency-query and remote-trust
cases are registered in `scenario-data/six-contracts.json`. Full preparation adds
the optional, validated `contracts` manifest group. It contains two runnable apps,
a shared runtime, a distinct SDK, app/runtime/SDK debug refs, and shared extensions.
Separate repository snapshots change only the runtime, a shared app extension, or
the migration target app. Every snapshot records all expected commits. Older
manifests remain valid, but the four cases requiring this group report an unmet
prerequisite. The two remote cases reuse `build.usb_repo` and its disposable key.

Distribute the whole fixture directory with the suite. Execution needs no reference
Flatpak exporter, source tree, Meson build, or public network repository. Some
groups use OSTree to create independent copies of prepared inputs or inspect
target-created public distribution artifacts. Failed preparation leaves an
incomplete directory without a valid
manifest; use a new output directory when retrying.

## Configure a target

Copy `target.example.json` and edit it for the target. Paths to executables and
library directories should be absolute. Adapter arguments are resolved with the
target configuration's directory as the working directory.

- `name` identifies the target in results.
- `cli` selects its executable.
- `adapter` is an argument array for environment setup, not a shell command.
- `environment` supplies explicit target settings to CLI commands and clients.
- `unsupported_capabilities` optionally maps unsupported requirements to reasons,
  for example `{"sandbox-execution": "Not implemented yet"}`. The behavior
  catalogues declare capability names such as `cli`, `libflatpak`,
  `user-installation`, `local-repository`, and `sandbox-execution`, including
  prerequisites of obligations that do not yet have tests. Mapped obligation
  prerequisites are combined with scenario prerequisites. Affected scenarios
  report `unsupported` and make
  the run unsuccessful. Omitting a declaration means the suite attempts the
  behavior; it does not infer lack of support from arbitrary command failures.
- `library.cc`, `library.pkg_config`, and `library.package` default to `cc`,
  `pkg-config`, and `flatpak`.
- `library.environment` sets build-tool environment variables such as
  `PKG_CONFIG_PATH` or `PKG_CONFIG_LIBDIR` for the selected development package.
- `library.runtime_library_dirs` must list existing absolute directories. The
  runner sets `LD_LIBRARY_PATH` and uses `ldd` to verify that the client resolves
  the target library there, rejecting fallback to a different host installation.
- `library.soname` defaults to `libflatpak.so.0`. Set it if the source-compatible
  replacement uses a different shared-library name. ABI compatibility is not
  required.

The example uses `/usr/lib64`; distributions with multiarch directories should
use their library directory, such as `/usr/lib/x86_64-linux-gnu`.

For system selector cases, set `BLACKBOX_SYSTEM_INSTALL_DIR` and
`BLACKBOX_SYSTEM_CONFIG_DIR` in `environment` to the target's actual compiled
default locations. These are test expectations, not Flatpak directory redirects.
The example uses `/var/lib/flatpak` and `/etc/flatpak`. The reference development
build uses `/var/local/lib/flatpak` and `/usr/local/etc/flatpak`. A mismatched
expectation must fail rather than redirect the target to the expected path.
Additional target resources can be exposed read-only with the colon-separated
`BLACKBOX_TARGET_READONLY_PATHS` setting. The namespace backend rejects paths that
would obscure its private installations or writable mounts. It does not infer a
source-checkout root from the suite's directory depth.

For an existing Meson development build, its `meson-uninstalled` directory can
provide `PKG_CONFIG_PATH`, with `common/` as the runtime library directory.
Configure the matching CLI and any build-specific helper paths in `environment`.
That is a target configuration choice; the suite itself does not locate or use
build-tree internals.

### Setup adapter contract

The runner appends a fresh state directory to the adapter command. It supplies
isolated home and XDG directories, `LC_ALL=C`, `TZ=UTC`, `TERM=dumb`, and
`GIO_USE_VFS=local`. It does not inherit the host's session bus, proxy variables,
or Flatpak-specific environment. `PATH` is inherited for dependency discovery.

The adapter prints a JSON object of environment-variable strings to stdout.
Diagnostics go to stderr. Exit 77 means an unmet prerequisite; other nonzero
statuses mean setup failed. The adapter must keep setup inside the supplied
state directory and must not perform operations under test or transform their
results. It must not leave background services running.

`flatpak-adapter.py` redirects reference Flatpak's system/configuration directories
to empty per-test directories. A replacement can provide another adapter. The
runner starts and stops a private session bus after setup. Only service files
provided by the adapter in `STATE_DIRECTORY/services/` are available for bus
activation. Host desktop services are not auto-activated. Tests currently cover
local repository transport and app execution; desktop session integration is an
outstanding inventory item.

## Run scenarios

```sh
python3 run.py \
  --target target.example.json \
  --fixtures /tmp/blackbox-fixtures \
  --output /tmp/blackbox-results
```

Use a new output directory for each run. To iterate on one boundary or scenario:

```sh
python3 run.py \
  --target target.example.json \
  --fixtures /tmp/blackbox-fixtures \
  --output /tmp/blackbox-cli-lifecycle \
  --driver cli --scenario lifecycle
```

`--driver` accepts `cli`, `library`, or `all`. `--scenario` accepts `all` or a
registered scenario name. Names come from `inventory.json` and `scenario-data/*.json`;
`python3 run.py --help` lists the complete selection. The original cases include:
`--timeout` sets a positive per-command limit in seconds, defaulting to 120.
Timeouts fail the test and retain command output.

| Scenario | Required behavior |
| --- | --- |
| `lifecycle` | Install A and its runtime, query and run A, update to B, query and run B, then uninstall and verify absence. |
| `failed-update` | Fail a required update download and verify that A and its runtime remain installed and A is runnable. |
| `noop-update` | Update while the remote still advertises A; the operation succeeds without changing the app or runtime commits. |
| `repeated-install` | Install A again while B is available. The CLI succeeds with an already-installed warning; libflatpak returns `ALREADY_INSTALLED`. Neither upgrades the app. |
| `missing-install` | Install a well-formed ref absent from the remote. The CLI fails with a missing-ref diagnostic; libflatpak returns `REF_NOT_FOUND`. Public enumeration must show an empty installation afterward. |
| `absent-ref` | Query and uninstall an absent ref alongside installed A. Both operations fail with absent-ref diagnostics or the public `NOT_INSTALLED` error, preserving A and its runtime after each operation. |
| `retry-update` | Fail an update download, verify A remains runnable, restore downloads, and retry. The retry must download and install B while preserving the runtime. |
| `remote-config` | Add, enumerate, modify, and delete remotes through separate processes; verify exact URL/title/priority properties, priority changes, and preservation of another remote. |
| `remote-priority-order` | Library only: enforce descending priority and the documented insertion-order rule for fresh equal-priority remotes. This currently exposes a reference implementation/documentation discrepancy. |
| `ready-abort` | Library only: reject a transaction in the public ready callback, verify no operations execute or refs appear, then accept a fresh transaction and verify installation. |
| `coverage-search` | Match an AppStream description keyword to the exact app and branches, excluding B-only and nonexistent terms. |
| `coverage-appstream-update` | Serve B at the same remote URL, verify cached A remains searchable, refresh that remote explicitly, then find B and exclude A. |
| `coverage-bundle` | Copy an independently exported bundle to an extensionless filename. Without `--bundle`, installation fails without deployment; with it, query the exact app commit, retained runtime, and absent companion app. |
| `coverage-runtime-filter` | Install apps using two different runtimes; each runtime filter selects only its app, and a missing runtime selects none. |
| `coverage-config-unset` | Observe locale-extension files before and after unsetting languages: explicit ja changes to extra-language de plus current language fr, excluding unrelated es. |
| `coverage-progress-context` | Library only: refresh AppStream over delayed HTTP and check callback user data, caller thread, selected-context ownership, display status, bounded percentage, and call scope. Record estimating and final progress without prescribing values. |
| `tx-install-subpaths` | Native transaction installs with explicit `/bin`, NULL, and an empty array; public deployment locations expose the requested subset or full payloads. |
| `tx-update-subpaths-all` | Two fresh partial installations each become full with an empty array or an array containing only the empty string. |
| `tx-update-subpaths-default` | NULL updates preserve ja, add configured fr and then de, and keep unrequested es absent. |
| `tx-disable-related` | Disabled related refs exclude the suggested locale from operations and installed refs; an enabled control includes it. |
| `tx-extra-dependency-source` | A public custom-path source supplies the installed runtime without duplication; an unregistered-source control installs a target copy. |
| `tx-file-uri-origin` | Native transaction installation from a file URI creates a publicly queryable origin remote with that URL. |
| `tx-operation-identity` | Install, update, uninstall and bundle operations expose their ref, type, applicable remote and nullable bundle path; execution callbacks verify current-operation identity. |
| `tx-auto-sdk-debug` | All SDK/debug flag combinations have exact deployment controls; update adds the SDK and debug refs; uninstall-only adds none. Native getters check the settings. |
| `tx-operation-causes` | A shared runtime identifies both requesting apps, extensions identify their main operations, explicit apps have no causes, and unchanged app causes report skipped during a runtime update. |
| `tx-rebase-migration` | The old app writes persistent data. Rebase with nonempty previous IDs must expose it through the new app's own data path, for new, unchanged-installed and updated targets. An ordinary install must not migrate it. |
| `query-missing-dependencies` | Both apps must appear in update enumeration for a missing runtime, missing related extension, shared runtime update and shared extension update; complete/repaired installations have no updates. |
| `remote-branch-collection` | Install from a valid signed collection remote and verify persistence after reopening. Before each clear, populate both properties; single-setter NULL clears must preserve the untouched property after reopening. Also check clearing both. |
| `remote-trusted-key` | A committed trusted key permits exact signed deployments. Missing-key and unsigned controls fail with no deployments; resolution or execution failure is accepted. |

Additional groups cover CLI management, build/export and signing, runtime
permissions and process behavior, library objects and queries, transactions and
authentication, permission-store workflows, private-journal history, preinstalled
applications, global options, and isolated system selectors. Their manifests contain
each case's precise preconditions and expected outcome.

Lifecycle state checks compare exact prepared commits and, where applicable,
runnable probe output. `missing-install` does not require sandbox execution
because it verifies that nothing was installed.

The library clients compile with `-Wall -Wextra -Werror` on each library run.
Both drivers use the same state assertions, with interface-specific error
expectations. The original library lifecycle cases use the CLI as a launch
observer. The `queryx-launch*` cases exercise public library launch APIs directly.

Each scenario gets fresh state, a private session bus, and a loopback HTTP server.
State directories use short paths to accommodate Unix socket path limits and
are removed after the case. Commands run in their own process groups, which the
runner terminates after completion or timeout. Bus logs and command evidence
remain in the output directory. If state cleanup fails, the report identifies
the remaining path and marks the case as a setup error.

The current measured run is
`_build/blackbox-artifacts/six-contract-reviewed-full-01/report.json`, using
`_build/blackbox-artifacts/six-contract-fixtures-04`. Its definition fingerprint is
`8df05943e73a0e8ee666cffe87e091142dfcca13d3fbb0a3bffaa48d48223779`.
All seven earlier transaction-contract cases and four of the six new cases pass.
The new failures are unchanged-commit rebase migration and affected-app update
enumeration for shared dependency updates. The existing nullable-rebase failure
and explicitly keyed bundle crash are separate checks. Fifteen previous failures
reproduce; document forwarding is now blocked by private portal startup rather
than reaching its previous failing assertion. `COVERAGE.md` records details,
target and fixture hashes.

For long runs on a quota-limited `/tmp`, select a short writable `TMPDIR` on a
filesystem with sufficient space and put `--output` there too. Keep the temporary
path short enough for Unix-domain sockets. An interrupted or quota-failed report
cannot provide verified coverage.

The failed-update scenario advertises B, then returns HTTP 503 for required
payload object downloads. It requires evidence of a blocked download, an update
failure, the original installed commit, and a runnable app still reporting A.
An unrelated failure before reaching the injected fault cannot pass this test.
The fixture server understands the prepared OSTree repository format; assertions
do not inspect the target's private storage.

`retry-update` repeats this failure setup in its own fresh installation. It then
removes the server-side fault and runs a new update operation. The result includes
evidence that a payload download was attempted after the fault was removed.

## Read results

`report.json` contains target and fixture provenance, compiler and runtime-linker
evidence, behavior IDs, driver/profile, command arguments, stdout, stderr, exit
status, and repository requests. Library errors and transaction signal events
are recorded in the client's stderr. Transaction cases assert operation ordering,
progress, cancellation, remote choices, and EOL/rebase decisions. Function and
signal reach require both a passing assertion mapping and observed call/emission
markers; merely logging an event earns no credit.

The C client's exit statuses 3, 4, and 5 identify public `NOT_INSTALLED`,
`ALREADY_INSTALLED`, and `REF_NOT_FOUND` errors, respectively. It uses
`g_error_matches()` with the target's public error domain and enum constants.
These are test-client protocol statuses, not assumed numeric values of Flatpak's
error enum or CLI exit statuses. Other library errors return status 1. Missing-ref
CLI failure assertions require a positive exit status and a diagnostic identifying
both the requested app and the error condition; exact full messages are not
compared.

Case statuses are `passed`, `failed`, `unmet-prerequisite`, `unsupported`,
`setup-error`, or `not-selected`. Preflight failures retain the affected behavior
IDs with the corresponding status. `gaps` summarizes incomplete areas; coverage
accounting lists exact unimplemented requirements and credited case evidence.
Failures, unsupported required capabilities, missing prerequisites, or
setup errors return exit status 1. Exit status 0 means the
selected implemented scenarios passed. It does not mean the inventory is fully
covered: `full_compatibility` is currently always false, and filtered-out cases
remain visible as `not-selected`.

Reports include timestamps, target configuration/executable/library hashes, and
suite/catalogue definition hashes. JSON writes are atomic. A report is eligible
for current coverage credit only after the run completes, all declared cases
are accounted for, and passing cases have confirmed cleanup. Old reports without
definition hashes, interrupted runs, and reports from changed definitions remain
unverified. Historical reports still describe their recorded target; they do not
certify a subsequently changed executable or a different environment.

## Extend and check the suite

Add cases to a `scenario-data/GROUP.json` file. Each file has schema 1,
`behaviors`, and `mappings`. A behavior names its root Python module and function
with `handler: "module:run"`; the function receives driver, repository server,
URL, fixture metadata, and scenario name. Optional `client` metadata names a C
source and a `blackbox_GROUP_main` entry point returning -1 for unhandled commands.
The shared header provides `CALL_API` and `TRACE_SIGNAL` instrumentation.

Map only fully asserted existing requirement IDs. Option-only cases can declare
`surface_assertions`, each naming an existing CLI-option ID and the specific
observed effect. They do not create behavior obligations or command coverage.
An ignored flag should cause the corresponding test to fail. Keep the fixed
denominators independent of how many tests have been implemented.

New assertions must use public interfaces, public distribution artifacts, or
observations from the fixture app. Preparation helpers run reference exporters
before testing; expected values must not come from the target API under test.

Python functions have type annotations. Dynamic target and fixture JSON still
uses `Any` in places, so passing a type checker does not establish complete type
safety for those inputs. The runtime uses the standard library; development tools
are pinned in the suite-local `pyproject.toml` and `uv.lock`.

From `tests/blackbox`, install and run the reproducible development checks:

```sh
uv sync --locked
uv run --locked ty check .
uv run --locked mypy
uv run --locked ruff check .
uv run --locked python -m unittest discover -p 'test_*.py'
```

ty checks Python 3.10 compatibility; strict mypy remains a complementary check
for annotation discipline. Ruff enforces the repository's 100-column limit,
imports, unused code, and the configured correctness/style rules. `uv run` uses
the same locked tool versions on each developer machine; avoid ad-hoc upgrades
through unpinned `uv tool run` when checking this suite.

Run individual scenarios while changing them, then run the unfiltered command
above once all changes are ready. The standalone suite is intentionally separate
from Meson's internal tests; it requires prepared fixtures and an explicit target.
