# What the coverage percentages mean

This suite reports separate measurements for catalogued behavior and public
interface reach. It does not report a percentage of all possible Flatpak behavior.
There is no finite denominator for all Flatpak behavior yet.

## Query and filter option batch

Eleven additional CLI cases pass against CI-pinned Flatpak 1.19.1, using the
existing independently prepared query repositories. The suite now has 371 cases.
Implemented CLI-option reach increases from 413/624 to **424/624, or 67.95%**.
CLI-command, library-function and library-signal reach remain fully implemented.
Behavior coverage remains 134/136 CLI obligations and 156/163 library obligations;
these focused option assertions add no behavior credit or denominator entries.

| Command | Newly asserted options |
| --- | --- |
| `remote-info` | `--cached` |
| `remote-ls` | `--cached`, `--all`, `--app-runtime`, `--show-details` |
| `list` | `--all`, `--show-details` |
| `remotes` | `--show-details` |
| `search` | `--columns` |
| `info` | `--show-size`, `--show-extensions` |

The cache cases switch the server from A to B and back. Cached queries retain
the warmed commits without making HTTP requests; ordinary queries fetch the
changed commits and refresh the next cached view. Filter cases compare exact
ref sets, including hidden locale extensions and apps using different runtimes.
Detailed output must equal the documented `--columns=all` form, differ from
ordinary output, and contain independently known identities and commits or
remote properties. Search checks selected and reordered columns, including
repeated `--columns` options. Info checks exact prepared byte counts and extension
membership before and after uninstalling the matching branch.

All thirteen negative controls fail their behavioral assertions and earn zero
passing credit. Eleven remove the option under test. Two additional cache
controls preserve correct cached output but make an extra HTTP request, proving
that the no-network assertions detect unwanted transfers independently of stale
commit checks.

All 122 unit tests pass with the prepared-fixture round-trip check, as do Ruff,
ty, strict mypy, JSON formatting and the source catalogue check. No existing
failure cases were investigated. These focused runs do not establish new
full-suite passing percentages.

All 24 positive/negative reports match definition fingerprint
`78ef46453b2aa6dfeda4c34981b7211b08681749f90470175566178d914f9ac9`.
Local indexes are kept outside this repository; their report paths are inside
`flatpak-blackbox-coverage-portals`, using `/tmp/target.json` and
`/tmp/fixtures-v2`. The artifacts are not published with this repository.
There are 200 CLI options and nine behavior obligations still without mappings.

## Command, function and signal reach at 100% implemented

Thirty additional cases bring the suite to 360 cases. The interface and behavior
denominators are unchanged. Current implemented coverage is:

| Measurement | Implemented | Percentage |
| --- | ---: | ---: |
| Catalogued CLI behavior | 134 / 136 | 98.53% |
| Catalogued library behavior | 156 / 163 | 95.71% |
| CLI command reach | 44 / 44 | 100.00% |
| Documented CLI option reach | 413 / 624 | 66.19% |
| Public library function reach | 223 / 223 | 100.00% |
| Public library signal reach | 14 / 14 | 100.00% |

These are implemented percentages, not full-suite passing percentages. Focused
runs on 2026-09-19 against the CI-pinned Flatpak 1.19.1 pass 28 of the 30 new
cases. Four existing cases with newly recorded standalone function assertions
also pass, as does the existing basic-authentication case with the expanded
auth fixture. Existing baseline failures were not investigated in this work.

The additions cover:

- Document export, read and write grants, revocation, unique IDs, permission
  changes, transient lifetime, enumeration, app filtering and document-info.
  Sandbox probes distinguish document grants from direct host-path access.
- Local-ref removal and pruning through controlled public repulls. With content
  blocked, repulling succeeds after ref removal and fails after pruning.
  Transaction pruning settings similarly control unrelated orphan payload.
- Downloaded versus deployed commits, remote metadata refresh, public AppStream
  timestamps, storage-query failure/recovery, transaction property round-trips,
  architecture selection, reinstall, static-delta selection and progress cadence.
- The `install-authenticator` signal's exact remote/ref, callback thread and
  refusal outcome. The prepared candidate is an installable placeholder; this
  case does not establish successful authenticator installation or resumed auth.
- Environment descriptors for build, build-finish and override, plus config-list
  output after independently changing two settings.

Standalone library assertions now use the same `surface_assertions` structure as
CLI-option assertions. They earn no behavior credit and still require matching
call-stage or signal-emission evidence from a passing library case. Five functions
receive reach credit from existing direct-bundle, deferred-trigger,
force-uninstall and remote-description assertions. The new cases establish the
remaining 19 previously unmapped functions.

Two new cases expose failures and retain their assertions:

- `documents.enumerate`: redirected output contains document IDs but omits the
  full origin paths required by the catalogue and manual.
- `documents.noexist`: exporting an absent file with `--noexist` fails with a
  GVariant response-type mismatch against the container's document portal.

All eleven negative controls fail their corresponding assertions and earn zero
passing credit. They ignore unique export, write revocation, app filtering,
unexport, transient lifetime, environment descriptors, authenticator installation
configuration, pruning, static-delta disabling, default architecture, or progress
interval changes. Controls use a CLI wrapper or a library interposer around the
reference target. The cadence control, for example, yields 64 advancing samples
in all three runs when the requested interval is ignored, so it fails the required
fast/slow/fast contrast.

All 121 unit tests pass with the new prepared-fixture round-trip check, along with
Ruff, ty, strict mypy, JSON formatting, and the source catalogue check. The focused
reports share suite definition fingerprint
`3873ecd1bf6dfc8dfe5eeb4d5af9c12bdf0ac825fc745ed03da6f8ac5236c642`.

Local evidence indexes are kept outside this repository. Their report paths are inside the
`flatpak-blackbox-coverage-portals` rootless Ubuntu 24.04 container, using
`/tmp/target.json` and `/tmp/fixtures-v2`. FUSE is available there; the container's
capability bounding set permits fusermount while the test process runs without
ambient capabilities. These artifacts are not published with the repository.

Overall implemented coverage is not yet 100%. The remaining nine behavior
obligations are two user repair contracts, two authorization contracts, four
cross-user system lifecycle/remote contracts, and successful authenticator
installation. Property round-trips and signal refusal do not satisfy their
stronger requirements. There are also 211 CLI options without assertion mappings.

## Full baseline for the 100% coverage target

A complete run on 2026-09-19 at suite revision `d058861` produced 311 passes,
18 failures and one unmet prerequisite across all 330 cases. The target was
Flatpak 1.19.1, built from CI-pinned commit
`1a6ec6a1f720fb30d76c76e656ac624fcaa237e9` in a rootless Ubuntu 24.04 Podman
container with independently prepared fixtures. A child-reaping supervisor
prevented orphaned sandbox processes from accumulating. The run took 362.49
seconds with a 90-second command timeout.

| Measurement | Implemented | Passing credit | Passing percentage |
| --- | ---: | ---: | ---: |
| Catalogued CLI behavior | 126 / 136 | 119 / 136 | 87.50% |
| Catalogued library behavior | 154 / 163 | 147 / 163 | 90.18% |
| CLI command reach | 40 / 44 | 38 / 44 | 86.36% |
| Documented CLI option reach | 397 / 624 | 389 / 624 | 62.34% |
| Public library function reach | 199 / 223 | 192 / 223 | 86.10% |
| Public library signal reach | 13 / 14 | 13 / 14 | 92.86% |

At creation, the coverage verifier accepted this report as current and complete.
The additions above make it historical evidence for its original definitions. This is a
baseline measurement, not coverage gained through new tests. Local evidence is
saved outside this repository; that artifact is not published with the repository. The container copy is
`/tmp/baseline-reaped/report.json` in `flatpak-blackbox-coverage-run`.

| Input | SHA-256 |
| --- | --- |
| Suite definition fingerprint | `8d59b70a3f439ff7e7ec6cc632ab6ceb2cd79dc2cb0c5c1e55e22c33934403b1` |
| Target configuration | `b8ec8619fa91dc3ccfe661e5fc861618aaa9ea9e22731a5be6264df545a7d758` |
| Target CLI | `09e81047c016104c7c5148488de5d319a59564a429b82e222422ae24e93e9c20` |
| Fixture manifest | `11aed4cb06f250d87c6942e6ea0274c26df6f8a1235414ef22590e93e7727f04` |

The unmapped behavior obligations are eight document-portal contracts, two user
repair contracts, two local-repository cleanup contracts, two authorization
contracts, four cross-user system lifecycle/remote contracts, and authenticator
installation. Interface reach additionally lacks 227 CLI options, 24 library
functions and the `install-authenticator` signal. These counts overlap the
behavior gaps and must not be added together.

Some existing cases exercise unmapped functions but do not prove the full
requirement. In particular, `lifex.local-ref` does not establish object retention,
and `lifex.prune` does not establish orphaned-object deletion. Their successful
execution does not justify marking those obligations covered.

The failures include build layout and execution contracts, sandbox environment
and enter behavior, named-installation overrides, ambiguous updates, remote
ordering, dependency and related-ref queries, native sideload queries, system
enumeration, instance processes, signed bundles and rebase behavior. Failure
causes still need individual diagnosis; this run alone does not attribute all
18 failures to Flatpak. The document-forwarding prerequisite fails because
`fusermount3` reports `Operation not permitted` in this container.

Reaching 100% passing coverage requires resolving those failures as well as adding
the missing assertions. The current CI build disables the system helper, so real
polkit authorization and second-user system tests also require a new provisioned
test environment. Denominators and passing-credit rules remain unchanged.

## Global driver and diagnostic options

Three additional focused cases pass against reference Flatpak 1.19.1 on
2026-09-19. The suite now has 330 cases, 126 mapped CLI obligations and 397 mapped
CLI options. All ten catalogued global-option obligations have implementations.
Denominators are unchanged; these focused runs do not establish new full-suite
passing percentages.

- `global-options-gl-drivers` checks exact driver tokens and priority order using
  two reversed `FLATPAK_GL_DRIVERS` overrides. It does not test automatic hardware
  detection.
- `global-options-verbose` compares quiet, `--verbose` and `-vv` unused-runtime
  analysis in forward and reverse order. Each level preserves stdout and the exact
  app/runtime commits. Verbosity enables diagnostics, and repeated verbosity adds
  distinct diagnostic lines without requiring particular wording or a fixed count.
- `global-options-ostree-verbose` alternates read-only commit queries with and
  without the flag. Every query reports independently prepared A with identical
  stdout; only flagged calls emit diagnostics. Both diagnostic cases disable
  inherited `G_MESSAGES_DEBUG` to keep the controls quiet.

Four negative controls deliberately ignore the GL override, remove `--verbose`,
reduce `-vv` to single verbosity, or remove `--ostree-verbose`. Each fails its
corresponding behavioral assertion and earns no passing credit. The controls use
a wrapper around the reference executable to inject each fault.

The target and fixtures are the same as the runtime-export runs below. All 119
unit tests pass with the prepared-fixture check, as do Ruff, ty, strict mypy,
JSON formatting and source catalogue checks.

## Runtime export and ambiguous update checks

Focused runs against reference Flatpak 1.19.1 on 2026-09-19 exercise two previously
unmapped CLI obligations. The suite now has 327 cases and 123 mapped CLI obligations;
the behavior and interface denominators are unchanged. Implemented CLI option reach
increases from 393 to 394. These focused results do not replace the historical full
run below or establish new full-suite passing percentages.

- `build-export-runtime` passes. The same finalized Application tree has different
  markers in `files` and `usr`, plus a file present only in `files`. Without
  `--runtime`, export creates an app ref containing the `files` payload. With it,
  export creates a runtime ref containing the `usr` payload and excludes the
  app-only file. Installation from the exported repository preserves the exact
  exported commit and payload, checked through `info --show-location`. This earns
  `cli.build-export.any.runtime` and `--runtime` coverage. The earlier case used
  Runtime metadata, which selected runtime export even without the flag.
- `management-update-ambiguous` fails the documented contract. Both `test` and
  `next` branches of `org.flatpak.Query.Data` start at independent A commits and
  advertise B updates. Fully qualified update controls reach B; explicit commit
  updates restore both to A before the ambiguous request. Updating by ID then
  returns success, prints both updates, and advances both installed branches to B.
  The manual says multiple matches produce an error listing the alternatives.
  The case retains that requirement and earns no passing credit.

The existing `build-export-contents` case also passes. Ruff, ty, strict mypy,
JSON formatting, source catalogue checks and all 119 unit tests pass, including
the prepared-fixture round-trip test.

The runs use the existing `extracted-build-target.json` and
`six-contract-fixtures-04` under the original Flatpak checkout's
`_build/blackbox-artifacts/`.
Local reports contain provenance and command evidence; they are not published
with this repository.

## Ubuntu CI portability validation

After correcting fixture `ldconfig` selection, C-locale help rendering, and D-Bus
tool dependencies and multiarch lookup, a full Ubuntu 24.04 container run against
the CI-pinned Flatpak 1.19.1 completed with 308 passes and 18 failures. The failing
case IDs and passing coverage match the checkpoint below. Its current-definition
report is `_build/blackbox-artifacts/u191v/results-multiarch-reaper/report.json` in
the original Flatpak checkout. A child-reaping supervisor handles orphaned
processes in this container; the GitHub-hosted VM has its own init process.
This is local Ubuntu validation, not a subsequent GitHub Actions run.

## Recorded surface-layout checkpoint

A complete run against reference Flatpak 1.19.1 on 2026-09-17 produced 308 passing
cases and 18 failing checks. The recorded report is
`_build/blackbox-artifacts/surface-layout-full-02/report.json`, relative to the
original Flatpak checkout root. Historical artifact paths and source commit IDs
in this document refer to that checkout, not this extracted repository. Its
passing evidence covers:

| Measurement | Passing credit | Percentage |
| --- | ---: | ---: |
| Catalogued CLI behavior | 115 / 136 obligations | 84.56% |
| Catalogued library behavior | 147 / 163 obligations | 90.18% |
| CLI command reach | 38 / 44 commands | 86.36% |
| Documented CLI option reach | 385 / 624 options | 61.70% |
| Public library function reach | 192 / 223 functions | 86.10% |
| Public library signal reach | 13 / 14 signals | 92.86% |

There are 121 mapped CLI obligations and 154 mapped library obligations; failures
do not receive passing credit. Twenty-two of the 28 explicit system obligations
have passing evidence from isolated selector, preinstall, environment, and repair
privilege checks. Polkit, non-root system-helper and multiple-user contracts
remain uncovered. This checkpoint is not a substitute for running the accounting
against the report for the target and definitions being evaluated.

The 326-case run used the uncommitted public-interface layout changes based on
`2c69bfa` on branch `refactor/readable-json`, target configuration
`/home/razze/dev/flatpak/_build/blackbox-artifacts/extracted-build-target.json`, and fixtures
at `_build/blackbox-artifacts/six-contract-fixtures-04`. It ran with `--timeout 90`
and `TMPDIR=/home/razze/dev/flatpak/_build/t`. Recorded SHA-256 values:

| Input | SHA-256 |
| --- | --- |
| Suite definition fingerprint | `3df9330148771fc58c3a1f8c735267f9acbbc86f467e8c510d25c4cd8baa8ecb` |
| Target configuration | `999164fb67f58ef7f33a2f718c4d0ba916616e99b354ed111ceac12f70683831` |
| Target CLI | `9e00add5910406853422eab296cc40ec90ba0439f5fea9564a8fba7fd09a90f2` |
| Target libflatpak | `d8ecbe648ea28869fa0e78a74b2c48b86dffd95123cb8015c530e630e70801e2` |
| Fixture manifest | `05ceae1af2272444bbc2d3fdbf142f0b9de52ed7c7854b6906bce7d0db098a61` |

The seven earlier transaction cases still pass. Four of the six additional
library contracts pass; rebase migration and missing-dependency enumeration
remain failures. All 17 failures from `six-contract-reviewed-full-01` reproduce.
Document forwarding, previously an unmet portal prerequisite, now reaches execution
and fails because the forwarded file is unavailable. Passing credit is unchanged.

Before editing, the scenario loaders and `CoverageModel` recorded
`_build/blackbox-artifacts/surface-layout-baseline.json`. Exact normalized comparison
preserves all 326 cases, 299 requirements, 320 mappings, gaps, assertion metadata,
capabilities, eight client registrations, limitations, and coverage counts.
The 74 scenario files and 72 requirement shards now follow CLI commands and public
library types. Their largest files are 463 and 474 lines respectively; the unchanged
generated interface snapshot is 12,205 lines. Locked Ruff, ty, strict mypy, formatting,
source catalogue checks, and all 89 unit tests pass with the prepared-fixture check.
Every case outcome matches `readable-json-full-01`, including its 18 failures.
The verification summary, ownership navigation, and full-run log are
`_build/blackbox-artifacts/surface-layout-{verification.json,navigation.json,full-02.log}`.
The initial `surface-layout-full-01` also matched all outcomes; the second run
refreshes evidence after correcting two ownership placements.

### Six additional library contracts

The `library/transaction/`, `library/transaction-operation.json`,
`library/installation/queries.json`, and `library/remote/` groups under
`scenario-data/` map the six existing obligations without
changing the requirement or interface denominators. Native calls and assertions
live in `client-transaction-contracts.c` and `six_contract_scenarios.py`. Public
installed-ref enumeration and independently prepared commits establish deployment
state. No assertions read private installation metadata or infer private paths.

- **Automatic SDK/debug installation.** Four independent flag combinations check
  native getters and exact resolved/deployed refs. The SDK differs from the runtime;
  app, runtime and SDK debug refs have their own commits. An update adds the SDK
  and debug refs to an initially plain installation. An uninstall-only transaction
  with both flags enabled adds no installs and leaves only the prior dependencies.
- **Operation causes.** A shared runtime names both requesting app operations.
  A runtime extension names its runtime and a shared app extension names both apps.
  Explicit app requests accept the documented NULL/empty cause equivalence.
  A runtime-only update exposes both unchanged app causes with `is_skipped` TRUE;
  they are absent from the operation list and execution callbacks.
- **Rebase migration.** The old sandbox writes and reads a marker in its actual
  `XDG_DATA_HOME`. Native rebase receives a nonempty previous-ID array. A new target
  and a changed-commit target expose that marker through their own sandbox data
  paths. An ordinary install does not. An already-installed target at the same
  commit fails to expose the marker despite successful rebase. All variants run
  before the case reports failure. This is distinct from the existing nullable
  rebase argument failure. CLI launches are data observers and earn no library
  launch coverage. No new-operation callback is required for a no-op update.
- **Missing/shared dependencies.** Apps installed without their runtime or
  should-download related refs appear in update enumeration. Fully current and
  repaired installations return no updates. However, with only a shared runtime
  or shared extension update available, the target lists the dependency alone and
  omits both affected apps, contrary to the public query documentation. Both
  update variants are checked and repaired before the case reports failure.
- **Branch/collection persistence.** A valid signed collection remote installs
  exact prepared app/runtime commits. Branch and collection getters survive
  reopening in new processes. Every clearing variant first sets both properties
  and verifies them after reopening. The `branch-clear` action calls only
  `flatpak_remote_set_default_branch()`; `collection-clear` calls only
  `flatpak_remote_set_collection_id()`. Reopened getters must report NULL for the
  cleared property and the original value for the untouched property. This avoids
  masking cross-property damage by setting the untouched property again. The
  clear-both variant also starts with both populated. Verification and deployments
  remain unchanged.
- **Trusted remote key.** Committing the prepared binary key permits installation
  from the signed remote with verification enabled. Separate missing-key and
  unsigned controls fail with GError and leave installed-ref enumeration empty.
  The test accepts failure during resolution or execution and does not require an
  operation-error signal or a particular error code. The existing explicitly keyed
  bundle crash is separate and remains unresolved.

Preparation uses `/usr/bin/flatpak` independently of the target and validates the
optional `contracts` manifest group. The final preparation log is
`_build/blackbox-artifacts/six-contract-preparation-04.log`. Pre-review focused reports are
`_build/blackbox-artifacts/six-contract-final-SCENARIO-01/report.json`, where
`SCENARIO` is `tx-auto-sdk-debug`, `tx-operation-causes`, `tx-rebase-migration`,
`query-missing-dependencies`, `remote-branch-collection` or `remote-trusted-key`.
Those pre-review reports use the earlier suite fingerprint. The reviewed
single-setter remote case passes in
`_build/blackbox-artifacts/six-contract-reviewed-remote-01/report.json`.
All six cases were rerun in the earlier reviewed full report, whose log is
`_build/blackbox-artifacts/six-contract-reviewed-full-01.log`. That report now has
historical definition hashes; the current full run above executes all six again.

At that earlier checkpoint, locked Ruff and ty checks passed; locked mypy passed
for 41 Python files. All 75 unit tests passed, including the
incomplete-contract-oracle rejection test.
Library clients compile with `-Wall -Wextra -Werror`. `catalogue.py --check` confirms
44 commands, 624 options, 223 functions and 14 signals against the current source.

### Transaction contract review

The original seven cases in `scenario-data/transaction-contracts.json` map seven existing library
obligations. Its C client calls native transaction APIs for each asserted action.
Separate public custom-path user installations isolate variants and dependency
sources. Assertions inspect public ref enumeration, commits, origins, remote URLs
and paths returned by `flatpak_installed_ref_get_deploy_dir()`. They do not infer
the installation's private directory layout.

Install subpaths cover explicit `/bin`, NULL and `{ NULL }`. All-subpaths updates
cover both `{ NULL }` and `{ "", NULL }`, each starting from a verified partial
deployment. The query fixture now has an ordinary `subset-control/payload` marker;
`files/extra` is reserved and is unsuitable as a full-deployment control. Locale
updates start with ja alone, add configured fr, then add configured de while
retaining both earlier languages. The es marker remains absent throughout.

Related-ref suppression has an enabled control. The extra dependency source has
an unregistered control that installs a second runtime; the registered source
omits that operation and target deployment while preserving the source's exact
runtime commit. This verifies dependency resolution and deployment, not runtime
discovery by a later launch in an unregistered custom-path installation.

Operation identity covers install, update, uninstall and bundle-install. Each
executing callback compares `get_current_operation()` with its operation argument.
The bundle-path getter explicitly permits NULL, including for bundle operations;
a non-NULL GFile is serialized with `g_file_get_uri()` and must equal the supplied
bundle's URI. Only an actual NULL getter result is serialized as `-`; a nonlocal
GFile cannot disappear through a NULL local-path conversion. Ordinary operations
require a NULL bundle. Operation labels come from a C switch over the public enum
constants rather than numeric enum strings. Remote expectations use the named
source or the public installed origin, without prescribing an automatically
generated origin name.

A separate negative control interposes the bundle getter during the real identity
scenario and returns `https://example.invalid/wrong-bundle.flatpak`. It confirms
that this non-NULL GFile has no local path, records the URI in the operation row,
and fails at the intended Python bundle assertion. Reproduction artifacts are
`_build/blackbox-artifacts/tx-contract-wrong-bundle-uri.c`, its compiled `.so`,
`tx-contract-wrong-bundle-target.json`, and
`tx-contract-wrong-bundle-repro-01/report.json` in the same artifact directory.
This deliberately invalid-target run is separate from the measured reference run.

## Reproduce the accounting

From this repository's root:

```sh
# Tests mapped to obligations, without claiming they have passed:
python3 coverage_report.py

# Passing evidence from a specific, completed execution:
python3 coverage_report.py --report /path/to/results/report.json

# Include individual evidence, uncovered IDs, categories, profiles and limitations:
python3 coverage_report.py --report /path/to/results/report.json --json

# In the reference source checkout, detect source/interface drift:
python3 catalogue.py --source-root ../flatpak --output coverage-data/surfaces.json --check
```

Every target run also writes `coverage.md` and embeds the same accounting in
`report.json`. Exit status 0 from `coverage_report.py` means the accounting is
valid, not that all target tests passed. The test runner still returns failure
when a required case fails or cannot run.

## Denominators

The initial reference is source commit
`74d525dcd206febbdc937b24bddb90d05bbf0c43`.

| Measurement | Denominator | What one unit means |
| --- | ---: | --- |
| CLI behavior | 136 | One selected, described CLI outcome, with its installation profile and source references |
| Library behavior | 163 | One selected, described public libflatpak outcome, with its profile and source references |
| CLI command reach | 44 | One active canonical command registered by the reference CLI |
| CLI option reach | 624 | One distinct documented long option for a particular command, or for the global invocation |
| Library function reach | 223 | One explicit public callable declaration, including deprecated APIs, excluding type-registration plumbing |
| Library signal reach | 14 | One documented and registered signal belonging to a public libflatpak type |

The 299 behavior obligations form the initial catalogue. Rows vary in scope and
are not weighted by complexity, risk, or usage. The files record
known omissions and documentation ambiguities. A behavior percentage means
coverage of those rows only; it must not be advertised as overall compatibility.

The source-generated interface denominator is independently reproducible.
`catalogue.py` records hashes for its 109 source inputs and rejects unsupported
forms within its documented parsing subset, unresolved XML, missing manuals, and
catalogue drift. It parses the public header list and signal documentation
without needing a built Flatpak. It is not a general C or Meson interpreter:
conditions, subdirectory includes and dependency-provided sources are not
evaluated, and known generated internal sources are excluded. Reassigned or
indirect header/source lists are rejected. A new build structure or generated
public API requires a parser review; hash checking alone cannot establish its
completeness.
Execution consumes the committed JSON, so a portable copy needs no source tree.
It makes no automatic claim that an unavailable source checkout is up to date.

### Counting rules and exclusions

- Deprecated command aliases such as `upgrade` and `remote-list` do not add
  canonical commands. Their exclusions are listed individually in the snapshot.
- Short aliases do not add option entries. Distinct long options stay distinct,
  even when documented together. In particular, `--filter` and `--no-filter` are
  opposing behaviors, not aliases. Repeated prose mentions do not add entries.
- `--user` counts separately where documented for different commands. This
  measures command-specific option reach, not a count of unique flag spellings.
- Option argument values, combinations, precedence, and repeated-option behavior
  require additional obligations. A single covered option is not fully tested.
- Public deprecated library functions remain counted. Explicit, macro-declared,
  and generated `get_type` plumbing is excluded consistently and individually.
- Private APIs, inherited GLib signals, standalone executables, D-Bus protocols,
  environment variables and file formats are outside these interface counts.
  Some effects of them occur in behavior obligations, but those obligations do
  not make the omitted interface categories complete.

## Numerators and evidence

`coverage-data/mapping.json` and the `mappings` entries in `scenario-data/*.json`
provide audited many-to-many mappings from cases to obligations. Each mapping
includes its assertion rationale.
Every obligation also declares coarse required capabilities, including unmapped
ones. These describe test prerequisites, not the full implementation dependency
graph. The JSON report exposes them alongside declared unsupported capabilities.
The behavior catalogue and executable scenario inventory are separate, so a large
gap such as sandbox permissions is never counted as equivalent to one scenario.

Two numerators are reported:

1. **Implemented:** unique obligations with an explicit test mapping.
2. **Passing evidence:** unique obligations whose mapped case passed in the
   supplied, complete execution, including cleanup.

Repeated assertions and multiple passing scenarios earn no duplicate credit.
A failed scenario earns no passing credit, even if some earlier assertions
succeeded. This deliberately undercounts partial progress rather than pretending
that its entire contract passed.

Failed, unsupported, unselected, and unimplemented obligations stay in the
denominator. There are 28 explicitly system-profile obligations; user-only runs
cannot cover them. `any` means a profile-independent contract, not evidence from
both profiles. The JSON profile breakdown groups labels; the `user` row alone is
not a denominator for all behavior relevant to user installations, because many
`any` obligations also apply.

Interface reach counts interfaces associated with covered obligations and
explicit CLI-option, library-function, or library-signal assertions. Explicit
assertions require a specific observable effect and a rationale. They cannot add
command or behavior-obligation credit, and their interface must match the case's
driver. This allows focused interface testing without redefining the 299-row
behavior denominator. Help tests cover only their help option, not the command's
main work.
Verified library-function reach additionally requires that
the test client reached that function's call site. A successful error test cannot
credit `flatpak_transaction_run()` if `add_install()` returned an error before
the run call. Call markers alone never earn coverage, and they are not a trace
of completion order. Signal reach similarly requires a recorded emission in the
passing case. The mapping still needs a relevant passing assertion.
Call evidence is currently collected per case, so mappings must be reviewed to
ensure a call belongs to the asserted outcome rather than unrelated setup.
Examples of credit intentionally withheld:

- Fixture creation invokes export commands, but does not test the target's
  export implementation.
- Adding a remote as setup does not establish property persistence until a
  later public query checks the expected values.
- Passing `--user` does not establish user/system selection precedence.
- Passing `--noninteractive` without confronting a choice does not test prompts.
- Empty enumeration does not exercise a per-element formatting loop.
- Logging transaction events does not establish their ordering or contents.
- Launching an app through the CLI in a library scenario does not exercise a
  library launch API.

Transaction tests assert ready rejection, operation success/error sequencing,
progress, remote choice, remote addition and EOL/rebase decisions. Authentication
tests use a public-wire authenticator fixture and a token-gated HTTP repository;
valid credentials permit protected downloads, while rejected credentials and
aborted basic-auth/webflow requests leave the installation empty. Pre-auth
inspection and parent-window propagation are also checked. Authenticator
installation and other incomplete contracts still receive no credit from logging.

## Freshness and reproducibility

Each execution records hashes of its assertion code, client, fixture preparation,
catalogues and mapping, plus the selected executable, resolved library and target
configuration. The runner pins the resolved executable before adapter setup, so
an adapter's PATH change cannot substitute a different CLI. It fingerprints the
adapter executable and directly identified file arguments, and rechecks selected
artifact hashes at completion. Changed artifacts invalidate passing credit.
These are start/end checks, not continuous monitoring. Target and fixture
provenance identify the run's subject; they are not a fingerprint of the entire
kernel and dependency environment.

Coverage verification compares the report's definition manifest with the current
suite. Changes to tests or definitions make older evidence stale. Interrupted
runs, unknown or duplicate cases, missing results, pending statuses and unconfirmed
cleanup cannot earn passing credit. Missing evidence is represented as `null`,
not zero or a successful skip. A zero denominator has no percentage.
Passing reports must retain subject provenance, timestamps, command arguments,
results, and the library client's call-stage evidence. Stripped reports cannot
keep their verified percentages while discarding that attribution and evidence.
The reporter validates this accounting and recorded evidence; it trusts the
runner's assertion results rather than independently replaying each assertion.

Source drift is checked separately with the generator's `--check` command. It
compares regenerated content and source hashes while ignoring only a changed git
HEAD. An unrelated commit therefore does not invalidate an unchanged interface
catalogue. Regeneration should accompany a review of affected behavior obligations
and mappings; it is not permission to shrink the denominator around the tests.

Snapshots are versioned baselines. Percentages from different catalogue revisions
are not directly comparable without inspecting changes to their denominators.

## Known reference discrepancy

### Remote priority tie order

`flatpak_installation_list_remotes()` documents highest priority first and, at
equal priority, earlier-added remotes before later-added ones. See its public
API comment in `common/flatpak-installation.c`.

The `remote-priority-order` case creates `remote-z-first`, then `remote-a-second`,
both at priority 20, followed by a priority-10 remote. Before modifying any of
them, reference Flatpak 1.19.1 returns `remote-a-second` before `remote-z-first`.
That contradicts the documented tie rule.

The case remains strict and fails on that reference build. Its obligation stays
implemented but receives no passing credit. It is separate from the remote
property scenario so the discrepancy does not prevent independent persistence
checks from executing. The compatibility contract does not accept an undocumented
ordering rule.

## AppStream callback execution checks

`FlatpakProgressCallback` documents callbacks in the caller's thread-default
context. GLib's [MainContext.invoke documentation](https://docs.gtk.org/glib/method.MainContext.invoke.html)
defines invocation in terms of context ownership and permits direct calls when
the current thread already owns that context. A different nested thread-default
context is therefore not itself a violation of the callback contract.

`coverage-progress-context` checks exact user data, caller thread, ownership of
the originally selected context, active call scope, nonempty UTF-8 display
status, and percentage bounds. It requires at least one callback during the
delayed refresh. Estimating follows gboolean zero/nonzero semantics, and the test
records callback count and final progress without prescribing their values.
Because [push_thread_default](https://docs.gtk.org/glib/method.MainContext.push_thread_default.html)
itself acquires the context, the ownership check verifies execution conditions;
it does not prove main-loop dispatch or distinguish valid direct invocation from
a queued callback.

The client keeps callback data alive while iterating both contexts for 250 ms
after return and during a second, callback-free refresh. It verifies the refreshed
public XML against the independently exported fixture. This is a bounded check
of post-call scope, not proof that a callback can never arrive later.

The six callback/search cases pass, covering the callback contract, search, explicit
AppStream refresh, extensionless bundle format selection, runtime-based app
filtering, and effective locale selection after config unset.

## Other unverified checks and remaining gaps

The complete run also retained failures for build-directory `/var` and empty-var
contracts, writable SDK/base initialization under the host's SELinux-xattr
restrictions, clearing inherited environment, `enter` output, named-installation
override isolation, related-ref enumeration, instance child-process identity,
unreachable-installation enumeration, and a documented nullable rebase argument.
Explicitly keyed bundle installation and the native collection-ID sideload-query
variant also remain failed checks in this run. Document forwarding previously
failed its behavioral assertion; this run cannot reach it because the private
document portal fails to start. That unmet prerequisite does not resolve or
replace the prior failure finding. The two additional failures are described
under "Six additional library contracts" above.
Review these observations separately. A failed assertion does not by itself prove
an implementation defect. None earns passing credit.

Non-root system-helper authorization, polkit, multiple users, authenticator
installation, document-portal workflows, repair recovery, and remaining
device/feature combinations need further work. Permission-store workflows use a
real isolated service, and history uses a private real journal. Root repair and
non-root refusal are compared against the same private populated installation;
this does not establish polkit authorization. Local-ref cleanup/prune partial
checks are retained without full credit because object retention/reclamation is
not established through public observations. The JSON report lists unmapped
obligations and the case evidence for credited interfaces.
