# What coverage means

Coverage measures the suite's catalogued requirements and public interfaces.
It is not a percentage of all possible Flatpak behavior. Current numbers and
failures belong in [the dashboard](https://razzeee.github.io/flatpak-blackbox-tests/)
and each run's generated `coverage.md` and `report.json`.

## Measurements

| Measurement | What it counts |
| --- | --- |
| CLI and library behavior | Selected, documented outcomes in the requirement catalogue |
| CLI command reach | Canonical commands with mapped behavior checks |
| CLI option reach | Command-specific long options with assertions of their effects |
| Library function reach | Public functions with relevant assertions and recorded calls |
| Library signal reach | Public signals with relevant assertions and recorded emissions |

Option inventory accounting also includes **equivalence checks**. These verify
ordinary results with a default-equivalent or context-inapplicable option present,
without proving a distinct option effect. Reports show them separately from
option-specific assertions. Accounting for every option does not mean every
option's behavior is tested.

## Implemented versus passing

- **Implemented** means a case is explicitly mapped to a requirement or interface
  assertion. It does not mean the case has passed.
- **Passing evidence** means the mapped case passed, including cleanup, in a
  complete, verified run matching the suite definitions.

A failed case earns no passing credit, even if earlier assertions succeeded.
Unsupported, unselected, and unimplemented requirements stay in the denominator.
Multiple passing cases for the same requirement earn no duplicate credit.
Setup commands and call traces alone do not establish coverage.

Reports record suite, target, and fixture provenance. Changes to the tests or
definitions make saved reports stale for current coverage. Interrupted runs or
reports with missing evidence cannot earn verified passing credit.

## Limits

Behavior requirements vary in scope and are not weighted by complexity or usage.
Interface reach does not establish every argument value, option combination,
precedence rule, or repeated-option behavior. User-only runs cannot establish
system-profile requirements.

The interface catalogue counts command-specific long options separately. It
excludes command and short-option aliases, type-registration plumbing, private
APIs, inherited GLib signals, and standalone executables. D-Bus protocols,
environment variables, and file formats are outside the interface counts, even
when individual behavior cases test their effects.

Compare percentages alongside their catalogue revisions. Different denominators
may make percentages incomparable. A reference failure can also come from the
test or environment; a failed run alone does not establish a Flatpak bug.

## Inspect the accounting

```sh
# Implemented mappings, without execution evidence:
python3 coverage_report.py

# Passing evidence from a completed run:
python3 coverage_report.py --report /path/to/results/report.json

# Individual evidence, uncovered IDs, profiles, and limitations:
python3 coverage_report.py --report /path/to/results/report.json --json
```

Exit status 0 from the coverage reporter means the accounting is valid, not that
all target tests passed. The runner reports test failures separately.

Requirements and mappings live in [`coverage-data/`](coverage-data/) and
[`scenario-data/`](scenario-data/). See [development](docs/development.md) for
mapping rules and checking the interface catalogue against a Flatpak checkout.
