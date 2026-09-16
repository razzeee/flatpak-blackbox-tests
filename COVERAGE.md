# What the coverage percentages mean

This suite reports separate measurements for catalogued behavior and public
interface reach. It does not report a percentage of all possible Flatpak behavior.
The latter has no defensible finite denominator yet.

## Measured checkpoint

A complete run against reference Flatpak 1.19.1 on 2026-09-15 produced 304 passing
cases and 16 failing checks. The current-definition report is
`_build/blackbox-artifacts/tx-contract-reviewed-full-01/report.json`, relative to the
checkout root. Its passing evidence covers:

| Measurement | Passing credit | Percentage |
| --- | ---: | ---: |
| Catalogued CLI behavior | 115 / 136 obligations | 84.56% |
| Catalogued library behavior | 143 / 163 obligations | 87.73% |
| CLI command reach | 38 / 44 commands | 86.36% |
| Documented CLI option reach | 385 / 624 options | 61.70% |
| Public library function reach | 182 / 223 functions | 81.61% |
| Public library signal reach | 13 / 14 signals | 92.86% |

There are 121 mapped CLI obligations and 148 mapped library obligations; failures
do not receive passing credit. Twenty-two of the 28 explicit system obligations
have passing evidence from isolated selector, preinstall, environment, and repair
privilege checks. Polkit, non-root system-helper and multiple-user contracts
remain uncovered. This checkpoint is not a substitute for running the accounting
against the report for the target and definitions being evaluated.

The 320-case run used the uncommitted suite changes based on
`e66397758f357b91977318b882dd245368e0a6eb`, target configuration
`/tmp/opencode/flatpak-blackbox-build-target.json`, and fully regenerated fixtures
at `_build/blackbox-artifacts/tx-contract-fixtures-01`. It ran with `--timeout 90`
and `TMPDIR=/home/razze/dev/flatpak/_build/t`. Recorded SHA-256 values:

| Input | SHA-256 |
| --- | --- |
| Suite definition fingerprint | `3a48115c8a5d9b7593e787b405d878744c4f2f944ed2eed6fc4a79d15b376d02` |
| Target configuration | `f3fbbf138daa37ef617632b3933f26f45f5fca9527e56d64a13271ed3a2cb97a` |
| Target CLI | `9e00add5910406853422eab296cc40ec90ba0439f5fea9564a8fba7fd09a90f2` |
| Target libflatpak | `d8ecbe648ea28869fa0e78a74b2c48b86dffd95123cb8015c530e630e70801e2` |
| Fixture manifest | `9232a74de3d6aaaf1daefadf8a9f02c7c455e5f0eb4403ec91d78be59931864b` |

The seven new transaction cases pass both focused runs and the full run. No new
reference failures appeared; the existing 16 failed checks retain no credit.

### Transaction contract review

`scenario-data/transaction-contracts.json` maps exactly seven existing library
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

From `tests/blackbox`:

```sh
# Tests mapped to obligations, without claiming they have passed:
python3 coverage_report.py

# Passing evidence from a specific, completed execution:
python3 coverage_report.py --report /path/to/results/report.json

# Include individual evidence, uncovered IDs, categories, profiles and limitations:
python3 coverage_report.py --report /path/to/results/report.json --json

# In the reference source checkout, detect source/interface drift:
python3 catalogue.py --source-root ../.. --output coverage-data/surfaces.json --check
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
| CLI behavior | 136 | One curated, described CLI outcome, with its installation profile and source references |
| Library behavior | 163 | One curated, described public libflatpak outcome, with its profile and source references |
| CLI command reach | 44 | One active canonical command registered by the reference CLI |
| CLI option reach | 624 | One distinct documented long option for a particular command, or for the global invocation |
| Library function reach | 223 | One explicit public callable declaration, including deprecated APIs, excluding type-registration plumbing |
| Library signal reach | 14 | One documented and registered signal belonging to a public libflatpak type |

The 299 behavior obligations are an initial curated catalogue. Their granularity
varies, and they are not weighted by complexity, risk, or usage. The files record
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
explicit CLI-option assertions. The latter require a specific observable effect
and a rationale, and cannot add command, function, or behavior-obligation credit.
They allow option testing to expand without redefining the 299-row behavior
denominator. Help tests cover only their help option, not the command's main work.
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
checks from executing. No undocumented ordering quirk has been silently accepted
as the compatibility contract.

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

All six new cases pass, covering the callback contract, search, explicit
AppStream refresh, extensionless bundle format selection, runtime-based app
filtering, and effective locale selection after config unset.

## Other unverified checks and remaining gaps

The complete run also retained failures for build-directory `/var` and empty-var
contracts, writable SDK/base initialization under the host's SELinux-xattr
restrictions, clearing inherited environment, `enter` output, named-installation
override isolation, related-ref enumeration, instance child-process identity,
unreachable-installation enumeration, and a documented nullable rebase argument.
Document forwarding, explicitly keyed bundle installation, and the native
collection-ID sideload-query variant also remain failed checks in this run.
These observations need individual triage; failed assertions are not automatically
proof of implementation defects. None earns passing credit.

Non-root system-helper authorization, polkit, multiple users, authenticator
installation, document-portal workflows, repair recovery, and remaining
device/feature combinations need further work. Permission-store workflows use a
real isolated service, and history uses a private real journal. Root repair and
non-root refusal are compared against the same private populated installation;
this does not establish polkit authorization. Local-ref cleanup/prune partial
checks are retained without full credit because object retention/reclamation is
not established through public observations. The JSON report lists unmapped
obligations and the case evidence for credited interfaces.
