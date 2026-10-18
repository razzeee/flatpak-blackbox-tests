// SPDX-License-Identifier: LGPL-2.1-or-later
import assert from "node:assert/strict";
import { test } from "node:test";
import { createChartScene } from "@tanstack/charts/scene";
import type { SceneNode } from "@tanstack/charts/types";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { App } from "../src/App.tsx";
import { evidenceDays, RunHealth } from "../src/RunHealth.tsx";
import { coverageChart, outcomeChart } from "../src/chart.ts";
import { outcomeRows } from "../src/performance.ts";
import { completeEntry, entry } from "./fixtures.ts";

function flatten(nodes: readonly SceneNode[]): SceneNode[] {
  return nodes.flatMap((node) =>
    node.kind === "group" ? flatten(node.children) : [node],
  );
}

test("TanStack renders separate line segments across missing and unverified days", () => {
  const entries = [
    entry(),
    entry("2026-09-18T21:00:00Z"),
    entry("2026-09-20T21:00:00Z"),
    { ...entry("2026-09-21T21:00:00Z"), verification: "stale" as const },
    entry("2026-09-22T21:00:00Z"),
    entry("2026-09-23T21:00:00Z"),
  ];
  const scene = createChartScene(coverageChart(entries, ["cli"]), {
    width: 700,
    height: 300,
  });
  const lines = flatten(scene.nodes).filter((node) => node.kind === "polyline");
  assert.equal(scene.points.length, 5);
  assert.equal(lines.filter((node) => node.points.length > 1).length, 2);
  assert.ok(lines.every((node) => node.points.length <= 2));
});

test("single-day and hidden-series charts have finite coordinates", () => {
  for (const names of [["cli"] as const, [] as const]) {
    const scene = createChartScene(coverageChart([entry()], names), {
      width: 350,
      height: 300,
    });
    assert.ok(
      scene.points.every(
        (point) => Number.isFinite(point.x) && Number.isFinite(point.y),
      ),
    );
    assert.equal(scene.points.length, names.length);
    assert.deepEqual(scene.scales.y?.domain, [0, 100]);
    assert.ok(scene.scales.x?.domain.every((value) => Number.isFinite(value)));
  }
});

test("outcome rows preserve status counts and missing-day gaps", () => {
  const rows = outcomeRows([
    completeEntry("2026-09-17T21:00:00Z", [
      {
        behavior_id: "passed",
        driver: "cli",
        profile: "user",
        status: "passed",
      },
      {
        behavior_id: "failed",
        driver: "cli",
        profile: "user",
        status: "failed",
      },
    ]),
    completeEntry("2026-09-19T21:00:00Z", [
      {
        behavior_id: "skipped",
        driver: "cli",
        profile: "user",
        status: "not-selected",
      },
    ]),
  ]);
  const passed = rows.filter((row) => row.status === "passed");
  assert.deepEqual(
    passed.map((row) => [row.date, row.count]),
    [
      ["2026-09-17", 1],
      ["", null],
      ["2026-09-19", null],
    ],
  );
  assert.equal(
    rows.find((row) => row.status === "failed" && row.date === "2026-09-17")
      ?.count,
    1,
  );
});

test("outcome rows preserve unverified-day gaps", () => {
  const rows = outcomeRows([
    { ...completeEntry("2026-09-17T21:00:00Z", []), verification: "stale" },
  ]);
  assert.ok(rows.every((row) => row.count === null));
});

test("outcome chart renders finite stacked coordinates", () => {
  const scene = createChartScene(
    outcomeChart([
      completeEntry("2026-09-17T21:00:00Z", []),
      completeEntry("2026-09-19T21:00:00Z", []),
    ]),
    { width: 700, height: 300 },
  );
  assert.ok(
    scene.points.every(
      (point) => Number.isFinite(point.x) && Number.isFinite(point.y),
    ),
  );
});

test("counts retain denominator changes and React escapes metadata", () => {
  const first = entry();
  const second = entry("2026-09-18T21:00:00Z");
  second.metrics.cli!.total = 20;
  second.suite_commit = "<script>bad</script>";
  second.run_url = "javascript:alert(1)";
  const page = renderToStaticMarkup(
    createElement(App, { history: [first, second] }),
  );
  assert.match(page, /8\/10/);
  assert.match(page, /8\/20/);
  assert.match(page, /40.00%/);
  assert.doesNotMatch(page, /<script>/);
  assert.doesNotMatch(page, /javascript:/);
  assert.match(
    renderToStaticMarkup(createElement(App, { history: [] })),
    /No recorded runs/,
  );
});

test("run timeline distinguishes missing snapshots without claiming schedules were skipped", () => {
  const missing = entry("2026-09-17T21:00:00Z");
  const noReport = {
    ...entry("2026-09-19T21:00:00Z"),
    complete: false,
    verification: "not-run" as const,
  };
  const page = renderToStaticMarkup(
    createElement(App, { history: [missing, noReport] }),
  );
  const historyPanel =
    page.match(/<section class="run-health"[\s\S]*?<\/section>/)?.[0] ?? "";
  assert.match(historyPanel, /Run history/);
  assert.match(historyPanel, /aria-expanded="false"/);
  assert.match(historyPanel, /hidden=""/);
  assert.match(
    page.match(/<div[^>]*id="panel-evidence"[^>]*>/)?.[0] ?? "",
    /hidden=""/,
  );
  assert.match(page, /Runs are scheduled daily/);
  assert.match(page, /No coverage snapshot/);
  assert.match(page, /No test report/);
  assert.match(page, /Verified evidence/);
  assert.match(page, /delayed schedule can leave a gap/);
  assert.doesNotMatch(page, /no run observed/);
});

test("evidence timeline is bounded, chronological and independent of today's date", () => {
  assert.deepEqual(evidenceDays([]), []);
  const days = evidenceDays([
    entry("2026-10-16T21:00:00Z"),
    entry("2026-08-01T21:00:00Z"),
  ]);
  assert.equal(days.length, 30);
  assert.equal(days[0]!.date, "2026-09-17");
  assert.equal(days.at(-1)!.date, "2026-10-16");
  assert.equal(days[0]!.state, "missing");
  assert.equal(days.at(-1)!.state, "verified");
});

test("workflow provenance renders observed trigger timing without redating coverage", () => {
  const value = {
    ...entry("2026-10-06T00:49:00Z"),
    workflow: { event: "schedule", created_at: "2026-10-06T00:36:25Z" },
  };
  const page = renderToStaticMarkup(
    createElement(RunHealth, { entries: [value] }),
  );
  assert.match(page, /Scheduled trigger/);
  assert.match(page, /observed trigger time, not the planned start/);
  assert.equal(evidenceDays([value])[0]!.date, "2026-10-06");
});
