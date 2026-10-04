# CI and the coverage dashboard

## Test runs and failure policy

Pushes and pull requests run lint, type, and formatting checks, unit tests on
Python 3.10 and 3.14, and the full compatibility suite against upstream Flatpak
`main`. Default-branch pushes and daily scheduled runs also test configured tagged
releases. Scheduled runs start at 21:00 in the `Europe/Berlin` timezone.
The [workflows](../.github/workflows/) support manual runs from GitHub Actions.

Classified non-security scenario assertion failures remain visible but do not
fail CI when they are the only failures and the complete report passes integrity
and coverage verification. Authentication and sandbox assertions, setup,
prerequisite, unsupported-capability, cleanup, integrity, and reporting failures
still fail CI. Reports and diagnostic logs are uploaded even when a run fails.

## Baselines

The upstream track resolves `main` to an exact commit at checkout. Pinned release
baselines are configured in `ci/baselines.json` with their tag and peeled commit.
CI fetches the selected full ref once before building; tags must peel to the
configured commit. Manual runs accept a configured tag version or its exact
commit. Reports record the checked-out commit and reported Flatpak version.

Compare releases using the same suite revision. Release coverage and timing
histories stay separate from upstream `main`. Archived snapshots remain readable
after a baseline is removed from the active configuration.

## System helper and authorization

CI builds the system helper from the selected commit. After fixture preparation,
`ci/system_helper.py` provisions two ordinary users, a named system installation,
and scoped polkit rules on the disposable VM. Its probe checks the helper's
bus-owner PID, authorized installation, exact commits visible to both users, and
rejection of the second user's remote modification.

The helper stays available during the suite. Always-run cleanup stops it,
removes test users and the installation, and restores any previous polkit action
policy. Commands and helper output are included in uploaded logs. Provisioning
itself earns no behavior coverage.

The `multiuser-*` library cases reset the named installation for each case, use
distinct ordinary users, verify the loaded target library, and retain nested
command records and API-call traces. They test lifecycle, remote persistence,
and installation/transaction no-interaction behavior.

The runner compiles `fixture-polkit-agent.c` using `polkit-agent-1` development
files. This process registers for the exact client PID, records authorization
requests, and rejects them. Interactive controls must reach it; no-interaction
attempts must not. Every attempt must fail authorization and preserve state.
The fixture exits with its parent. Privileged bridge assertions under `ci/`
participate in the suite-definition fingerprint.

## Published results

The [dashboard](https://razzeee.github.io/flatpak-blackbox-tests/) keeps the latest
complete run for each UTC day in separate baseline tracks. Missing or unverified
runs create gaps. Snapshots persist on the `coverage-history` branch.

Select a run to filter outcomes or compare slow cases with an earlier run. Case
rows open timing histories. Select Failed or Setup error, then a case, to inspect
its failure message and command/API evidence. Diagnostics are bounded and label
truncation; the CI link leads to full report artifacts while they remain available.
Older snapshots may lack diagnostics.

Timings separate setup, execution, and cleanup. Setup includes state, adapter,
bus, and repository startup; cleanup includes shutdown and state deletion. Run
duration also includes shared preflight, client builds, and coverage accounting,
but excludes final report writes. Cases blocked by preflight have no timings.
The dashboard lists shared and unrecorded time separately.

When `GITHUB_STEP_SUMMARY` is set, the runner appends the summary there and saves
`job-summary.md` as its delivery marker. Write failures return failure after
saving reports. CI adds an unverified fallback if delivery fails or the runner
never runs.

## Local dashboard development

The TypeScript/React site uses TanStack Charts and needs Node 22.12+:

```sh
npm --prefix web ci
npm --prefix web run dev
```

Copy published `history.json` to `web/public/history.json` to preview real data.
