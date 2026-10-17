// SPDX-License-Identifier: LGPL-2.1-or-later
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { App } from "../src/App.tsx";
import { snapshotSchema, type CaseTiming } from "../src/history.ts";
import { caseKey } from "../src/performance.ts";
import { OutcomeFilters, RunDiagnostics } from "../src/RunDiagnostics.tsx";
import { RunSummary } from "../src/RunSummary.tsx";
import { DashboardTabs } from "../src/DashboardTabs.tsx";
import { CaseHistory, PerformancePanel } from "../src/PerformancePanel.tsx";
import {
  caseOptions,
  compareRuns,
  defaultOutcomeFilter,
  delta,
  earlierRuns,
  filterCases,
  inventoryComplete,
  rankCases,
  runAccounting,
} from "../src/runComparison.ts";
import { completeEntry, entry, timedEntry } from "./fixtures.ts";

const day1 = "2026-09-17T21:00:00Z";
const day2 = "2026-09-18T21:00:00Z";

test("default outcome view prioritizes verified failures, then setup errors, otherwise all cases", () => {
  assert.equal(
    defaultOutcomeFilter(completeEntry(day1, [result("broken", 1, "failed")])),
    "failed",
  );
  assert.equal(
    defaultOutcomeFilter(
      completeEntry(day1, [result("setup", 1, "setup-error")]),
    ),
    "setup-error",
  );
  assert.equal(
    defaultOutcomeFilter(completeEntry(day1, [result("ok", 1)])),
    "all",
  );
  assert.equal(
    defaultOutcomeFilter({
      ...completeEntry(day1, [result("stale", 1, "failed")]),
      verification: "stale",
    }),
    "all",
  );
  assert.equal(defaultOutcomeFilter(undefined), "all");
});

test("the dashboard opens on Trends and keeps failure-filtered Cases available", () => {
  const run = completeEntry(day1, [
    result("broken", 1, "failed"),
    result("healthy", 1),
  ]);
  const html = renderToStaticMarkup(createElement(App, { history: [run] }));
  const trendsTab = html.match(/<button[^>]*id="tab-trends"[^>]*>/)?.[0] ?? "";
  assert.match(trendsTab, /aria-selected="true"/);
  const trendsPanel = html.match(/<div[^>]*id="panel-trends"[^>]*>/)?.[0] ?? "";
  assert.doesNotMatch(trendsPanel, /hidden=""/);
  const casesPanel = html.match(/<div[^>]*id="panel-cases"[^>]*>/)?.[0] ?? "";
  assert.match(casesPanel, /hidden=""/);
  const table =
    html.match(
      /<table[^>]*class="[^"]*case-comparison[^"]*"[\s\S]*?<\/table>/,
    )?.[0] ?? "";
  assert.match(table, /Inspect broken/);
  assert.doesNotMatch(table, /Inspect healthy/);
  assert.match(html, /All cases/);
  const selected =
    html
      .match(/<button[^>]*>[\s\S]*?<\/button>/g)
      ?.find(
        (button) =>
          button.includes('role="radio"') &&
          button.includes('aria-checked="true"'),
      ) ?? "";
  assert.match(selected, /Failed/);
});

test("inspector retains removed-case provenance and never replaces absent timings with zero", () => {
  const before = completeEntry(day1, [result("retired", 5, "failed")]);
  const current = completeEntry(day2, [result("replacement", 7)]);
  const comparison = compareRuns(current, before).find(
    (row) => row.before?.behavior_id === "retired",
  )!;
  const html = renderToStaticMarkup(
    createElement(CaseHistory, {
      entries: [before, current],
      run: current,
      caseId: comparison.key,
      comparison,
    }),
  );
  assert.match(html, /This case was not recorded in the selected run/);
  assert.match(html, /Removed case/);
  assert.match(html, /Before: 5\.00s \(Failed\)/);
  assert.match(html, /Not recorded/);
  assert.doesNotMatch(html, /\b0\.00s/);
});

test("dashboard tabs expose one selected view with matching labelled panels", () => {
  const tabs = renderToStaticMarkup(
    createElement(DashboardTabs, {
      value: "trends",
      onChange: () => {},
    }),
  );
  assert.equal((tabs.match(/aria-selected="true"/g) ?? []).length, 1);
  assert.match(
    tabs.match(/<button[^>]*id="tab-trends"[^>]*>/)?.[0] ?? "",
    /aria-selected="true"/,
  );
  const run = completeEntry(day2, [result("ok", 1)]);
  const panel = renderToStaticMarkup(
    createElement(
      DashboardTabs,
      { value: "trends", onChange: () => {} },
      createElement(PerformancePanel, {
        entries: [run],
        activeTab: "trends",
      }),
    ),
  );
  const casesPanel = panel.match(/<div[^>]*id="panel-cases"[^>]*>/)?.[0] ?? "";
  assert.match(casesPanel, /hidden=""/);
  assert.match(casesPanel, /aria-labelledby="tab-cases"/);
  const trendsPanel =
    panel.match(/<div[^>]*id="panel-trends"[^>]*>/)?.[0] ?? "";
  assert.match(trendsPanel, /aria-labelledby="tab-trends"/);
  assert.doesNotMatch(trendsPanel, /hidden=""/);
  const evidencePanel =
    panel.match(/<div[^>]*id="panel-evidence"[^>]*>/)?.[0] ?? "";
  assert.match(evidencePanel, /hidden=""/);
});

test("outcome filters include nonzero statuses without empty secondary options", () => {
  const run = completeEntry(day2, [
    result("ok", 1),
    result("setup", 1, "setup-error"),
  ]);
  const html = renderToStaticMarkup(
    createElement(OutcomeFilters, {
      run,
      value: "all",
      onChange: () => {},
    }),
  );
  assert.match(html, /Setup error/);
  assert.match(html, /class="outcome-count">1/);
  assert.doesNotMatch(html, /Unsupported|Pending/);
});

test("run-first layout puts failures and investigation ahead of historical charts", () => {
  const run = completeEntry(day2, [
    result("broken", 2, "failed"),
    result("ok", 1),
  ]);
  const html = renderToStaticMarkup(createElement(App, { history: [run] }));
  assert.match(html, /case needs[^<]* attention/);
  assert.match(html, /Inspect failed cases/);
  assert.ok(html.indexOf("case needs") < html.indexOf("Case results"));
  assert.ok(
    html.indexOf("Case results") < html.indexOf("Coverage &amp; performance"),
  );
  assert.match(html, /data-slot="tabs-trigger"/);
  assert.match(html, /Open details for/);
  assert.doesNotMatch(html, /<th scope="col">Phase deltas/);
});

function result(
  id: string,
  seconds?: number,
  status: CaseTiming["status"] = "passed",
): CaseTiming {
  return {
    behavior_id: id,
    driver: "cli",
    profile: "user",
    status,
    ...(seconds === undefined ? {} : { duration_seconds: seconds }),
  };
}

test("rank added seconds rather than current duration or percentage, with phase deltas", () => {
  const before = completeEntry(day1, [
    {
      ...result("small", 5),
      timings: { setup_seconds: 1, execution_seconds: 3, cleanup_seconds: 1 },
    },
    result("large", 60),
    result("tiny", 0.1),
  ]);
  const current = completeEntry(day2, [
    {
      ...result("small", 9),
      timings: { setup_seconds: 2, execution_seconds: 6, cleanup_seconds: 1 },
    },
    result("large", 61),
    result("tiny", 1),
  ]);
  const ranked = rankCases(compareRuns(current, before), "change");
  assert.deepEqual(
    ranked.map((row) => row.after?.behavior_id),
    ["small", "large", "tiny"],
  );
  assert.equal(ranked[0]!.addedSeconds, 4);
  assert.equal(ranked[0]!.percent, 80);
  assert.deepEqual(ranked[0]!.phases, {
    duration_seconds: 4,
    setup_seconds: 1,
    execution_seconds: 3,
    cleanup_seconds: 0,
  });
  assert.equal(rankCases(ranked, "duration")[0]!.after?.behavior_id, "large");
});

test("known additions and removals get explicit contributions, not invented percentages", () => {
  const before = completeEntry(day1, [
    result("removed", 10),
    result("same", 5),
  ]);
  const current = completeEntry(day2, [result("added", 20), result("same", 6)]);
  const rows = rankCases(compareRuns(current, before), "change");
  assert.deepEqual(
    rows.map((row) => [row.kind, row.addedSeconds]),
    [
      ["Added case", 20],
      ["Comparable", 1],
      ["Removed case", -10],
    ],
  );
  assert.equal(rows[0]!.beforeSeconds, null);
  assert.equal(rows[0]!.percent, null);
  assert.equal(rows[2]!.afterSeconds, null);
  assert.equal(rows[2]!.percent, null);
});

test("legacy missing details cannot masquerade as added or removed cases", () => {
  const before = timedEntry(day1);
  const current = completeEntry(day2, [result("new-or-unrecorded", 20)]);
  const rows = compareRuns(current, before);
  assert.equal(rows.find((row) => row.after)?.kind, "Not recorded before");
  assert.equal(rows.find((row) => row.after)?.addedSeconds, null);
  const incompleteCurrent = {
    ...current,
    performance: { ...current.performance!, cases_complete: false },
  };
  assert.ok(
    compareRuns(incompleteCurrent, before)
      .filter((row) => !row.after)
      .every(
        (row) => row.kind === "Not recorded now" && row.addedSeconds === null,
      ),
  );
});

test("zero durations, missing timings and outcome changes have distinct meanings", () => {
  const before = completeEntry(day1, [
    result("zero", 0),
    result("zero-still", 0),
    result("skipped", 99, "not-selected"),
    result("failed-now", 10),
    result("untimed-now", 4),
  ]);
  const current = completeEntry(day2, [
    result("zero", 3),
    result("zero-still", 0),
    result("skipped", 5),
    result("failed-now", 1, "failed"),
    result("untimed-now", undefined, "setup-error"),
  ]);
  const rows = compareRuns(current, before);
  const lookup = (id: string) =>
    rows.find((row) => row.after?.behavior_id === id)!;
  assert.equal(lookup("zero").addedSeconds, 3);
  assert.equal(lookup("zero").percent, null);
  assert.equal(lookup("zero-still").percent, 0);
  assert.equal(lookup("skipped").kind, "No earlier timing");
  assert.equal(lookup("skipped").addedSeconds, null);
  assert.equal(lookup("failed-now").before?.status, "passed");
  assert.equal(lookup("failed-now").after?.status, "failed");
  assert.equal(lookup("failed-now").addedSeconds, -9);
  assert.equal(lookup("untimed-now").kind, "No current timing");
  assert.equal(lookup("untimed-now").addedSeconds, null);
});

test("case identity includes driver and profile and filters use the selected run outcome", () => {
  const before = completeEntry(day1, [
    result("shared", 1),
    { ...result("shared", 2), driver: "library" },
    { ...result("shared", 3), profile: "system" },
    result("removed-failure", 4, "failed"),
  ]);
  const current = completeEntry(day2, [
    result("shared", 1),
    { ...result("shared", 5, "failed"), driver: "library" },
    { ...result("shared", 4), profile: "system" },
  ]);
  const rows = compareRuns(current, before);
  assert.equal(rows.length, 4);
  assert.equal(new Set(rows.map((row) => row.key)).size, 4);
  const failed = filterCases(rows, "failed", " SHARED / LIBRARY ");
  assert.equal(failed.length, 1);
  assert.equal(failed[0]!.addedSeconds, 3);
  assert.equal(filterCases(rows, "all", "system")[0]!.addedSeconds, 1);
});

test("run accounting separates shared or unrecorded time and never invents negative overhead", () => {
  const current = completeEntry(
    day2,
    [
      result("one", 10),
      result("two", 20),
      result("excluded", 500, "unsupported"),
      result("blocked", undefined, "unmet-prerequisite"),
    ],
    110,
  );
  const before = completeEntry(day1, current.performance!.cases, 100);
  assert.deepEqual(runAccounting(current), {
    total: 110,
    cases: 30,
    outside: 80,
  });
  assert.equal(
    delta(runAccounting(before).outside, runAccounting(current).outside),
    10,
  );
  const inconsistent = {
    ...current,
    performance: { ...current.performance!, duration_seconds: 20 },
  };
  assert.equal(runAccounting(inconsistent).outside, null);
  assert.deepEqual(runAccounting(entry()), {
    total: null,
    cases: null,
    outside: null,
  });
});

test("comparison defaults to an earlier verified run of the same target", () => {
  const current = timedEntry("2026-09-20T21:00:00Z");
  const old = timedEntry(day1);
  const previous = timedEntry(day2);
  const invalid = {
    ...timedEntry("2026-09-19T21:00:00Z"),
    verification: "stale" as const,
  };
  const other = timedEntry(day2, "upstream");
  assert.deepEqual(
    earlierRuns([other, current, invalid, old, previous], current),
    [previous, old],
  );
  assert.throws(() => compareRuns(current, other), /same target/);
  assert.deepEqual(compareRuns(invalid, previous), []);
});

test("complete inventories are validated and old exact inventories can be inferred", () => {
  const complete = completeEntry(day1, [
    result("skip", undefined, "not-selected"),
  ]);
  assert.equal(inventoryComplete(snapshotSchema.parse(complete)), true);
  const legacy = structuredClone(complete);
  delete legacy.performance!.cases_complete;
  assert.equal(inventoryComplete(legacy), true);
  legacy.performance!.case_statuses.failed = 1;
  assert.equal(inventoryComplete(legacy), false);
  legacy.performance!.cases_complete = true;
  assert.throws(() => snapshotSchema.parse(legacy), /match outcome counts/);
});

test("untimed cases remain selectable and a single run defaults to slowest first", () => {
  const current = completeEntry(day1, [
    result("skipped", undefined, "not-selected"),
    result("short", 5),
    result("slow-failure", 60, "failed"),
  ]);
  const rows = rankCases(compareRuns(current), "duration");
  assert.equal(rows[0]!.after?.behavior_id, "slow-failure");
  assert.equal(rows.at(-1)!.after?.behavior_id, "skipped");
  assert.ok(
    caseOptions([current]).some(
      (item) => item.key === caseKey(current.performance!.cases[0]!),
    ),
  );
});

test("outcome filters render failed and skipped counts, not zeroes for unavailable data", () => {
  const current = completeEntry(day1, [
    result("failed", 1, "failed"),
    result("skip", undefined, "not-selected"),
  ]);
  const page = renderToStaticMarkup(
    createElement(OutcomeFilters, {
      run: current,
      value: "all",
      onChange: () => {},
    }),
  );
  assert.match(page, /Failed <span class="outcome-count">1/);
  assert.match(page, /Not selected <span class="outcome-count">1/);
  const missing = renderToStaticMarkup(
    createElement(RunSummary, {
      entries: [entry()],
      run: entry(),
      onFilter: () => {},
      onRunChange: () => {},
    }),
  );
  assert.match(missing, /outcomes are unavailable/);
  assert.doesNotMatch(missing, /<strong>0<\/strong>/);
});

test("diagnostics explain legacy gaps and the page selects the latest run", () => {
  const current = timedEntry(day2);
  const partial = renderToStaticMarkup(
    createElement(RunDiagnostics, {
      run: current,
      earlier: [],
      comparisonChoice: "auto",
      rows: compareRuns(current),
      filter: "not-selected",
      onFilter: () => {},
      onComparison: () => {},
      onInspect: () => {},
    }),
  );
  assert.match(partial, /older snapshot retained only some case details/);
  assert.match(partial, /No retained case details match this filter/);
  const before = completeEntry(day1, [result("slow", 5)]);
  const latest = completeEntry(day2, [result("slow", 15)]);
  const page = renderToStaticMarkup(
    createElement(App, { history: [latest, before] }),
  );
  assert.match(page, /Case results/);
  assert.match(page, /SELECTED RUN \/ 2026-09-18/);
  assert.match(page, /\+10\.00s/);
  assert.match(page, /Outside recorded cases/);
});
