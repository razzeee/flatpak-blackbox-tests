# Moving current Flatpak baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make default compatibility runs build the latest upstream Flatpak `main` while keeping tagged release baselines selectable and reproducible.

**Architecture:** Store `refs/heads/main` as the current baseline ref, with release tags remaining in the pinned-baseline list. Model baseline resolution as either a moving upstream ref or a pinned release; CI resolves the branch to a commit once at checkout and records it in existing run provenance. Moving results use the existing upstream history track, avoiding a second moving-main series.

**Tech Stack:** GitHub Actions, TypeScript, Zod, Node.js test runner, Python unittest.

**Spec:** `docs/superpowers/specs/2026-09-29-moving-current-flatpak-baseline-design.md`

## Global Constraints

- The configured current target is `refs/heads/main`, not a release tag or commit SHA.
- Tagged release baselines remain explicit and immutable, with their peeled commits verified.
- Every moving-branch run records its resolved commit SHA and reported Flatpak version.
- Moving `main` results use the existing `upstream` history series; never fabricate a release baseline identity.
- Scheduled coverage runs each retained tagged baseline and exactly one moving `main` target.
- Preserve archived snapshots and existing release history.

## Review Focus

- Branch refs must not require an expected commit before checkout; test moving-branch checkout without `FLATPAK_REFERENCE_COMMIT` set.
- Annotated release tags still require matching peeled commits; retain and run the mismatch-rejection case.
- Empty selector must choose moving `refs/heads/main`; assert CLI output has no configured SHA/version.
- Explicit version and commit selectors must still resolve to retained tags; assert both selectors.
- Scheduled runs must not execute moving `main` twice; assert the generated matrix has one upstream entry.

---

### Task 1: Model moving and pinned baseline selections

**Files:**
- Modify: `ci/baselines.json`
- Modify: `web/src/baselines.ts`
- Modify: `web/scripts/baseline.ts`
- Test: `web/test/baselines.test.ts`

**Interfaces:**
- Produces `BaselineSelection = { kind: "upstream"; ref: string } | { kind: "pinned"; baseline: Baseline }`.
- `resolveBaseline(selector?: string): BaselineSelection` returns upstream for an empty selector and a pinned selection for a retained version or commit.
- Pinned `Baseline` continues to include `version`, `commit`, and tag `ref`.

- [ ] **Step 1: Add config and selector tests**

Update the config test to accept `current: "refs/heads/main"`, reject a SHA in `current`, require pinned entries to have tag refs, and retain unique pinned commit validation. Assert that `resolveBaseline()` returns `{ kind: "upstream", ref: "refs/heads/main" }`, while exact version and commit selectors return `{ kind: "pinned", baseline: latestPinnedBaseline }`.

- [ ] **Step 2: Run focused tests and verify they fail**

Run: `npm --prefix web test -- --test-name-pattern='baseline configuration|manual baseline selection'`
Expected: FAIL because the current schema and resolver only support a commit-pinned current baseline.

- [ ] **Step 3: Update config and baseline resolution**

Set `ci/baselines.json.current` to `refs/heads/main`. Keep 1.19.2, 1.19.1, 1.19.0, 1.18.4, and 1.18.3 in descending version order with exact tagged commits. In `web/src/baselines.ts`, validate current as a full `refs/heads/*` ref, remove the current-must-match-pinned-entry refinement, and define `resolveBaseline` with the union interface above. Retain a pinned latest-release export only for legacy pinned-snapshot inference; do not use it as the default selector.

- [ ] **Step 4: Emit environment for both selection types**

Update `web/scripts/baseline.ts`: always emit `FLATPAK_BASELINE_REF`; emit `FLATPAK_REFERENCE_COMMIT` and `FLATPAK_BASELINE_VERSION` only for `kind: "pinned"`. Validate emitted values before writing GitHub Actions environment lines.

- [ ] **Step 5: Test CLI output and pinned selection compatibility**

Extend `web/test/baselines.test.ts` to assert empty selection emits only `FLATPAK_BASELINE_REF=refs/heads/main`, and explicit version/commit selections emit the same pinned SHA, version, and tag ref as before. Keep unknown selector rejection coverage.

- [ ] **Step 6: Run web baseline tests**

Run: `npm --prefix web test -- --test-name-pattern='baseline configuration|manual baseline selection'`
Expected: PASS.

---

### Task 2: Route default CI runs to moving upstream main

**Files:**
- Modify: `.github/workflows/compatibility.yml`
- Modify: `web/package.json`
- Create: `web/scripts/matrix.mjs`
- Modify: `ci/compatibility.sh`
- Test: `web/test/baselines.test.ts`
- Test: `test_ci.py`

**Interfaces:**
- Matrix entries use `track: "upstream"` and `ref: "refs/heads/main"` for the default moving target.
- Matrix entries use `track: "pinned"` and `baseline: <commit>` for explicit release selection and scheduled release coverage.
- Checkout resolves moving branch refs to `FLATPAK_REFERENCE_COMMIT`; only tag refs require a preconfigured expected SHA.

- [ ] **Step 1: Add CI matrix and checkout tests**

Extend `web/test/baselines.test.ts` to cover default empty selection choosing upstream main, explicit release selectors choosing pinned entries, and scheduled matrix entries including all pinned commits plus one upstream entry. Update `test_ci.py` to run branch checkout without an expected commit and retain mismatched tag checkout rejection. Assert branch checkout records its resolved SHA and the matrix contains exactly one upstream entry.

- [ ] **Step 2: Run CI tests and verify new cases fail**

Run: `npm --prefix web test -- --test-name-pattern='compatibility matrix' && uv run --locked python -m unittest test_ci`
Expected: FAIL on new matrix/default-selection cases while existing tag checks continue to pass.

- [ ] **Step 3: Update matrix generation and selection steps**

Implement `web/scripts/matrix.mjs` as a dependency-free Node script so the matrix-preparation job can run before npm dependencies are installed. Test default, explicit-release, and publishing cases by executing that script from `web/test/baselines.test.ts`; add a package script for local runs. In `.github/workflows/compatibility.yml`, replace the inline generator with that script. Pass each matrix ref into the upstream selection step instead of hardcoding a separate value. Run the pinned selection step only for pinned matrix entries.

- [ ] **Step 4: Resolve moving refs once at checkout**

In `ci/compatibility.sh`, preserve the tag-ref guard requiring an expected SHA and rejection when its peeled commit differs. For `refs/heads/*`, do not require an expected SHA; after fetch, write the resolved commit to logs and `GITHUB_ENV` exactly as today. Build phases continue to require the SHA written by checkout.

- [ ] **Step 5: Run CI tests**

Run: `npm --prefix web test -- --test-name-pattern='compatibility matrix' && uv run --locked python -m unittest test_ci`
Expected: PASS.

---

### Task 3: Align history, UI, and guidance

**Files:**
- Modify: `web/src/targets.ts`
- Modify: `web/test/baselines.test.ts`
- Modify: `README.md`
- Modify: `.github/workflows/compatibility.yml` workflow-dispatch description

**Interfaces:**
- `targetOptions(history)` lists release pins by version and the existing `upstream` series; it does not label a pinned release as “current baseline.”
- Existing history snapshots with `track: "upstream"` remain compatible and group across changing target commits and versions.

- [ ] **Step 1: Update history and UI tests**

Update `web/test/baselines.test.ts` so the current release pin is not presented as the current baseline, the upstream option remains `Upstream main`, legacy known pinned commits still get version labels, and unknown pinned commits remain labelled `Pinned commit`.

- [ ] **Step 2: Run focused web tests and verify they fail**

Run: `npm --prefix web test -- --test-name-pattern='changing the active baseline|legacy snapshots|page defaults'`
Expected: FAIL because target option generation currently labels a release pin as the current baseline.

- [ ] **Step 3: Update history options and guidance**

Remove the active-current-release label from `web/src/targets.ts`; keep version labels for historical pinned commits and the existing upstream option. Update README baseline guidance to explain that default compatibility runs follow upstream `main`, while selected versions/commits run retained immutable tag baselines. Update the workflow-dispatch description to say blank uses latest upstream main.

- [ ] **Step 4: Run web checks**

Run: `npm --prefix web test && npm --prefix web run check`
Expected: tests, TypeScript, and Prettier checks pass.

- [ ] **Step 5: Run Python project checks**

Run: `uv sync --locked && uv run --locked ruff check . && uv run --locked ty check . && uv run --locked mypy && uv run --locked python format_json.py --check && uv run --locked python -m unittest discover -p 'test_*.py'`
Expected: all checks pass.

- [ ] **Step 6: Review final diff and update the existing PR**

Inspect `git diff`, ensure the config has no current commit SHA, and confirm the PR description reflects the moving `main` default and release-pin options. Push the branch and update PR #35.
