// SPDX-License-Identifier: LGPL-2.1-or-later
import assert from "node:assert/strict";
import { test } from "node:test";
import { createChartScene } from "@tanstack/charts/scene";
import type { SceneNode } from "@tanstack/charts/types";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { performanceChart } from "../src/chart.ts";
import { daily, snapshotSchema, type Snapshot } from "../src/history.ts";
import {
  availableCases,
  caseKey,
  timingRows,
  verifiedPerformance,
} from "../src/performance.ts";
import { PerformancePanel } from "../src/PerformancePanel.tsx";
import { entry, timedEntry } from "./fixtures.ts";

test("old snapshots remain valid, while new snapshots preserve finite nonnegative timings", () => {
  assert.equal(snapshotSchema.parse(entry()).performance, undefined);
  const valid = timedEntry();
  assert.deepEqual(snapshotSchema.parse(valid), valid);
  for (const seconds of [-1, NaN, Infinity]) {
    const value = timedEntry();
    value.performance!.duration_seconds = seconds;
    assert.throws(() => snapshotSchema.parse(value));
    const phase = timedEntry();
    phase.performance!.cases[0]!.timings!.execution_seconds = seconds;
    assert.throws(() => snapshotSchema.parse(phase));
  }
  const duplicate = timedEntry();
  duplicate.performance!.cases.push(duplicate.performance!.cases[0]!);
  assert.throws(() => snapshotSchema.parse(duplicate));
});

test("case choices keep behavior, driver and profile separate", () => {
  const first = timedEntry();
  first.performance!.cases.push({
    ...first.performance!.cases[0]!,
    profile: "system",
  });
  const second = timedEntry("2026-09-18T21:00:00Z");
  const choices = availableCases([first, second]);
  assert.equal(choices.length, 3);
  assert.equal(new Set(choices.map((item) => item.key)).size, 3);
  const cli = caseKey(second.performance!.cases[0]!);
  const library = caseKey(second.performance!.cases[1]!);
  assert.equal(timingRows([second], "duration_seconds", cli)[0]!.seconds, 8);
  assert.equal(
    timingRows([second], "duration_seconds", library)[0]!.seconds,
    12,
  );
  assert.equal(
    timingRows([second], "duration_seconds", library)[0]!.outcome,
    "failed",
  );
  assert.equal(timingRows([second], "cleanup_seconds", library)[0]!.seconds, 0);
});

test("legacy, missing, incomplete and unverified days create gaps, not zeroes", () => {
  const values = [
    entry(),
    timedEntry("2026-09-18T21:00:00Z"),
    timedEntry("2026-09-20T21:00:00Z"),
  ];
  assert.deepEqual(
    timingRows(values, "duration_seconds").map((row) => row.seconds),
    [null, 430, null, 430],
  );
  for (const verification of [
    "stale",
    "incomplete",
    "invalid",
    "not-run",
    "unversioned",
  ] as const) {
    const value = { ...timedEntry(), verification };
    assert.equal(verifiedPerformance(value), undefined);
    assert.equal(timingRows([value], "duration_seconds")[0]!.seconds, null);
    assert.deepEqual(availableCases([value]), []);
  }
  assert.equal(
    verifiedPerformance({ ...timedEntry(), complete: false }),
    undefined,
  );
  const zero = timedEntry();
  zero.performance!.duration_seconds = 0;
  assert.equal(timingRows([zero], "duration_seconds")[0]!.seconds, 0);
});

test("untimed, skipped and retired cases do not gain timing credit", () => {
  const first = timedEntry();
  const key = caseKey(first.performance!.cases[0]!);
  const later = timedEntry("2026-09-18T21:00:00Z");
  later.performance!.cases.shift();
  assert.deepEqual(
    timingRows([first, later], "duration_seconds", key).map(
      (row) => row.seconds,
    ),
    [8, null],
  );
  delete first.performance!.cases[0]!.timings;
  assert.equal(timingRows([first], "setup_seconds", key)[0]!.seconds, null);
  assert.equal(timingRows([first], "duration_seconds", key)[0]!.seconds, 8);
  for (const status of ["not-selected", "unsupported", "pending"] as const) {
    first.performance!.cases[0]!.status = status;
    assert.equal(
      timingRows([first], "duration_seconds", key)[0]!.seconds,
      null,
    );
    assert.equal(availableCases([first]).length, 1);
  }
});

test("performance uses the same latest complete daily snapshot as coverage", () => {
  const earlier = timedEntry();
  const later = timedEntry("2026-09-17T23:00:00Z");
  later.performance!.duration_seconds = 500;
  const selected = daily([earlier], later);
  assert.equal(timingRows(selected, "duration_seconds")[0]!.seconds, 500);
  const noTimings = entry("2026-09-17T23:30:00Z");
  assert.equal(
    timingRows(daily(selected, noTimings), "duration_seconds")[0]!.seconds,
    null,
  );
});

function flatten(nodes: readonly SceneNode[]): SceneNode[] {
  return nodes.flatMap((node) =>
    node.kind === "group" ? flatten(node.children) : [node],
  );
}

test("TanStack performance charts use seconds and break lines at missing timing data", () => {
  const entries: Snapshot[] = [
    timedEntry(),
    timedEntry("2026-09-18T21:00:00Z"),
    entry("2026-09-19T21:00:00Z"),
    timedEntry("2026-09-20T21:00:00Z"),
  ];
  const scene = createChartScene(performanceChart(entries), {
    width: 600,
    height: 300,
  });
  assert.equal(scene.points.length, 3);
  assert.equal(scene.scales.y!.domain[0], 0);
  assert.ok(Number(scene.scales.y!.domain[1]) >= 430);
  const lines = flatten(scene.nodes).filter((node) => node.kind === "polyline");
  assert.equal(lines.filter((line) => line.points.length > 1).length, 1);
  assert.ok(lines.every((line) => line.points.length <= 2));
  const key = caseKey(entries[0]!.performance!.cases[1]!);
  const caseScene = createChartScene(performanceChart([entries[0]!], key), {
    width: 350,
    height: 300,
  });
  assert.equal(caseScene.points.length, 4);
  assert.ok(
    caseScene.points.every(
      (point) => Number.isFinite(point.x) && Number.isFinite(point.y),
    ),
  );
  assert.ok(caseScene.points.some((point) => point.datum.seconds === 0));
  assert.ok(
    caseScene.points.every((point) => point.datum.outcome === "failed"),
  );
});

test("performance UI includes exact counts, outcomes and legacy empty states", () => {
  const page = renderToStaticMarkup(
    createElement(PerformancePanel, { entries: [timedEntry()] }),
  );
  assert.match(page, /430\.00s/);
  assert.match(page, /1 passed, 1 failed, 2 not-selected/);
  assert.match(page, /lifecycle\.user \/ cli \/ user/);
  assert.match(page, /lifecycle\.user \/ library \/ user/);
  assert.match(page, /Daily timings and outcomes/);
  const legacy = renderToStaticMarkup(
    createElement(PerformancePanel, { entries: [entry()] }),
  );
  assert.match(legacy, /No run timings recorded yet/);
  assert.match(legacy, /No per-case timings recorded yet/);
  assert.doesNotMatch(legacy, /0\.00s/);
});
