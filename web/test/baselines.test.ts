// SPDX-License-Identifier: LGPL-2.1-or-later
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { App } from "../src/App.tsx";
import {
  baselineConfig,
  baselineConfigSchema,
  latestPinnedBaseline,
  resolveBaseline,
  type Baseline,
} from "../src/baselines.ts";
import {
  daily,
  historySchema,
  snapshotSchema,
  type Snapshot,
} from "../src/history.ts";
import {
  baselineKey,
  targetKey,
  targetOptions,
  withBaseline,
} from "../src/targets.ts";
import { entry, timedEntry } from "./fixtures.ts";

const nextBaseline: Baseline = {
  version: "1.20.0",
  commit: "c".repeat(40),
  ref: "refs/tags/1.20.0",
};

function forBaseline(baseline: Baseline, timestamp?: string): Snapshot {
  return {
    ...timedEntry(timestamp),
    baseline,
    target_commit: baseline.commit,
    target_version: `Flatpak ${baseline.version}`,
  };
}

function compatibilityMatrix(input: {
  eventName: string;
  ref: string;
  defaultBranch: string;
  selector: string;
}) {
  const output = execFileSync(
    process.execPath,
    [fileURLToPath(new URL("../scripts/matrix.mjs", import.meta.url))],
    {
      encoding: "utf8",
      env: {
        ...process.env,
        EVENT_NAME: input.eventName,
        REF: input.ref,
        DEFAULT_BRANCH: input.defaultBranch,
        BASELINE: input.selector,
      },
    },
  );
  return JSON.parse(output.slice("matrix=".length)).include as Array<{
    track: "pinned" | "upstream";
    baseline: string;
    ref: string;
  }>;
}

test("baseline configuration requires a moving current ref and unique safe definitions", () => {
  assert.deepEqual(baselineConfigSchema.parse(baselineConfig), baselineConfig);
  assert.throws(() =>
    baselineConfigSchema.parse({ ...baselineConfig, current: "f".repeat(40) }),
  );
  assert.throws(() =>
    baselineConfigSchema.parse({
      ...baselineConfig,
      baselines: [latestPinnedBaseline, latestPinnedBaseline],
    }),
  );
  assert.throws(() =>
    baselineConfigSchema.parse({
      ...baselineConfig,
      baselines: [{ ...latestPinnedBaseline, version: "1.19.1\nENV=bad" }],
    }),
  );
  assert.throws(() =>
    baselineConfigSchema.parse({
      ...baselineConfig,
      baselines: [
        { version: nextBaseline.version, commit: nextBaseline.commit },
      ],
    }),
  );
  assert.equal(
    baselineConfigSchema.parse({
      ...baselineConfig,
      current: "refs/heads/main",
    }).current,
    "refs/heads/main",
  );
});

test("manual baseline selection resolves current branch, release version and exact commit", () => {
  assert.deepEqual(resolveBaseline(), {
    kind: "upstream",
    ref: "refs/heads/main",
  });
  assert.deepEqual(resolveBaseline(latestPinnedBaseline.version), {
    kind: "pinned",
    baseline: latestPinnedBaseline,
  });
  assert.deepEqual(resolveBaseline(latestPinnedBaseline.commit), {
    kind: "pinned",
    baseline: latestPinnedBaseline,
  });
  assert.throws(() => resolveBaseline("does-not-exist"), /Unknown baseline/);
  const cli = fileURLToPath(new URL("../scripts/baseline.ts", import.meta.url));
  const output = execFileSync(process.execPath, ["--import", "tsx", cli], {
    encoding: "utf8",
  });
  assert.equal(output, "FLATPAK_BASELINE_REF=refs/heads/main\n");
  const pinnedOutput = execFileSync(
    process.execPath,
    ["--import", "tsx", cli, "--baseline", latestPinnedBaseline.version],
    { encoding: "utf8" },
  );
  assert.equal(
    pinnedOutput,
    `FLATPAK_REFERENCE_COMMIT=${latestPinnedBaseline.commit}\nFLATPAK_BASELINE_VERSION=${latestPinnedBaseline.version}\nFLATPAK_BASELINE_REF=${latestPinnedBaseline.ref}\n`,
  );
  const invalid = spawnSync(
    process.execPath,
    ["--import", "tsx", cli, "--baseline", "missing"],
    { encoding: "utf8" },
  );
  assert.equal(invalid.status, 1);
  assert.equal(invalid.stdout, "");
});

test("compatibility matrix defaults to one moving main track and retains pinned choices", () => {
  const pullRequest = compatibilityMatrix({
    eventName: "pull_request",
    ref: "refs/pull/35/merge",
    defaultBranch: "main",
    selector: "",
  });
  assert.deepEqual(pullRequest, [
    { track: "upstream", baseline: "", ref: "refs/heads/main" },
  ]);

  const selectedRelease = compatibilityMatrix({
    eventName: "workflow_dispatch",
    ref: "refs/heads/main",
    defaultBranch: "main",
    selector: "1.18.4",
  });
  assert.deepEqual(selectedRelease, [
    {
      track: "pinned",
      baseline: "a02d0ba48abe9aacc377de15699e5d8c024b5669",
      ref: "refs/tags/1.18.4",
    },
  ]);

  const scheduled = compatibilityMatrix({
    eventName: "schedule",
    ref: "refs/heads/main",
    defaultBranch: "main",
    selector: "",
  });
  assert.equal(
    scheduled.filter((entry) => entry.track === "upstream").length,
    1,
  );
  assert.equal(scheduled.length, baselineConfig.baselines.length + 1);
  assert.ok(
    scheduled.some((entry) => entry.baseline === latestPinnedBaseline.commit),
  );
});

test("two baselines on the same UTC day preserve coverage and performance independently", () => {
  const old = forBaseline(latestPinnedBaseline);
  const next = forBaseline(nextBaseline);
  next.metrics.cli!.passed = 4;
  next.performance!.duration_seconds = 900;
  const latestNext = { ...next, timestamp: "2026-09-17T23:00:00Z" };
  const selected = daily([old, next], latestNext);
  assert.equal(selected.length, 2);
  assert.deepEqual(
    selected.find(
      (item) => targetKey(item) === baselineKey(latestPinnedBaseline),
    ),
    old,
  );
  assert.deepEqual(
    selected.find((item) => targetKey(item) === baselineKey(nextBaseline)),
    latestNext,
  );
  assert.equal(
    selected.find((item) => item.baseline?.version === "1.20.0")?.performance
      ?.duration_seconds,
    900,
  );
  assert.equal(
    selected.find((item) => item.baseline?.version === "1.20.0")?.metrics.cli
      ?.passed,
    4,
  );
  const repin = forBaseline({
    ...latestPinnedBaseline,
    commit: "d".repeat(40),
  });
  assert.equal(daily([old], repin).length, 2);
});

test("upstream main stays a moving series across source and version changes", () => {
  const early = {
    ...entry(undefined, "upstream"),
    target_version: "Flatpak 1.19.1",
  };
  const later = {
    ...entry("2026-09-17T23:00:00Z", "upstream"),
    target_commit: "d".repeat(40),
    target_version: "Flatpak 1.99.0",
  };
  assert.deepEqual(daily([early], later), [later]);
  assert.equal(targetKey(early), targetKey(later));
});

test("legacy snapshots infer only known pins and retain their original evidence", () => {
  const legacy = entry();
  delete legacy.baseline;
  delete legacy.target_version;
  assert.equal(snapshotSchema.parse(legacy).baseline, undefined);
  const inferred = withBaseline(legacy);
  assert.deepEqual(inferred.baseline, latestPinnedBaseline);
  assert.equal(inferred.target_version, undefined);
  assert.deepEqual(inferred.metrics, legacy.metrics);
  assert.equal(inferred.fingerprint, legacy.fingerprint);
  assert.equal(targetKey(inferred), targetKey(legacy));
  const unknown = { ...legacy, target_commit: "e".repeat(40) };
  assert.equal(withBaseline(unknown).baseline, undefined);
  const options = targetOptions([unknown]);
  assert.match(
    options.find((item) => item.key === targetKey(unknown))!.label,
    /Pinned commit/,
  );
  const upstream = { ...legacy, track: "upstream" as const };
  assert.equal(withBaseline(upstream).baseline, undefined);
});

test("target choices label pinned releases and keep moving main separate", () => {
  const old = entry();
  delete old.baseline;
  const next = forBaseline(nextBaseline);
  const options = targetOptions([old, next]);
  assert.ok(
    options.some((item) => item.key === baselineKey(latestPinnedBaseline)),
  );
  assert.ok(
    options
      .find((item) => item.key === targetKey(old))!
      .label.includes(latestPinnedBaseline.version),
  );
  assert.match(
    options.find((item) => item.key === baselineKey(nextBaseline))!.label,
    /1.20.0/,
  );
  assert.equal(options.at(-1)!.key, "upstream");
  assert.equal(options.at(-1)!.label, "Upstream main");
  const oldUnknown = { ...next };
  delete oldUnknown.baseline;
  assert.match(
    targetOptions([oldUnknown, next]).find(
      (item) => item.key === targetKey(next),
    )!.label,
    /1.20.0/,
  );
});

test("archived baselines without refs remain readable after an upgrade", () => {
  const archived = {
    version: "1.17.9",
    commit: "1a6ec6a1f720fb30d76c76e656ac624fcaa237e9",
  };
  const snapshot = forBaseline(archived);
  assert.deepEqual(snapshotSchema.parse(snapshot).baseline, archived);
  assert.match(
    targetOptions([snapshot]).find((item) => item.key === targetKey(snapshot))!
      .label,
    /1.17.9/,
  );
  assert.throws(() => resolveBaseline(archived.version), /Unknown baseline/);
  assert.throws(() => resolveBaseline(archived.commit), /Unknown baseline/);
});

test("snapshots reject baseline metadata attached to another target", () => {
  assert.throws(() =>
    snapshotSchema.parse({ ...entry(), baseline: nextBaseline }),
  );
  assert.throws(() => snapshotSchema.parse({ ...entry(), track: "upstream" }));
});

test("history updates migrate legacy labels and retain same-day baseline comparisons", async (context) => {
  const root = await mkdtemp(join(tmpdir(), "baseline-history-"));
  context.after(() => rm(root, { recursive: true, force: true }));
  const historyPath = join(root, "history.json");
  const snapshotPath = join(root, "snapshot.json");
  const old = entry();
  delete old.baseline;
  delete old.target_version;
  const next = forBaseline(nextBaseline);
  const archived = forBaseline({
    version: "1.19.1",
    commit: "1a6ec6a1f720fb30d76c76e656ac624fcaa237e9",
  });
  await writeFile(historyPath, JSON.stringify([old, archived]));
  await writeFile(snapshotPath, JSON.stringify(next));
  execFileSync(process.execPath, [
    "--import",
    "tsx",
    fileURLToPath(new URL("../scripts/history.ts", import.meta.url)),
    "update",
    "--snapshot",
    snapshotPath,
    "--history",
    historyPath,
  ]);
  const saved = historySchema.parse(
    JSON.parse(await readFile(historyPath, "utf8")),
  );
  assert.equal(saved.length, 3);
  assert.deepEqual(
    saved.find((item) => item.target_commit === archived.target_commit),
    archived,
  );
  assert.deepEqual(
    saved.find((item) => item.target_commit === old.target_commit),
    withBaseline(old),
  );
  assert.deepEqual(
    saved.find((item) => item.target_commit === next.target_commit),
    next,
  );
});

test("the page defaults to upstream without mixing target data", () => {
  const archived = forBaseline({ version: "1.18.0", commit: "d".repeat(40) });
  archived.metrics.cli!.passed = 2;
  const upstream = entry(undefined, "upstream");
  for (const metric of Object.values(upstream.metrics)) metric.passed = 3;
  const page = renderToStaticMarkup(
    createElement(App, { history: [archived, entry(), upstream] }),
  );
  assert.match(page, /option value="upstream" selected="">Upstream main/);
  assert.match(page, /Flatpak 1.18.0/);
  assert.doesNotMatch(page, /current baseline/);
  assert.match(page, /3\/10/);
  assert.doesNotMatch(page, /8\/10/);
  assert.doesNotMatch(page, /2\/10/);
});
