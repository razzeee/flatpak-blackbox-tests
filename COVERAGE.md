# What the coverage percentages mean

This suite reports separate measurements for catalogued behavior and public
interface reach. It does not report a percentage of all possible Flatpak behavior.
There is no finite denominator for all Flatpak behavior yet.

## Current inventory: all 624 CLI options accounted for

The suite now has **511 cases**, including 80 new cases after the 500-option
checkpoint below. The CLI-option denominators have not changed.

| Measurement | Implemented | Meaning |
| --- | ---: | --- |
| Option-specific assertions | **584/624, 93.59%** | Tests assert a distinguishable option effect |
| Separate equivalence checks | **40/624, 6.41%** | Tests assert ordinary results under default-equivalent or context-inapplicable options |
| CLI-option inventory accounting | **624/624, 100%** | Deduplicated union of both kinds |

All 136 CLI and 164 library behavior obligations, 44 commands, 224 public
library functions and 14 signals still have implementations. These are
implementation counts. **Full inventory accounting is not full passing coverage.**

The 84 additional option-specific assertions cover confirmation, vendor
preinstallation, SDK/base initialization, signing-key trust, remote
authentication and metadata, installation selectors, USB exports, accessibility,
process lifetime and visibility, forced removal, diagnostics and filesystem
synchronization. Synchronization cases trace actual `fsync`/`fdatasync` calls
while independently checking exported content and repository integrity.
Process-lifetime cases observe a real launching process exit and use a
helper-local subreaper to stop and reap their descendants.

### Separate equivalence accounting

Scenario mappings use `equivalent_options` when the ordinary result is tested
without establishing an option-specific effect. Such mappings never increase
the behavioral CLI-option metric. Reports expose `cli_option_accounting` in
JSON and separate inventory tables in Markdown, console and GitHub summaries.
Passing equivalence credit requires a complete, current, verified passing case
with the selected CLI command and a leading option in its recorded invocation.
Option-like payload arguments cannot establish credit. Wrapped commands record
their exact executed `cli_argv` suffix.

These cases retain independent result assertions. For example, explicit
`document-export --allow-read` must provide actual read-only sandbox access,
and permission commands with diagnostic flags must preserve exact permission
store results. They do not merely check that a parser accepts an option.

Some equivalence checks deliberately cover an inapplicable context. A GPG home
on a native bundle does not establish OCI signing-key selection. Lookaside
options on native OSTree remotes do not establish OCI signature retrieval.
A delta worker count without delta generation does not establish concurrency
limits. Those limitations remain even though the options are accounted for.

### Local reference validation

Local runs of both reference builds produce the same outcomes for the 80 new cases:

| Target | Revision | Passed | Assertion failures | Local environment failures |
| --- | --- | ---: | ---: | ---: |
| CI-pinned Flatpak 1.19.1 | `1a6ec6a1f720fb30d76c76e656ac624fcaa237e9` | 70 | 6 | 4 |
| Upstream main, Flatpak 1.19.1 | `a1bcecfc6cd2e33477e8d186acac631119780d06` | 70 | 6 | 4 |

The six assertion failures remain visible and earn no passing credit:

- `remote-add --no-follow-redirect` is rejected as an unknown option.
- `remote-modify --no-follow-redirect` does not retain the original URL after
  a redirect appears in independently published metadata.
- `remote-modify --follow-redirect` does not enable following after the URL
  has been explicitly pinned.
- Explicit `install --gpg-file` verification of the independently signed bundle
  in the new trust scenario exits with signal 11.
- After changing the default system installation's current branch, a branchless
  system launch still reports the competing master-branch commit.
- `update --force-remove` leaves the old payload visible in the running sandbox.
  The corresponding forced-uninstall case passes.

Four build initialization cases stop at `security.selinux` xattr writes that the
local container filesystem rejects. They cover `--type`, `--var`,
`--sdk-extension` and `--base-extension`. Their local reports retain failed
status and zero passing credit. All four pass on the Ubuntu worker described below.

The passing focused cases verify **72 of the 84 new option-specific assertions**
and **all 40 equivalence checks** on each target. Each target also rejects all
72 option-removal controls, giving **144 deliberately failing controls** with
zero passing credit. Mutating wrappers emit no diagnostic text, so wrapper
messages cannot satisfy verbosity checks. Confirmation cleanup uses a separate
approval spelling so removal of the option under test reaches its own assertion.

All nine existing authentication cases pass on each target, giving 18 additional
regression reports after extending the independent authenticator's wire checks.
The focused reference builds disable the system helper. System-selector cases
use the existing disposable root user/mount namespaces; they do not establish
non-root helper authorization.

`create-usb --allow-partial` is specifically a warning-suppression option. Its
case verifies removal of the actual warning while preserving other diagnostics
and the command status. The reference's independent partial-export failure is
recorded separately; a full-install export control succeeds. This is not a claim
that partial USB export succeeds on these references.

Locked Ruff, ty and strict mypy pass, as do static JSON formatting and the source
catalogue check. The host unit run executes 129 tests with the optional prepared
fixture test skipped; all 17 fixture-schema tests, including that round trip,
also pass in the prepared container.

The external `selection-reference-evidence` directory contains the final indexes
`final-remaining-v4-{pinned,upstream}{,-negative,-auth}-index.json`.
`remaining-summary.json` audits all **322 reports**, recomputes their coverage,
records report hashes and confirms their shared definition fingerprint:
`e51748f26587cf3676a9f60331f3abb585e29deb4f8333b06f6e3abf93e3c6aa`.
These focused reports do not establish whole-suite passing percentages.

### Full Ubuntu CI validation

[Run 35596676314](https://github.com/razzeee/flatpak-blackbox-tests/actions/runs/35596676314)
executes the full suite against the pinned reference with freshly prepared
fixtures and the provisioned system helper. Its complete report matches the same
definition fingerprint above and records **481 passing and 29 failing cases**.
The 80 added cases have **74 passes and six failures**. The same 23 existing cases
still fail; no previously passing existing case regressed.

All five new build initialization cases pass in CI, including the four blocked
by the local filesystem. CI exposed an existing preparation bug during development:
`ExtensionOf` payloads are exported from `files/`, but the contract preparer had
written extension markers under `usr/`. Preparation now uses the correct directory
and verifies the bytes in each exported commit. The new copy cases reject older
markerless fixtures as an unmet prerequisite.

| Full CI option measurement | Passing evidence |
| --- | ---: |
| Option-specific assertions | **572/624, 91.67%** |
| Separate equivalence checks | **40/624, 6.41%** |
| Deduplicated option inventory accounting | **612/624, 98.08%** |

The six new failures are the reference failures listed above. They retain zero
passing credit, and the compatibility job remains unsuccessful. The source
catalogue, lint/type checks, unit tests and coverage-site checks pass.

The 12 options without passing inventory evidence are:

- `document-export --noexist`
- `install --gpg-file`
- `make-current --user`, `--system`, `--installation`
- `override --installation`
- `remote-add --no-follow-redirect`
- `remote-modify --follow-redirect`, `--no-follow-redirect`
- `run --clear-env`, `--file-forwarding`
- `update --force-remove`

A failed multi-option case grants no credit to any of its options; this list does
not assert that each option independently fails.

## Previous expansion: complete behavior inventory, 500 CLI options

The suite now has **430 cases**. All **136/136 CLI** and **163/163 library**
behavior obligations have implementations, along with all 44 commands,
223 public library functions and 14 signals. Implemented CLI-option coverage is
**500/624, or 80.13%**, up from 433/624 at the selection checkpoint below.
Denominators are unchanged. These are implementation counts, not a claim that
the entire compatibility suite passes or that all possible Flatpak behavior is covered.

The additional 67 CLI-option assertions cover:

| Area | Additional options |
| --- | ---: |
| Remote default branches, disabling, filtering and GPG trust | 7 |
| Observable Flatpak/OSTree diagnostics | 34 |
| Build/run permissions and persistent storage | 13 |
| Real D-Bus ownership, method access and traffic logging | 10 |
| Image parsing and sideload installation/update | 3 |

Diagnostic cases compare quiet, flagged and quiet-again invocations. They require
additional diagnostics while preserving ordinary output and public state. Fault
injection records its own activity out of band, so its messages cannot satisfy
the diagnostic assertions. Probes that emit no diagnostics earn no option credit.

Sandbox cases use host listener connections, shared-memory marker reads, socket
visibility, persistent file contents and a real `ptrace` syscall. Bus cases
actually acquire names and call a controlled echo service through private session
and system-bus proxies. Unrelated rules keep build proxies enabled while the
specific grant under test is removed. Logging must identify the real call's
method and destination. No host system bus is used.

Image cases respect automatic detection of valid OCI prefixes. Explicit `--image`
is distinguished by forcing image-specific rejection of an unsupported transport,
then validating independent A/B image payloads. Sideload cases first fail an
ordinary transfer with HTTP payloads blocked, then install or update to the exact
signed commit without remote payload requests. Update inputs contain changed
executable bytes, preventing a cached or metadata-only update from satisfying the test.

### Successful authenticator installation

The last library obligation now has both refusal and success evidence. The
`install-authenticator` handler verifies the exact remote/ref and confirms that
the app is absent. It installs that app through a nested native transaction,
checks the independent commit and launches the installed authenticator in its
sandbox. The service validates the actual request and supplies the token needed
by the independently gated HTTP repository. The protected commit, authenticator
and its GIO runtime must be the exact final installed set; service bytes must
match the independently prepared executable.

The authenticator grants access to the case's private session bus so its unicast
response signals can reach the caller. This does not expose the host session bus.
CLI launch is an observer and adds no library launch credit. Older placeholder
fixtures still support refusal, but report an unmet prerequisite for the new
success case. Full preparation now builds the runnable service and runtime.

### Validation and remaining work

The combined 43 CLI cases and authenticator-success case pass against both the
CI-pinned commit `1a6ec6a1f720fb30d76c76e656ac624fcaa237e9` and upstream main at
`a1bcecfc6cd2e33477e8d186acac631119780d06`, both reporting Flatpak 1.19.1.
Both are fresh local builds with the system helper disabled; these are isolated
user-installation checks, not a replacement for full CI. All runs use a freshly
prepared complete fixture set. There are **88 passing focused reports** and
**77 deliberately failing controls**: 75 option-removal variants and two library
controls that suppress authenticator installation or refuse its launch. Every
negative report earns zero passing credit. Eight existing authentication cases
also passed regression checks during development.

The final CLI runs use a disposable Ubuntu container with an init process to reap
exited sandbox helpers. An earlier container exhausted its process limit because
it lacked that reaper; those failed runs are excluded from the final evidence.

Locked Ruff, ty, strict mypy, static JSON formatting, the source catalogue check
and all **125 unit tests** pass. The fixture round-trip test also covers the new
complete manifest. Independent preparation and the native client builds succeed
with their warning-as-error settings.

Final reports are indexed in the external `selection-reference-evidence` directory
by `final-pinned-positive-index.json`, `final-upstream-positive-index.json` and
`final-pinned-negative-index.json`. The four native reports are under
`final-auth-{pinned,upstream,negative-skip-install,negative-refuse-launch}/report.json`.
`expansion-summary.json` audits all 165 reports, their artifact integrity and
their shared definition fingerprint:
`a179f385316d8f84777ac80473b81f08f18c7230a60717160a3b6aed47c51a36`.

The PR review follow-up tightens GPG and filtered-ref rejection diagnostics so
unrelated failures cannot satisfy those checks. All six affected remote scenarios
pass again on both reference builds. Their 12 reports are indexed by
`pr15-review-index.json`, with definition fingerprint
`530fe5197d9fdb0c69e2cbb8d57bf3231639aed73afbdb3eff22f3507e0b9d0b`.
The initial PR revision's full CI run records 407 passing and 23 failing cases;
all 44 cases added by this expansion pass, and the failures are in existing cases.

**124 CLI options remain** before implemented option coverage reaches 100%:

| Remaining group | Options |
| --- | ---: |
| Other verbosity options | 52 |
| Remote authentication, redirects, subsets and metadata settings | 17 |
| Preinstall | 10 |
| Remaining build/run feature, process and accessibility controls | 10 |
| Build initialization, bundles, repository operations and distribution controls | 26 |
| Make-current, search and repair installation selectors | 8 |
| Document read grant | 1 |

## CLI SDK/debug and subpath selection

Five additional cases bring the suite to **391 cases** and implemented
CLI-option reach to **433/624, or 69.39%**, up from 429/624. Catalogued behavior
coverage remains 136/136 CLI and 162/163 library obligations. These cases add
option assertions without changing any denominator or claiming behavior credit.

- `install --include-sdk` and `--include-debug` run in all four combinations
  against fresh, already-current and updatable apps. Each checks exact independent
  commits for the app, runtime, related extensions, SDK and debug refs. The SDK
  differs from the runtime; its debug ref is included only when both flags are on.
  Already-current apps must still gain the requested dependencies. Inclusion
  flags must update an older app without explicit `--or-update`, while the
  ordinary repeated-install control retains its old commit.
- `install --subpath` selects either of two disjoint payload directories. Repeated
  options and an ordinary full-install control must deploy both. Assertions use
  `info --show-location` and check excluded files as well as included files and
  the independent marker contents.
- `update --subpath` starts from a bin-only A deployment and advances to B.
  Omission preserves the original subset; a single option replaces it and
  repeated options expand it. A subsequent explicit-commit update back to A,
  without subpath options, verifies that selection persists across another
  deployment rather than merely a same-commit no-op.

All five cases pass against three targets:

| Target | Source revision |
| --- | --- |
| Installed Flatpak 1.18.2 | Distribution binary recorded by hash in each report |
| CI-pinned Flatpak 1.19.1 | `1a6ec6a1f720fb30d76c76e656ac624fcaa237e9` |
| Upstream main, also reporting 1.19.1 | `a1bcecfc6cd2e33477e8d186acac631119780d06` |

The two source targets were freshly built in a disposable Ubuntu 24.04 container.
Tests ran as an ordinary user. These builds disable the system helper and test
only isolated user installations; they do not substitute for the full CI setup.

Seventeen targeted negative controls also run against each target. They remove
individual options, keep only the first or last repeated subpath, forget a stored
subset, suppress dependency installation for an already-current app, omit only
SDK debug, add unrequested debug refs, or install the correct dependencies while
restoring the old app commit. All 51 control runs fail their intended ref-set,
commit or payload-selection assertion and earn zero passing credit. The 15
positive runs credit exactly the four options above. These focused runs do not
establish full-suite passing percentages.

A second, freshly exported fixture set also passes all five cases against the
pinned build. Preparation uses the existing basic, query and contract exporters;
these tests require no new fixture format or payload. This gives 20 passing
focused reports alongside the 51 deliberately failing negative controls.

An exploratory rejection check for `--include-sdk --no-deps` was removed. Both
1.18.2 and the pinned build return success, install the app and omit the SDK.
The manual calls the options incompatible but does not explicitly specify an
error result. This observation is not counted as an implementation defect or
additional coverage.

Locked Ruff, ty, strict mypy, JSON formatting, the source catalogue check and
all 123 unit tests pass, including the prepared-fixture round trip.

Reports and validation scripts are retained outside the repository in the local
`selection-reference-evidence` artifact directory. The indexes are
`{host,pinned,upstream}-{reviewed,faults-reviewed}-index.json` and
`fresh-pinned-reviewed-index.json`; they name all 71 reports and record their
suite fingerprint. Container paths beginning `/evidence/` map to that artifact
directory. The final definition fingerprint is
`2471cc87986d9de0b2720292a7bc1ac4477b13a320ece3a8f1a848b72059fce9`.
The existing `six-contract-fixtures-04` inputs from the imported Flatpak checkout
were checksum-validated and reused without modification; their manifest SHA-256 is
`05ceae1af2272444bbc2d3fdbf142f0b9de52ed7c7854b6906bce7d0db098a61`.
The freshly exported fixture manifest SHA-256 is
`8b5d7fde2c6dc74799910c0598df19a692b593b3a9f8ffc2d5a2f99e6fa9e780`.

## Cross-user library and authorization contracts

Six new cases bring the suite to **383 cases** and implemented library behavior
to **162/163, or 99.39%**. CLI behavior remains 136/136 and CLI-option reach remains
429/624. Successful authenticator installation is the sole remaining unmapped
catalogued behavior obligation. Denominators are unchanged, and these focused
runs do not establish full-suite passing percentages.

The four lifecycle/remote cases use the selected system helper, real polkit and
two distinct ordinary users. Install requests only the app and verifies its
implicit runtime dependency. Update selects advertised B with commit NULL and
retains the runtime. Uninstall yields public NOT_INSTALLED errors for the app
while retaining only the runtime. The reader observes remote addition and URL
changes through fresh library objects, then both users observe removal. Default
and per-user remote snapshots remain unchanged. Each user must load the selected
target library, and each case uses fresh named-installation state with umask 0022.

The authorization cases compile an independent process-scoped polkit agent that
records requests and rejects all authentication. Installation settings produce
interactive/silent/interactive request counts of **1, 0, 1**. Transaction inheritance
and explicit overrides in both directions produce **1, 0, 1, 0, 1**. Getters must
match settings. Every attempted mutation must fail authorization and leave the
seeded configuration and installed refs/commits unchanged.

Configuration errors may be public D-Bus AccessDenied or Flatpak permission-denied.
A transaction's top-level ABORTED error is accepted only when its operation-error
callback identifies a permission-denied failure for the requested ref. An unrelated
failure cannot satisfy these checks.

All six cases pass against the helper-enabled CI-pinned Flatpak 1.19.1 build.
Nine library-interposer controls fail their intended assertions and earn zero
passing credit. They redirect system selection to a user installation, suppress
runtime dependency resolution, update, uninstall, remote modification or removal,
or ignore installation/transaction interaction settings and inheritance. The
interaction controls preserve the expected getter values, so real agent request
counts detect the incorrect behavior.

CI now places the build and fixture directory under `/tmp` for access by both test
users. Privileged bridge sources under `ci/` participate in the suite definition
fingerprint. The unit tests verify that changing a bridge invalidates prior
coverage, and that its privileged entry points reject unprovisioned hosts.

Ruff, ty, strict mypy, JSON formatting, the source catalogue check and the unit
suite pass. The optional prepared-fixture test also passes in the container.
A run without active provisioning reports an unmet prerequisite with zero passing
credit. The updated provisioning probe, its allow-reader negative control and
cleanup also pass their expected checks. GitHub Actions has not yet run these
changes remotely.

All fifteen focused positive/negative reports share definition fingerprint
`9861214269b134b2e249d05a798d490b925ec1096f17646812a839344f9714b0`.
Evidence is local to `flatpak-blackbox-coverage-portals` under
`/tmp/multiuser-final-*/report.json` and `/tmp/multiuser-negative-final-*/report.json`,
with provisioning logs in `/tmp/helper-ci/logs`. These artifacts are not published
with the repository.

## Related-ref options and forced repair redeployment

Four additional focused cases bring the suite to 377 cases and implemented
CLI-option reach to **429/624, or 68.75%**. Catalogued CLI behavior remains
136/136 and library behavior 156/163. These option assertions add no behavior
credit or denominator entries.

- `install --no-related` omits the available locale extension while installing
  the required runtime. Ordinary installation includes the locale.
- `update --no-related` leaves an absent locale extension uninstalled. Ordinary
  update installs it while preserving the app and runtime commits.
- `uninstall --no-related` retains the app's autodelete locale extension.
  Ordinary uninstall removes it. Both retain the runtime.
- `repair --reinstall-all` restores an executable unlinked from the public app
  deployment while its repository object remains intact. Ordinary repair leaves
  that damage in place. Forced repair restores the independent fixture bytes and
  runs version A via an absolute `/app/bin/blackbox-probe` command, preventing
  fallback to the runtime's identically named executable.

All four cases pass against CI-pinned Flatpak 1.19.1. Removing each option in a
negative-control wrapper fails its state assertion and earns zero passing credit.
The eight reports are local to `flatpak-blackbox-coverage-portals` under
`/tmp/state-options-final-{install,update,uninstall,repair}-{False,True}/report.json`,
where `True` denotes a negative control. Together with the five repair reports
below, they share definition fingerprint
`e21c9cccb7f1b04bac0157573241359997da2751bd312a8ec09c30c7ab0bf295`.

## System-helper environment

The CI reference build now enables the system helper. A provisioning probe uses
real polkit decisions and two ordinary user identities on the existing disposable
VM. It checks the selected helper's bus-owner PID, installation by the allowed
user, exact app/runtime commits visible to both users, and denied remote mutation
by the reader. Cleanup removes the test users, named installation and policies and
restores any previous action policy.

The probe and cleanup pass locally in a disposable Ubuntu 24.04 Podman container
with a helper-enabled build of the pinned commit. A negative control granting the
reader permission fails the denial assertion. The GitHub Actions integration has
not yet been run remotely. Existing CLI and library lifecycle cases also pass with
the helper-enabled build while the provisioned helper is running. Probe, cleanup
and negative-control logs are retained locally in `/tmp/helper-ci/logs`; the
lifecycle report is `/tmp/helper-lifecycle/report.json` in the same container.
This infrastructure earns no behavior coverage; the
six authorization and cross-user library obligations still need implementations,
including an authentication-agent fixture for no-interaction contrasts.

## User repair contracts

Two new cases cover the remaining catalogued CLI behavior obligations. The suite
now has 373 cases, with implemented CLI behavior at **136/136** and CLI-option
reach at **425/624, or 68.11%**. Library behavior remains 156/163. Denominators
are unchanged; these focused results do not establish full-suite passing coverage.

Both cases pass against CI-pinned Flatpak 1.19.1 with independent fixtures. The
reference adapter removes the executable payload object used by the installed app
and runtime. Real repair must restore exact commits and permit offline
reinstallation of both refs, followed by execution of app version A. A surviving
deployment alone cannot satisfy the recovery assertion.

The dry-run case compares healthy and damaged diagnostics, requires a new line
identifying the affected app, and compares installation snapshots before and after
the dry run. Snapshots cover paths, file types, ownership, modes, symlink targets
and file contents, excluding timestamps. Subsequent real repair must pass the same
offline redeployment checks.

Three negative controls fail their intended assertions: a no-op repair cannot
redeploy offline, ignoring `--dry-run` changes the installation snapshot, and
discarding inconsistency diagnostics fails the affected-app assertion.

An exploratory missing-commit variant failed: Flatpak detected the absent commit
but reinstallation returned `No such metadata object`, even though the fixture
source retained that commit. The committed cases cover missing payload recovery,
not missing commit metadata recovery. That broader failure still needs diagnosis.

Ruff, ty, strict mypy, JSON formatting and the source catalogue check pass.
The unit suite passes with one optional prepared-fixture test skipped locally;
the fixture-manifest tests also pass in the container with that check enabled.

All five final reports match the definition fingerprint recorded above.
Focused evidence is local to the `flatpak-blackbox-coverage-portals` container at
`/tmp/repair-complete-{restore,dry,noop,ignore-dry-run,silent}/report.json`.
These artifacts are not published with the repository.

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
