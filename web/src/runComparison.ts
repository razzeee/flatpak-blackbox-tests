// SPDX-License-Identifier: LGPL-2.1-or-later
import type { CaseStatus, CaseTiming, Snapshot } from "./history.ts";
import {
  caseKey,
  hasCaseTiming,
  timingNames,
  verifiedPerformance,
  type TimingSeries,
} from "./performance.ts";
import { targetKey } from "./targets.ts";

export const outcomeLabels: Record<CaseStatus, string> = {
  passed: "Passed",
  failed: "Failed",
  "setup-error": "Setup error",
  "unmet-prerequisite": "Unmet prerequisite",
  unsupported: "Unsupported",
  "not-selected": "Not selected",
  pending: "Pending",
};
export type OutcomeFilter = CaseStatus | "all";
export type CaseSort = "change" | "duration";

export function caseLabel(item: CaseTiming): string {
  return `${item.behavior_id} / ${item.driver} / ${item.profile}`;
}

export function caseRecord(entry: Snapshot, key: string) {
  return verifiedPerformance(entry)?.cases.find(
    (item) => caseKey(item) === key,
  );
}

export function caseOptions(entries: readonly Snapshot[]) {
  const options = new Map<string, string>();
  for (const entry of entries) {
    for (const item of verifiedPerformance(entry)?.cases ?? []) {
      options.set(caseKey(item), caseLabel(item));
    }
  }
  return [...options]
    .map(([key, label]) => ({ key, label }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

export function caseSeconds(
  item: CaseTiming | undefined,
  phase: TimingSeries = "duration_seconds",
): number | null {
  if (!item || !hasCaseTiming(item)) return null;
  return (
    (phase === "duration_seconds"
      ? item.duration_seconds
      : item.timings?.[phase]) ?? null
  );
}

export function delta(
  before: number | null | undefined,
  after: number | null | undefined,
): number | null {
  return before == null || after == null ? null : after - before;
}

/** Legacy snapshots omitted untimed cases, but exact counts can prove completeness. */
export function inventoryComplete(entry: Snapshot): boolean {
  const performance = verifiedPerformance(entry);
  if (!performance) return false;
  if (performance.cases_complete !== undefined)
    return performance.cases_complete;
  const counts: Record<string, number> = {};
  for (const item of performance.cases)
    counts[item.status] = (counts[item.status] ?? 0) + 1;
  return [
    ...new Set([
      ...Object.keys(counts),
      ...Object.keys(performance.case_statuses),
    ]),
  ].every(
    (status) =>
      (counts[status] ?? 0) === (performance.case_statuses[status] ?? 0),
  );
}

export function earlierRuns(
  entries: readonly Snapshot[],
  current: Snapshot,
): Snapshot[] {
  return entries
    .filter(
      (item) =>
        targetKey(item) === targetKey(current) &&
        Date.parse(item.timestamp) < Date.parse(current.timestamp) &&
        verifiedPerformance(item),
    )
    .sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp));
}

export function runAccounting(entry: Snapshot) {
  const performance = verifiedPerformance(entry);
  if (!performance) return { total: null, cases: null, outside: null };
  const total = performance.duration_seconds ?? null;
  const cases = performance.cases.reduce(
    (sum, item) => sum + (caseSeconds(item) ?? 0),
    0,
  );
  const remaining = total === null ? null : total - cases;
  // A negative remainder is inconsistent data, not negative shared setup time.
  const outside =
    remaining === null || remaining < -1e-6 ? null : Math.max(0, remaining);
  return { total, cases, outside };
}

export type ComparisonKind =
  | "Recorded"
  | "Comparable"
  | "Added case"
  | "Removed case"
  | "Not recorded before"
  | "Not recorded now"
  | "No earlier timing"
  | "No current timing"
  | "No timing";

export interface CaseComparison {
  key: string;
  label: string;
  before?: CaseTiming;
  after?: CaseTiming;
  beforeSeconds: number | null;
  afterSeconds: number | null;
  addedSeconds: number | null;
  percent: number | null;
  phases: Record<TimingSeries, number | null>;
  kind: ComparisonKind;
}

export function compareRuns(
  current: Snapshot,
  reference?: Snapshot,
): CaseComparison[] {
  if (reference && targetKey(reference) !== targetKey(current)) {
    throw new Error("Compare runs of the same target");
  }
  const performance = verifiedPerformance(current);
  if (!performance) return [];
  const previous = reference ? verifiedPerformance(reference) : undefined;
  const after = new Map(performance.cases.map((item) => [caseKey(item), item]));
  const before = new Map(previous?.cases.map((item) => [caseKey(item), item]));
  return [...new Set([...after.keys(), ...before.keys()])].map((key) => {
    const a = after.get(key);
    const b = before.get(key);
    const beforeSeconds = caseSeconds(b);
    const afterSeconds = caseSeconds(a);
    let addedSeconds = delta(beforeSeconds, afterSeconds);
    let kind: ComparisonKind = "Recorded";
    if (previous && reference) {
      if (!b) {
        kind = inventoryComplete(reference)
          ? "Added case"
          : "Not recorded before";
        // This is a contribution from a confirmed new case, not a measured regression.
        if (kind === "Added case") addedSeconds = afterSeconds;
      } else if (!a) {
        kind = inventoryComplete(current) ? "Removed case" : "Not recorded now";
        if (kind === "Removed case" && beforeSeconds !== null)
          addedSeconds = -beforeSeconds;
      } else if (beforeSeconds === null && afterSeconds === null)
        kind = "No timing";
      else if (beforeSeconds === null) kind = "No earlier timing";
      else if (afterSeconds === null) kind = "No current timing";
      else kind = "Comparable";
    }
    const percent =
      kind !== "Comparable" || beforeSeconds === null || afterSeconds === null
        ? null
        : beforeSeconds > 0
          ? ((afterSeconds - beforeSeconds) * 100) / beforeSeconds
          : afterSeconds === 0
            ? 0
            : null;
    const phases = Object.fromEntries(
      timingNames.map((name) => [
        name,
        delta(caseSeconds(b, name), caseSeconds(a, name)),
      ]),
    ) as Record<TimingSeries, number | null>;
    return {
      key,
      label: caseLabel(a ?? b!),
      before: b,
      after: a,
      beforeSeconds,
      afterSeconds,
      addedSeconds,
      percent,
      phases,
      kind,
    };
  });
}

export function rankCases(
  rows: readonly CaseComparison[],
  sort: CaseSort,
): CaseComparison[] {
  return [...rows].sort((a, b) => {
    const x = sort === "change" ? a.addedSeconds : a.afterSeconds;
    const y = sort === "change" ? b.addedSeconds : b.afterSeconds;
    if (x === null && y !== null) return 1;
    if (y === null && x !== null) return -1;
    return (
      (y ?? 0) - (x ?? 0) ||
      (b.afterSeconds ?? -1) - (a.afterSeconds ?? -1) ||
      a.label.localeCompare(b.label)
    );
  });
}

export function filterCases(
  rows: readonly CaseComparison[],
  status: OutcomeFilter,
  query: string,
): CaseComparison[] {
  const search = query.trim().toLowerCase();
  return rows.filter(
    (row) =>
      (status === "all" || row.after?.status === status) &&
      row.label.toLowerCase().includes(search),
  );
}
