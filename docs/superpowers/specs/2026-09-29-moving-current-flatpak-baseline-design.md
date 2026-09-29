# Moving current Flatpak baseline

## Goal

Make the default compatibility target follow the latest upstream Flatpak `main`
branch. The configured current target must not be pinned to a release tag or
commit SHA. Preserve tagged release baselines as explicit, reproducible choices
and retain each run's resolved commit as evidence.

## Configuration and selection

- Change `ci/baselines.json` so `current` is the full branch ref
  `refs/heads/main`, not a commit hash.
- Keep the `baselines` collection for immutable tagged releases, including the
  newly added 1.18.4 and the retained 1.19.x and 1.18.3 entries.
- An omitted/manual `baseline` selection resolves to the moving current ref.
- A supplied version or exact commit selects its retained release-tag entry.
- The baseline CLI emits the ref for both selections, but emits no expected
  commit for the moving branch. The checkout step resolves its fetched branch
  once and records that commit for the run.

## CI behavior

- Pull-request and manually dispatched runs with no selected baseline test the
  moving current ref (`refs/heads/main`).
- Explicit release selections continue to fetch and verify their immutable tag
  against the configured peeled commit.
- Scheduled/default-branch coverage continues to run each retained release
  baseline and one moving `main` track. It must not schedule the current moving
  target twice.
- Reports and logs identify moving-branch results as the upstream track, with
  the resolved commit and reported Flatpak version captured from that run.

## History and UI

- Moving `main` results remain one `upstream` series across commit and version
  changes; do not assign them a fabricated release-baseline identity.
- Release results remain keyed by their exact commits and retain version labels.
- Update copy and tests so “current” means the moving branch selection, while
  “pinned baseline” means a retained release tag.
- Preserve compatibility with archived snapshots and existing release history.

## Validation

- Unit tests cover config validation for a branch ref and pinned release entries,
  default and explicit selector behavior, and CLI environment output.
- CI matrix tests/checks cover default moving-ref selection, explicit pinned tag
  selection, and no duplicate moving-main entry on scheduled coverage.
- Run the web checks and Python CI checks relevant to the changed workflow/config
  and documentation.

## Out of scope

- Automatically adding newly tagged releases to the retained baseline list.
- Changing which tagged releases are retained beyond the versions in the current
  PR.
