// SPDX-License-Identifier: LGPL-2.1-or-later
import { dailyEntries, type CaseTiming, type Snapshot } from "./history.ts";

export const timingSeries = {
  duration_seconds: { label: "Total", color: "#1756a9" },
  setup_seconds: { label: "Setup", color: "#a84b00" },
  execution_seconds: { label: "Execution", color: "#7541a0" },
  cleanup_seconds: { label: "Cleanup", color: "#187447" },
} as const;
export type TimingSeries = keyof typeof timingSeries;
export const timingNames = Object.keys(timingSeries) as TimingSeries[];

export function hasCaseTiming(item: CaseTiming): boolean {
  return (
    !["not-selected", "unsupported", "pending"].includes(item.status) &&
    (item.duration_seconds !== undefined || item.timings !== undefined)
  );
}

export function caseKey(item: CaseTiming): string {
  return JSON.stringify([item.behavior_id, item.driver, item.profile]);
}

export function verifiedPerformance(entry: Snapshot) {
  return entry.complete && entry.verification === "current"
    ? entry.performance
    : undefined;
}

export function availableCases(entries: readonly Snapshot[]) {
  const cases = new Map<string, string>();
  for (const entry of entries) {
    for (const item of verifiedPerformance(entry)?.cases ?? []) {
      if (hasCaseTiming(item)) {
        cases.set(
          caseKey(item),
          `${item.behavior_id} / ${item.driver} / ${item.profile}`,
        );
      }
    }
  }
  return [...cases]
    .map(([key, label]) => ({ key, label }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

export function caseTiming(entry: Snapshot, key: string) {
  return verifiedPerformance(entry)?.cases.find(
    (item) => caseKey(item) === key && hasCaseTiming(item),
  );
}

export function runOutcomes(entry: Snapshot): string {
  const statuses = verifiedPerformance(entry)?.case_statuses;
  return statuses
    ? Object.entries(statuses)
        .filter(([, count]) => count > 0)
        .map(([status, count]) => `${count} ${status}`)
        .join(", ")
    : "No timing";
}

export function timingRows(
  entries: readonly Snapshot[],
  name: TimingSeries,
  key?: string,
) {
  return dailyEntries(entries).map(({ day, date, entry }) => {
    const item =
      entry && key !== undefined ? caseTiming(entry, key) : undefined;
    const performance = entry ? verifiedPerformance(entry) : undefined;
    const seconds =
      key === undefined
        ? performance?.duration_seconds
        : name === "duration_seconds"
          ? item?.duration_seconds
          : item?.timings?.[name];
    return {
      day,
      date,
      seconds: seconds ?? null,
      label: key === undefined ? "Test run" : timingSeries[name].label,
      outcome: entry
        ? key === undefined
          ? runOutcomes(entry)
          : (item?.status ?? "No timing")
        : "No timing",
    };
  });
}
