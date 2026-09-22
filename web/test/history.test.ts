// SPDX-License-Identifier: LGPL-2.1-or-later
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import {
  chartRows,
  credit,
  daily,
  historySchema,
  snapshotSchema,
  utcDay,
  type Snapshot,
  type CaseTiming,
} from "../src/history.ts";
import { record } from "../scripts/record.ts";
import { currentBaseline } from "../src/baselines.ts";
import { completeEntry, entry, timedEntry } from "./fixtures.ts";

test("latest complete UTC-day run wins, including out-of-order reruns", () => {
  const early = entry();
  const later = entry("2026-09-17T22:00:00Z");
  const interrupted = { ...entry("2026-09-17T23:00:00Z"), complete: false };
  for (const values of [
    [early, later, interrupted],
    [interrupted, later, early],
  ]) {
    const history = values.reduce<Snapshot[]>(
      (items, value) => daily(items, value),
      [],
    );
    assert.deepEqual(history, [later]);
    assert.deepEqual(daily(history, later), history);
  }
  assert.deepEqual(daily([], interrupted), [interrupted]);
});

test("UTC day boundaries and tracks remain independent", () => {
  const early = entry("2026-09-18T00:30:00+02:00");
  const later = entry("2026-09-17T23:00:00Z");
  const upstream = entry(undefined, "upstream");
  assert.deepEqual(daily([early, upstream], later), [later, upstream]);
  assert.equal(utcDay("2026-01-01T00:30:00+02:00"), "2025-12-31");
  assert.throws(() => utcDay("2026-09-17T21:00:00"));
  assert.throws(() => utcDay("2026-02-30T21:00:00Z"));
});

test("unverified evidence and empty denominators are gaps, zero passes are data", () => {
  for (const verification of [
    "stale",
    "incomplete",
    "invalid",
    "not-run",
    "unversioned",
  ] as const) {
    assert.equal(credit({ ...entry(), verification }, "cli"), null);
  }
  assert.equal(credit({ ...entry(), complete: false }, "cli"), null);
  const value = entry();
  value.metrics.cli!.total = 0;
  assert.equal(credit(value, "cli"), null);
  value.metrics.cli!.total = 20;
  value.metrics.cli!.passed = 0;
  assert.deepEqual(credit(value, "cli"), { passed: 0, total: 20, percent: 0 });
  value.metrics.cli!.passed = 8;
  assert.equal(credit(value, "cli")?.percent, 40);
});

test("schema rejects invalid input and accepts original Python snapshot timestamps", () => {
  assert.equal(
    snapshotSchema.parse(entry("2026-09-17T21:00:00.123456+00:00")).schema,
    1,
  );
  assert.throws(() => snapshotSchema.parse({ ...entry(), schema: true }));
  assert.throws(() =>
    snapshotSchema.parse({ ...entry(), track: "pull-request" }),
  );
  assert.throws(() => historySchema.parse({ entries: [] }));
  const value = entry();
  value.metrics.cli!.passed = 11;
  assert.throws(() => snapshotSchema.parse(value));
});

test("missing days and unverified days produce explicit null chart rows", () => {
  const first = entry();
  const unverified = {
    ...entry("2026-09-18T21:00:00Z"),
    verification: "stale" as const,
  };
  const last = entry("2026-09-20T21:00:00Z");
  const rows = chartRows([last, first, unverified], "cli");
  assert.deepEqual(
    rows.map((row) => row.percent),
    [80, null, null, 80],
  );
  assert.equal(rows[3]!.day - rows[0]!.day, 3);
  assert.deepEqual(chartRows([], "cli"), []);
});

test("snapshot CLI handles absent reports and update preserves existing history", async (context) => {
  const root = await mkdtemp(join(tmpdir(), "coverage-history-"));
  context.after(() => rm(root, { recursive: true, force: true }));
  const cli = fileURLToPath(new URL("../scripts/history.ts", import.meta.url));
  const snapshot = join(root, "snapshot.json");
  const history = join(root, "history.json");
  execFileSync(process.execPath, [
    "--import",
    "tsx",
    cli,
    "record",
    "--report",
    join(root, "missing.json"),
    "--track",
    "pinned",
    "--timestamp",
    "2026-09-17T21:00:00Z",
    "--suite-commit",
    "suite",
    "--target-commit",
    currentBaseline.commit,
    "--run-url",
    "https://github.com/example/suite/actions/runs/1",
    "--output",
    snapshot,
  ]);
  const gap = snapshotSchema.parse(
    JSON.parse(await readFile(snapshot, "utf8")),
  );
  assert.equal(gap.complete, false);
  assert.equal(gap.verification, "not-run");
  const retained = completeEntry(entry().timestamp, [
    ...timedEntry().performance!.cases,
    {
      behavior_id: "skipped",
      driver: "cli",
      profile: "user",
      status: "not-selected",
    },
    {
      behavior_id: "unsupported",
      driver: "library",
      profile: "system",
      status: "unsupported",
    },
  ]);
  retained.performance!.cases[1]!.failure_details = {
    error: "Previously recorded failure",
    evidence: [],
    truncated: false,
  };
  for (const value of [gap, entry(), entry(undefined, "upstream"), retained]) {
    await writeFile(snapshot, JSON.stringify(value));
    execFileSync(process.execPath, [
      "--import",
      "tsx",
      cli,
      "update",
      "--snapshot",
      snapshot,
      "--history",
      history,
    ]);
  }
  const saved = await readFile(history, "utf8");
  assert.deepEqual(historySchema.parse(JSON.parse(saved)), [
    retained,
    entry(undefined, "upstream"),
  ]);
  await writeFile(snapshot, "broken JSON");
  const failure = spawnSync(
    process.execPath,
    [
      "--import",
      "tsx",
      cli,
      "update",
      "--snapshot",
      snapshot,
      "--history",
      history,
    ],
    { encoding: "utf8" },
  );
  assert.equal(failure.status, 1);
  assert.equal(await readFile(history, "utf8"), saved);
  await writeFile(snapshot, JSON.stringify(entry()));
  await writeFile(history, "null");
  const invalidHistory = spawnSync(
    process.execPath,
    [
      "--import",
      "tsx",
      cli,
      "update",
      "--snapshot",
      snapshot,
      "--history",
      history,
    ],
    { encoding: "utf8" },
  );
  assert.equal(invalidHistory.status, 1);
  assert.equal(await readFile(history, "utf8"), "null");
});

test("Python accounting accepts completed failed runs but rejects stale definitions", async (context) => {
  const root = await mkdtemp(join(tmpdir(), "coverage-engine-"));
  context.after(() => rm(root, { recursive: true, force: true }));
  const reportPath = join(root, "report.json");
  const suite = fileURLToPath(new URL("../../", import.meta.url));
  const report = JSON.parse(
    execFileSync(
      "python3",
      [
        "-c",
        `
import json
from pathlib import Path
from coverage_report import CoverageModel
model = CoverageModel(Path.cwd())
print(json.dumps({
    "schema": 1, "complete": True, "coverage_definition": model.definition,
    "finished_at": "2026-09-17T22:00:00Z",
    "results": [{"behavior_id": behavior, "driver": driver, "profile": profile,
                 "status": "failed"} for behavior, driver, profile in model.cases],
}))
`,
      ],
      { cwd: suite, encoding: "utf8" },
    ),
  ) as {
    coverage_definition: { fingerprint: string };
    complete: boolean;
    target_version?: string;
    duration_seconds?: number;
    results: (CaseTiming & {
      error?: string;
      evidence?: { stderr: string }[];
    })[];
  };
  await writeFile(reportPath, JSON.stringify(report));
  const options = {
    report: reportPath,
    track: "pinned" as const,
    timestamp: "2026-09-18T01:00:00Z",
    suiteCommit: "suite",
    targetCommit: currentBaseline.commit,
    runUrl: "https://github.com/example/suite",
  };
  const value = await record(options);
  assert.equal(value.verification, "current");
  assert.equal(value.timestamp, "2026-09-17T22:00:00.000Z");
  assert.deepEqual(credit(value, "cli"), { passed: 0, total: 136, percent: 0 });
  assert.equal(value.performance?.duration_seconds, undefined);
  assert.equal(value.performance?.cases.length, report.results.length);
  assert.equal(value.performance?.cases_complete, true);
  assert.deepEqual(value.baseline, currentBaseline);
  assert.equal(value.target_version, undefined);
  report.target_version = `Flatpak ${currentBaseline.version}`;
  report.duration_seconds = 450;
  for (const result of report.results) {
    result.duration_seconds = 1;
    result.timings = {
      setup_seconds: 0.1,
      execution_seconds: 0.7,
      cleanup_seconds: 0.2,
    };
  }
  report.results[0]!.status = "not-selected";
  report.results[1]!.status = "unsupported";
  report.results[2]!.status = "setup-error";
  report.results[2]!.error = "Fixture preparation failed";
  report.results[3]!.error = "Expected installed ref";
  report.results[3]!.evidence = [{ stderr: "Remote unavailable" }];
  delete report.results[2]!.duration_seconds;
  delete report.results[2]!.timings;
  await writeFile(reportPath, JSON.stringify(report));
  const timed = await record(options);
  assert.equal(timed.target_version, report.target_version);
  assert.equal(timed.performance?.duration_seconds, 450);
  assert.equal(timed.performance?.cases.length, report.results.length);
  assert.equal(timed.performance?.cases_complete, true);
  assert.equal(
    timed.performance?.cases[3]?.failure_details?.error,
    "Expected installed ref",
  );
  assert.equal(
    timed.performance?.cases[3]?.failure_details?.evidence[0]?.body,
    "Remote unavailable",
  );
  assert.equal(
    timed.performance?.cases[2]?.failure_details?.error,
    "Fixture preparation failed",
  );
  assert.equal(timed.performance?.cases[0]?.status, "not-selected");
  assert.equal(timed.performance?.cases[1]?.status, "unsupported");
  assert.equal(timed.performance?.cases[2]?.status, "setup-error");
  assert.deepEqual(timed.performance?.case_statuses, {
    "not-selected": 1,
    unsupported: 1,
    "setup-error": 1,
    failed: report.results.length - 3,
  });
  report.target_version = "Flatpak 0.0.0";
  await writeFile(reportPath, JSON.stringify(report));
  await assert.rejects(record(options), /does not match baseline/);
  const upstream = await record({
    ...options,
    track: "upstream",
    targetCommit: "c".repeat(40),
  });
  assert.equal(upstream.baseline, undefined);
  assert.equal(upstream.target_version, "Flatpak 0.0.0");
  await assert.rejects(
    record({ ...options, targetCommit: "c".repeat(40) }),
    /Unknown pinned commit/,
  );
  report.target_version = `Flatpak ${currentBaseline.version}`;
  report.complete = false;
  await writeFile(reportPath, JSON.stringify(report));
  assert.equal((await record(options)).performance, undefined);
  report.complete = true;
  report.coverage_definition.fingerprint = "stale";
  await writeFile(reportPath, JSON.stringify(report));
  const stale = await record(options);
  assert.equal(stale.verification, "stale");
  assert.equal(credit(stale, "cli"), null);
  assert.equal(stale.performance, undefined);
  await writeFile(reportPath, "invalid JSON");
  await assert.rejects(record(options));
});
