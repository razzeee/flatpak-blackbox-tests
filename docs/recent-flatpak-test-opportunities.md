# Recent upstream Flatpak: black-box test opportunities

Research snapshot: **2026-10-15**. Scope: upstream changes approximately November
2025–October 2026, with emphasis on recent stable fixes and merged development
changes. This is a test-design report, not evidence that any target passes.

## Verified upstream baseline

The first-party GitHub [releases API](https://api.github.com/repos/flatpak/flatpak/releases?per_page=20)
reports **1.18.4** as the latest stable release and **1.19.2** as the latest
development prerelease, both published **2026-09-28**. The latter explicitly says
the next stable series will start at 1.20.0; it does **not** establish that 1.20.0
has shipped. The latest default-branch commit returned during research was a
translation update dated **2026-10-15**
([ddbee83](https://github.com/flatpak/flatpak/commit/ddbee83f4664b63f6e15ae563f52e4cc73ade185)).
Thus these source dates agree with the environment's October 2026 date; none of
the October changes below is assumed to be in a released version.

Useful release anchors:

| Release | Publication date | Relevant changes |
| --- | --- | --- |
| [1.17.0](https://github.com/flatpak/flatpak/releases/tag/1.17.0) | 2025-11-03 | Conditional permissions, JSON output, `run --clear-env`, build isolation, OCI installation/sideloading. |
| [1.17.4](https://github.com/flatpak/flatpak/releases/tag/1.17.4) / [1.16.4](https://github.com/flatpak/flatpak/releases/tag/1.16.4) | 2026-04-08 / 2026-04-07 | Sandbox escape/deletion fixes; development extension branch following. |
| [1.17.6](https://github.com/flatpak/flatpak/releases/tag/1.17.6) / [1.16.6](https://github.com/flatpak/flatpak/releases/tag/1.16.6) | 2026-04-10 | Follow-up browser/subsandbox and extra-data regressions; development repair pin preservation. |
| [1.18.0](https://github.com/flatpak/flatpak/releases/tag/1.18.0) | 2026-06-08 | New stable series; DRI permission includes `/dev/kfd`. |
| [1.18.1](https://github.com/flatpak/flatpak/releases/tag/1.18.1) / [1.19.0](https://github.com/flatpak/flatpak/releases/tag/1.19.0) | 2026-08-11 | Extensive security fixes; development transfer-rate API and authentication/clear-env fixes. |
| [1.18.2](https://github.com/flatpak/flatpak/releases/tag/1.18.2) | 2026-08-27 | Summary validation, extension/openat2 and portal FD fixes. |
| [1.18.3](https://github.com/flatpak/flatpak/releases/tag/1.18.3) | 2026-09-22 | Fix build regressions introduced by 1.18.2, subsandbox negated bus permissions, explicit bundle-key cleanup. |
| [1.18.4](https://github.com/flatpak/flatpak/releases/tag/1.18.4) / [1.19.2](https://github.com/flatpak/flatpak/releases/tag/1.19.2) | 2026-09-28 | Deployment traversal, export allowlist, OCI token/cache permissions and process-group fixes; development user-data deletion API, cache refresh and size improvements. |

**Version policy:** release notes establish inclusion on the named branch, not
every downstream package. Prefer capability probes, record target/package and
helper versions, and account for security backports. For example, the suite's
[`library_features.py`](../library_features.py) already compiles and links typed
API probes instead of relying on version comparisons.

## How coverage was assessed

Reviewed [`COVERAGE.md`](../COVERAGE.md), [`scenario_catalogue.py`](../scenario_catalogue.py),
the executable scenario modules and their `scenario-data/` documents, plus
relevant C clients. “Gap” below means no matching assertion was found in this
checkout; it does not mean the command/API has no coverage. “Existing” means an
implemented assertion, **not** verified passing evidence. Upstream claims below
are grounded in release notes, published advisories, or merged PR descriptions
and executable diffs/tests, not uncorroborated source comments.

Priorities: **P0** security boundaries, **P1** high-value compatibility/regression
contracts, **P2** narrower output/platform behavior. Security fixtures must use
only expendable canaries in a disposable VM/private installation and private
process groups; never point attack paths at real home directories or `/etc`.

## Recommended additions

### 1. P0 — Deployment traversal must not write or delete outside the deployment

- **Upstream:** advisories published 2026-09-28, fixed in stable **1.18.4**:
  [GHSA-8xgq-v545-vgvf](https://github.com/flatpak/flatpak/security/advisories/GHSA-8xgq-v545-vgvf)
  (`files/etc` writes) and
  [GHSA-5p67-xh8x-rq54](https://github.com/flatpak/flatpak/security/advisories/GHSA-5p67-xh8x-rq54)
  (`export/bin` deletion). Advisories identify the fd-relative fix commits.
- **Suite gap:** ordinary export/build/install and repair tests exist, but no
  malicious deployment symlink canary test was found.
- **Assertions:** independently prepare malicious update payloads redirecting
  `files/etc` and `export/bin` to private external directories. Seed `passwd`,
  `group`, `machine-id`, `resolv.conf`, and deletion canaries there. Run
  install/update through CLI and libflatpak. Every external canary retains its
  bytes and file type; `resolv.conf` must not become a symlink. Rejecting the
  malformed deployment is acceptable; a successful operation must remain confined.
  Follow with an ordinary valid update and verify its exact commit and execution.
- **Prerequisites:** independently generated OSTree commits, isolated writable
  deployment storage, user profile first; disposable system-helper profile for
  the root-context guarantee. Do not require one exact diagnostic message.

### 2. P0 — Export filtering must remove unsafe keys without breaking safe entries

- **Upstream:** [GHSA-v64f-hrwr-j4vh](https://github.com/flatpak/flatpak/security/advisories/GHSA-v64f-hrwr-j4vh),
  published 2026-09-28, says fixed in **1.18.4**. Its
  [3393102 implementation and regression assertion](https://github.com/flatpak/flatpak/commit/33931025ff74f4db7b09f0ad331e76f9fd9ab99e)
  replace a denylist with allowlists.
- **Suite gap:** `sandbox_scenarios.py::_make_current` checks ordinary desktop
  export selection; it does not exercise field/group sanitization.
- **Assertions:** install a fixture with a D-Bus service containing `Name`,
  `Exec`, `SystemdService`, `User`, and an unknown key. Inspect the public exported
  service: safe name survives, execution is wrapped by Flatpak, unsafe/unknown
  keys disappear. For desktop exports, retain `Name`, localized `Name[de]`,
  `Icon`, and valid action entries; strip `TryExec`, unknown vendor keys and
  unrecognized groups. Verify an action's `Exec` is also wrapped. Keep an
  allowlisted safe-key control to catch an overbroad “delete all metadata” fix.
- **Prerequisites:** independently prepared exported files, private user install;
  no real D-Bus service activation needed. Use an unknown vendor key, not a key
  newly allowlisted later (October development changes already extend the list).

### 3. P0 — An app's process-group signals must not reach its host parent

- **Upstream:** [GHSA-f3p8-vr7v-gxf2](https://github.com/flatpak/flatpak/security/advisories/GHSA-f3p8-vr7v-gxf2),
  published 2026-09-28, fixed in **1.18.4** by
  [a3cf27b](https://github.com/flatpak/flatpak/commit/a3cf27b5d6f365777259bd26ffa0d369c5ed7874).
- **Suite gap:** process/kill and parent-lifetime scenarios do not establish
  containment of `kill(0, signal)` or `killpg(0, signal)` issued inside the app.
- **Assertions:** a dedicated host supervisor records receipt of a harmless
  caught signal; launch an app that sends that signal to its own process group.
  Confirm the inner signal operation actually executed while the supervisor
  receives nothing and remains responsive. Exercise both signal APIs.
- **Prerequisites:** small signal-aware fixture; create a private supervisor
  session/group so even a vulnerable target cannot signal the runner/desktop.
  Merely wrapping `flatpak run` in `setsid` and checking runner survival is
  insufficient: the supervisor inside that private group is the canary.

### 4. P0 — libflatpak permissive-umask caches and OCI credentials

- **Upstream:** published 2026-09-28, fixed in **1.18.4**:
  [GHSA-r9w3-qx54-qvc8](https://github.com/flatpak/flatpak/security/advisories/GHSA-r9w3-qx54-qvc8)
  restricts temporary child repositories; explicitly notes that normal CLI
  startup's umask masks the libflatpak vulnerability.
  [GHSA-7rvf-rqr3-43j4](https://github.com/flatpak/flatpak/security/advisories/GHSA-7rvf-rqr3-43j4)
  stops persisting OCI bearer tokens to child-repository disk storage.
- **Suite gap:** authentication, multiuser and system transactions exist, but no
  permissive-umask/OCI token-confidentiality assertion was found.
- **Assertions:** in a dedicated C client set `umask(000)` before a real system
  transaction. Pause controlled transfers while an independent second UID probes
  temporary repository paths: none may be writable by that UID. For an
  authenticated OCI transaction, the second UID must not recover the unique
  synthetic bearer token from child repositories; verify authorized download and
  exact deployed content, so simply disabling downloads cannot pass. Capture
  observations during transfer, not just after cleanup.
- **Prerequisites:** disposable two-UID system-helper/polkit environment and
  controlled OCI registry. Backend path discovery belongs in an adapter; document
  this as a security profile, not a backend-neutral storage API guarantee.

### 5. P0 — App-data, SDK extension, and runtime extension traversal

- **Upstream:** **1.18.1**, advisories published 2026-08-11:
  [app-data symlink escape](https://github.com/flatpak/flatpak/security/advisories/GHSA-8688-9x26-hhxj),
  [build-init extension copy traversal](https://github.com/flatpak/flatpak/security/advisories/GHSA-8qxj-x646-phcm),
  and [extension metadata/host probing](https://github.com/flatpak/flatpak/security/advisories/GHSA-w69g-9x8j-7p8f).
  The app-data advisory links both a negative regression test and a Steam-like
  positive compatibility test.
- **Suite gap:** `sandbox-persist`, `/var/data` persistence, build-init extension
  copying and related-ref selection are positive tests, not adversarial confinement.
- **Assertions:** (a) replace app-controlled cache/tmp and data-directory
  components with symlinks to private external canaries; a new launch must not
  expose or change the external files. (b) Give SDK/base extension metadata a
  `directory=../../...` destination; `build-init --writable-sdk --sdk-extension`
  must not delete/replace a sibling canary. (c) Use invalid extension path fields
  and merge-directory symlinks; app-visible listings must not disclose external
  canary filenames or install extension content at unintended mount points.
  Pair each malformed fixture with a valid copy/mount/persistence control.
- **Prerequisites:** separate cases rather than one all-or-nothing test; synthetic
  SDK/extensions, private home and sandbox runtime. General permission denial
  does not prove symlink confinement. Deterministic fixtures do not prove absence
  of every race; leave race/fault-injection claims to a dedicated stress profile.

### 6. P1 — Repair must preserve pins, including unpinned dependencies

- **Upstream:** [PR #6571](https://github.com/flatpak/flatpak/pull/6571), merged
  **2026-04-10**, shipped in development **1.17.6**; disables auto-pin in repair.
  Its executable upstream test compares pin output before/after reinstall-all.
- **Suite gap:** [`repair_scenarios.py`](../repair_scenarios.py) verifies restored
  bytes, commits and execution but never checks pins. The separate `tx-auto-pin`
  test does not exercise repair's internal transaction setup.
- **Assertions:** create one explicit pin and one unpinned dependency runtime;
  compare normalized `flatpak pin` sets before/after both ordinary repair and
  `repair --reinstall-all`. After removing the dependent app, `uninstall --unused`
  must remove the unpinned runtime while retaining the pinned control.
- **Prerequisites:** existing repair fixtures plus an independent pinned runtime;
  low implementation cost, no malicious payloads required. Add user and isolated
  system variants where repair is supported. Avoid interactive pin counts when
  comparing sets (see October PR #6759).

### 7. P1 — `--assumeyes` is not `--noninteractive` for authentication

- **Upstream:** [PR #6744](https://github.com/flatpak/flatpak/pull/6744), merged
  **2026-07-29**, included in development **1.19.0**. The diff removes setting
  libflatpak's no-interaction flag for `-y`; upstream tests distinguish the
  authenticator request option for `-y` versus `--noninteractive`.
- **Suite gap:** [`confirmation_option_scenarios.py`](../confirmation_option_scenarios.py)
  correctly proves both options bypass ordinary confirmation. Existing
  `auth_scenarios.py` exercises library authentication separately, not this CLI
  distinction; treating the two options as interchangeable would miss this bug.
- **Assertions:** use a real authenticator fixture to record request options:
  `install -y` must not request no-interaction, whereas `--noninteractive` must.
  Under a PTY, `-y` should still allow the required basic-auth exchange and install
  the exact commit. Noninteractive operation must not hang waiting for credentials;
  a fixture that can supply a token noninteractively may still succeed.
- **Prerequisites:** reuse the independent authenticator/token-gated HTTP service;
  add CLI launch/PTY support and bounded deadlines. Do not assume all
  noninteractive authentication must fail.

### 8. P1 — Opted-in no-autodownload extensions must follow branch changes

- **Upstream:** [PR #6550](https://github.com/flatpak/flatpak/pull/6550), merged
  **2026-03-29**, development **1.17.4**. The implementation checks installed
  branches for the same extension ID **and architecture**, and adds an end-to-end
  branch-following test.
- **Suite gap:** related-ref and extension copying/metadata cases do not establish
  migration from a previously installed branch when the parent's requirement changes.
- **Assertions:** app A requests extension branch 1 with `no-autodownload=true`;
  explicitly install it. Publish app B requiring branch 2, then update: branch 2
  is installed with expected bytes and mounted content. In a fresh installation
  without the prior opt-in, updating to B must not auto-install that extension.
  A different-architecture installed branch must not satisfy the opt-in check.
- **Prerequisites:** two parent metadata versions and two extension branches;
  inspect exact installed refs via CLI and resolved operations via libflatpak.
  No assertion that branch 1 is automatically removed: this change does not promise it.

### 9. P1 — OCI `remote-ls --updates` must agree with actual update state

- **Upstream:** [PR #6875](https://github.com/flatpak/flatpak/pull/6875), merged
  **2026-10-09**, **unreleased default branch**. Compares remote checksum with
  both deployed OSTree commit and OCI alternative image digest, retaining origin
  filtering. The PR includes install/update/list integration tests.
- **Suite gap:** `remote-ls`/update and OCI image import coverage do not establish
  update-list correctness against a live OCI remote whose image digest differs
  from its imported commit.
- **Assertions:** after installing OCI app/runtime A, `remote-ls --updates` is
  empty. Publish app B only: exactly that app is listed. Update it: listing is
  empty again, commit/alternative ID and execution identify B. A second remote
  with a same-named ref must not bypass the installed-origin filter.
- **Prerequisites:** independent local OCI registry with publishable revisions;
  run user/system variants. Do not extend this claim to `list --columns=latest`:
  the PR explicitly leaves that behavior unchanged.

### 10. P1 — Recover dropped/truncated HTTP responses without retaining partial data

- **Upstream:** [PR #6881](https://github.com/flatpak/flatpak/pull/6881), merged
  **2026-10-12**, **unreleased default branch**. Curl error mapping now reaches
  existing retry handling. Added tests cover empty reply, truncated response and
  compressed cache output; retry limit and already-written-stream policy are unchanged.
- **Suite gap:** `tx-error-sequence` checks failure followed by a second explicit
  transaction; it does not prove automatic retry inside one CLI/library invocation.
- **Assertions:** controlled HTTP server drops the first response or advertises a
  longer Content-Length then truncates it; the next response is valid. One public
  remote refresh/install succeeds, server evidence proves retry, and deployed
  bytes/commit match the independent fixture, with no partial-prefix corruption.
  Add a permanently broken-response control that terminates with failure and
  leaves existing deployment A unchanged.
- **Prerequisites:** fault-injecting server, clean caches and a confirmed public
  operation using the affected HTTP path. Upstream tests are helper-level, so
  first establish which metadata/OCI public path reaches this code; do not assume
  OSTree payload fetching necessarily uses Flatpak's curl wrapper. Avoid exact
  retry-count/timing assertions not promised by the public contract.

### 11. P1 — Instance IDs must be usable immediately, not only after app readiness

- **Upstream:** [PR #6864](https://github.com/flatpak/flatpak/pull/6864), merged
  **2026-10-10**, **unreleased default branch**. Writes PID before reporting
  `--instance-id-fd`; fixes portal NOTIFY_START and adds an end-to-end spawn test.
- **Suite partial coverage:** `sandbox_scenarios.py::_instance_descriptor` waits
  for the app's `ready` output **before** reading the instance descriptor, hiding
  an earlier unusable-ID window.
- **Assertions:** read a pipe carrying the instance ID as soon as the writer
  closes it, before releasing an app-side readiness barrier. Immediately create
  `FlatpakInstance` from that ID and query a valid PID/app identity; later `ps`
  agrees. Optional protocol test: a long-lived spawned child must emit
  `SpawnStarted`, then exit normally after the observer releases a FIFO barrier.
- **Prerequisites:** descriptor-pipe/barrier fixture and C libflatpak client;
  real private Flatpak portal for the optional extension. Do not require a
  start signal for a child that exits immediately: upstream explicitly permits
  missing notification for such short-lived children. Portal protocol coverage
  is outside current interface-count denominators, so label it separately.

### 12. P2 — Both user-font locations and search output normalization

- **Fonts upstream:** [PR #6883](https://github.com/flatpak/flatpak/pull/6883),
  merged **2026-10-12**, **unreleased**; implementation and `test-run.sh` verify
  simultaneous XDG and legacy mounts. **Gap:** no user-font assertion found.
  **Assert:** with both directories populated, distinct marker bytes are readable
  at `/run/host/user-fonts` and `/run/host/user-fonts-legacy`, both fontconfig remaps
  appear, and writes fail. With only `~/.fonts`, retain the historical
  `/run/host/user-fonts` mapping. **Prerequisites:** private HOME/XDG directories,
  runtime probe; marker files suffice for mount behavior, real font files are
  needed for a separate font-discovery assertion.
- **Search upstream:** [PR #6889](https://github.com/flatpak/flatpak/pull/6889),
  merged **2026-10-14**, **unreleased**; executable diff replaces CR/LF/TAB in
  AppStream summaries with spaces. **Gap:** `scenario-data/cli/search.json`
  covers search, not embedded control separators. **Assert:** a deliberately
  multiline/tabbed summary occupies one logical output row, with separators
  replaced by spaces, and neighboring app-ID/origin columns remain intact.
  **Prerequisites:** independently prepared AppStream input, fixed locale,
  noninteractive text output; do not assume JSON strings must use this table policy.

## Existing coverage: retain, run against recent targets, and strengthen selectively

| Upstream change | Evidence in this checkout | Assessment |
| --- | --- | --- |
| `flatpak_user_data_delete()`: [PR #6728](https://github.com/flatpak/flatpak/pull/6728), merged 2026-09-23; development 1.19.2 release notes | `scenario-data/library/user-data.json`, `permission_scenarios.py`, `library_features.py` | Already probes availability and tests cancellation, app-ID/path validation, deletion and permission reset without installation. Not a missing API scenario. |
| Transfer-rate API: [PR #6679](https://github.com/flatpak/flatpak/pull/6679), merged 2026-06-23; development 1.19.0 | `transaction.rate`, `client-transactions.c`, `transaction_scenarios.py`, `library_features.py` | Already feature-gated, with a paced transfer and assertions for initial zero and eventual positive rate. Not a missing scenario. Avoid imposing an exact timing-sensitive formula unless deliberately matching that version's contract. |
| Explicit bundle-key crash: [PR #6842](https://github.com/flatpak/flatpak/pull/6842), merged 2026-09-21; stable 1.18.3 | `bundle_trust_scenarios.py` checks explicit CLI `--gpg-file`; `lifecycle_extra_scenarios.py` and `client-lifecycle-extra.c` exercise `explicit-key` | Already tests both CLI and `flatpak_transaction_add_install_bundle()` with non-NULL `GBytes`, including transaction scope cleanup after success. An optional malformed/rejected-bundle variant could strengthen failure-path cleanup; do not duplicate the existing success case. |
| Redirect switches: development [1.19.2 notes](https://github.com/flatpak/flatpak/releases/tag/1.19.2), #6844 | `remote_metadata_option_scenarios.py` tests add/modify no-follow and explicit follow transitions against independent repositories | Already behavior-specific, not merely option parsing. Run on the prerelease target rather than proposing duplicates. |
| `document-export --noexist` crash: [PR #6847](https://github.com/flatpak/flatpak/pull/6847), merged 2026-09-25; development 1.19.2 | `document_scenarios.py`, `documents-noexist` | Existing real portal scenario verifies export without creating the origin file. |
| `run --clear-env` inversion: [1.19.0 notes](https://github.com/flatpak/flatpak/releases/tag/1.19.0), #6722 | `sandbox_scenarios.py`, `sandbox-clear-env` | Existing inherited-variable removal/explicit-variable retention assertion. Does not establish portal CLEAR_ENV + NOTIFY_START combinations. |
| File forwarding with nonstandard runtime path: [1.19.2 notes](https://github.com/flatpak/flatpak/releases/tag/1.19.2), #6848 | `sandbox-file-forwarding` starts private document portal under isolated runtime directory and checks rewritten arguments, read/write and restart revocation | Substantial overlap: verify the run's actual runtime path before calling this a gap. Empty paths (#6693, 1.18.1) and directory arguments (#6247, 1.17.0) remain useful additional variants. |
| Noninteractive ambiguity handling: [1.17.3 notes](https://github.com/flatpak/flatpak/releases/tag/1.17.3), #5754 | `cli_management_scenarios.py`, `management-update-ambiguous`; selection scenarios | Existing ambiguous-update failure, diagnostic candidates and unchanged commits. Inventory different refs/remotes/installations separately before adding redundant cases. |

## Follow-up backlog and uncertainty

- **Stable 1.18.2→1.18.3 build regression:** the
  [1.18.3 release](https://github.com/flatpak/flatpak/releases/tag/1.18.3)
  explicitly fixes builds with a system-installed runtime and SELinux (#6818).
  Add a matrix case with runtime/SDK installed **only system-wide**, then run
  user `build-init`/`build` and verify output and sandbox execution; add enforcing
  SELinux where available. Current build fixtures predominantly install user
  runtimes. The referenced PR endpoint returned 404 during research, so the
  precise minimum reproduction needs follow-up; the release claim itself is verified.
- **Subsandbox combinations:** stable 1.18.3/development 1.19.2 notes identify
  startup with `--no-talk-name`/`--system-no-talk-name` (#6776); 1.18.1 notes
  identify portal environment handling (#6721), and 1.18.2 notes identify
  `sandbox-expose-fd-ro` FD remapping (#6785). Existing bus/FD/clear-env tests are
  not the same as launching a real subsandbox with those combinations. Add an
  optional portal profile, checking child startup, inherited/cleared/explicit
  environment, exact FD bytes, and denied bus destinations. #6776's PR endpoint
  returned 404; use the release as the inclusion source until its detailed patch
  is located. Do not infer every portal feature is a libflatpak API obligation.
- **Anti-downgrade:** [GHSA-q4gr-vc25-57m5](https://github.com/flatpak/flatpak/security/advisories/GHSA-q4gr-vc25-57m5)
  (2026-08-11, 1.18.1) concerns helper ref removal bypass, whereas the suite's
  system selectors exercise requested downgrades under their configured policy.
  A denied-authorization active-user case should preserve deployed B despite
  attempts to remove the deployed ref and install older A; an explicitly
  authorized control may succeed. New development polkit actions are described
  in [1.19.0 notes](https://github.com/flatpak/flatpak/releases/tag/1.19.0) (#6669).
  This requires a genuine policy-aware multiuser session, not root-only execution.
- **Malformed inputs/extra-data:** [1.18.2 notes](https://github.com/flatpak/flatpak/releases/tag/1.18.2)
  identify GVariant summary validation (#6779). Add malformed/truncated summary
  cases asserting bounded failure/no crash and unchanged deployment, with a
  valid-summary control. The [extra-data traversal advisory](https://github.com/flatpak/flatpak/security/advisories/GHSA-fqx6-vh4p-42cg)
  (2026-08-11, 1.18.1) warrants invalid blob-name/symlink confinement cases;
  existing `build-finish-extra-data` only checks generated metadata. Separately,
  [1.16.6 notes](https://github.com/flatpak/flatpak/releases/tag/1.16.6) document
  legitimate extra-data without a runtime (#6587), a useful positive control.
- **New development output/cache features:** [1.19.2 notes](https://github.com/flatpak/flatpak/releases/tag/1.19.2)
  describe `list --bytes`, extra-data download estimates (#5947), and automatic
  AppStream refresh for `remote-info`/`remote-ls --updates` except `--cached`
  (#5974). No matching bytes assertion was found; existing AppStream tests use
  explicit refresh. Add A→B cache transitions, prove `--cached` makes no refresh
  request, and prove the default command refreshes before observing B. Estimate
  tests need actual extra-data fixtures and size-aware assertions, not merely
  the existing extra-data metadata test. #5947/#5974 PR endpoints returned 404;
  exact cache freshness/size-format contracts require patch/manual verification
  before locking down stronger assertions than the release notes promise.

The research phase did not execute target tests. No claim is made that these gaps
are current Flatpak defects. For implementation, start with repair pins and CLI
authentication (cheap, well-specified), OCI update listing and immediate instance
usability (fresh regression tests), then add isolated P0 canary profiles. Keep
expected security behavior independent of implementation details, and record
unsupported prerequisites rather than silently granting passing coverage.

## Implemented follow-up

The initial shortlist now has executable cases; see
[development: focused upstream regressions](development.md#focused-upstream-regressions)
for scenario names, fixture preparation and scope. Implemented checks cover repair
pins, export filtering, deployment `files/etc` and `export` traversal, process-group
isolation, CLI authentication interaction policy, immediate public instance
enumeration, and OCI update listings. This does not implement every item in the
broader research backlog above. In particular, system-helper/root-context canaries,
OCI credential confidentiality, automatic HTTP retries and optional portal protocol
profiles remain follow-up work.
