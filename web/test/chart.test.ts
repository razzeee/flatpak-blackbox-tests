// SPDX-License-Identifier: LGPL-2.1-or-later
import assert from "node:assert/strict";
import { test } from "node:test";
import { createChartScene } from "@tanstack/charts/scene";
import type { SceneNode } from "@tanstack/charts/types";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { App } from "../src/App.tsx";
import { coverageChart } from "../src/chart.ts";
import { entry } from "./fixtures.ts";

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
