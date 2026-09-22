// SPDX-License-Identifier: LGPL-2.1-or-later
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { correctSnapshot } from "../scripts/corrections.ts";
import { snapshotSchema, type CaseTiming } from "../src/history.ts";
import { entry } from "./fixtures.ts";

function blockedCase(): CaseTiming {
  return {
    behavior_id: "lifecycle.user",
    driver: "library",
    profile: "user",
    status: "failed",
    failure_details: {
      error:
        "public library client did not compile: implicit declaration of function",
      evidence: [],
      truncated: false,
    },
  };
}

function snapshot(cases: CaseTiming[] = [blockedCase()]) {
  const counts: Record<string, number> = {};
  for (const item of cases)
    counts[item.status] = (counts[item.status] ?? 0) + 1;
  return snapshotSchema.parse({
    ...entry(),
    performance: { cases, case_statuses: counts, cases_complete: true },
  });
}

test("build-error correction preserves provenance, diagnostics and coverage", () => {
  const original = snapshot();
  const corrected = correctSnapshot(original);
  assert.equal(original.performance!.cases[0]!.status, "failed");
  assert.equal(corrected.performance!.cases[0]!.status, "setup-error");
  assert.deepEqual(corrected.performance!.case_statuses, { "setup-error": 1 });
  assert.deepEqual(
    corrected.performance!.cases[0]!.failure_details,
    original.performance!.cases[0]!.failure_details,
  );
  assert.deepEqual(corrected.metrics, original.metrics);
  assert.equal(corrected.timestamp, original.timestamp);
  assert.equal(corrected.suite_commit, original.suite_commit);
  assert.equal(corrected.target_commit, original.target_commit);
  assert.equal(corrected.fingerprint, original.fingerprint);
  assert.equal(corrected.run_url, original.run_url);
  assert.deepEqual(corrected.corrections, [
    {
      id: "library-client-build-setup-error-v1",
      changed_cases: 1,
    },
  ]);
  assert.deepEqual(correctSnapshot(corrected), corrected);
  snapshotSchema.parse(corrected);
});

test("correction needs positive build-failure evidence and no case execution", () => {
  const examples: CaseTiming[] = [
    { ...blockedCase(), driver: "cli" },
    { ...blockedCase(), status: "passed" },
    { ...blockedCase(), duration_seconds: 0 },
    {
      ...blockedCase(),
      timings: { setup_seconds: 0, execution_seconds: 0, cleanup_seconds: 0 },
    },
    { ...blockedCase(), failure_details: undefined },
    {
      ...blockedCase(),
      failure_details: {
        error: "library operation failed",
        evidence: [],
        truncated: false,
      },
    },
    {
      ...blockedCase(),
      failure_details: {
        ...blockedCase().failure_details!,
        evidence: [{ title: "Command", body: "client install" }],
      },
    },
  ];
  for (const item of examples) {
    const original = snapshot([item]);
    assert.deepEqual(correctSnapshot(original), original);
  }
  // Incomplete inventories retain counts for cases absent from the snapshot.
  const partial = snapshot();
  partial.performance!.cases_complete = false;
  partial.performance!.case_statuses = {
    failed: 10,
    passed: 8,
    "setup-error": 2,
  };
  assert.deepEqual(correctSnapshot(partial).performance!.case_statuses, {
    failed: 9,
    passed: 8,
    "setup-error": 3,
  });
});

test("migration CLI is idempotent and update cannot restore old labels", async (context) => {
  const root = await mkdtemp(join(tmpdir(), "history-correction-"));
  context.after(() => rm(root, { recursive: true, force: true }));
  const cli = fileURLToPath(new URL("../scripts/history.ts", import.meta.url));
  const history = join(root, "history.json");
  const incoming = join(root, "snapshot.json");
  await writeFile(history, JSON.stringify([snapshot()]));
  await writeFile(incoming, JSON.stringify(snapshot()));
  const run = (...args: string[]) =>
    execFileSync(process.execPath, ["--import", "tsx", cli, ...args], {
      encoding: "utf8",
    });
  run("migrate", "--history", history);
  const corrected = await readFile(history, "utf8");
  run("migrate", "--history", history);
  assert.equal(await readFile(history, "utf8"), corrected);
  run("update", "--snapshot", incoming, "--history", history);
  assert.deepEqual(
    JSON.parse(await readFile(history, "utf8")),
    JSON.parse(corrected),
  );
  assert.equal(
    JSON.parse(corrected)[0].performance.cases[0].status,
    "setup-error",
  );
});
