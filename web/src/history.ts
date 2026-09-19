// SPDX-License-Identifier: LGPL-2.1-or-later
import { z } from "zod";
import { baselineSchema } from "./baselines.ts";
import { targetKey } from "./targets.ts";

export const tracks = {
  pinned: "Pinned baseline",
  upstream: "Upstream main",
} as const;
export const series = {
  cli: { label: "CLI behavior", color: "#1756a9" },
  library: { label: "Library behavior", color: "#7541a0" },
  "cli-command": { label: "CLI commands", color: "#1756a9" },
  "cli-option": { label: "CLI options", color: "#a84b00" },
  "library-function": { label: "Library functions", color: "#7541a0" },
  "library-signal": { label: "Library signals", color: "#187447" },
} as const;
export type Series = keyof typeof series;
export type Track = keyof typeof tracks;
export const seriesNames = Object.keys(series) as Series[];
export const trackSchema = z.enum(["pinned", "upstream"]);
export const timestampSchema = z.iso.datetime({ offset: true });
export const secondsSchema = z.number().nonnegative();
export const caseStatusSchema = z.enum([
  "passed",
  "failed",
  "setup-error",
  "unmet-prerequisite",
  "unsupported",
  "not-selected",
  "pending",
]);
export type CaseStatus = z.infer<typeof caseStatusSchema>;
export const caseTimingSchema = z.object({
  behavior_id: z.string(),
  driver: z.enum(["cli", "library"]),
  profile: z.enum(["user", "system", "any"]),
  status: caseStatusSchema,
  duration_seconds: secondsSchema.optional(),
  timings: z
    .object({
      setup_seconds: secondsSchema,
      execution_seconds: secondsSchema,
      cleanup_seconds: secondsSchema,
    })
    .optional(),
});
export const performanceSchema = z
  .object({
    duration_seconds: secondsSchema.optional(),
    case_statuses: z.record(z.string(), z.number().int().nonnegative()),
    cases: z.array(caseTimingSchema),
    cases_complete: z.boolean().optional(),
  })
  .refine((value) => {
    const keys = value.cases.map((item) =>
      JSON.stringify([item.behavior_id, item.driver, item.profile]),
    );
    return new Set(keys).size === keys.length;
  }, "Duplicate case timings")
  .refine((value) => {
    if (!value.cases_complete) return true;
    const counts: Record<string, number> = {};
    for (const item of value.cases)
      counts[item.status] = (counts[item.status] ?? 0) + 1;
    return [
      ...new Set([...Object.keys(counts), ...Object.keys(value.case_statuses)]),
    ].every(
      (status) => (counts[status] ?? 0) === (value.case_statuses[status] ?? 0),
    );
  }, "Complete case inventory must match outcome counts");
export type CaseTiming = z.infer<typeof caseTimingSchema>;
export const metricSchema = z
  .object({
    total: z.number().int().nonnegative(),
    implemented: z.number().int().nonnegative(),
    implemented_percent: z.number().min(0).max(100).nullable(),
    passed: z.number().int().nonnegative().nullable(),
    passed_percent: z.number().min(0).max(100).nullable(),
  })
  .refine(
    (value) =>
      value.implemented <= value.total &&
      (value.passed === null || value.passed <= value.total),
    "Counts exceed denominator",
  );
export const snapshotSchema = z
  .object({
    schema: z.literal(1),
    track: trackSchema,
    timestamp: timestampSchema,
    complete: z.boolean(),
    verification: z.enum([
      "current",
      "not-run",
      "incomplete",
      "stale",
      "invalid",
      "unversioned",
    ]),
    suite_commit: z.string(),
    target_commit: z.string(),
    baseline: baselineSchema.optional(),
    target_version: z.string().optional(),
    run_url: z.string(),
    fingerprint: z.string(),
    metrics: z.record(z.string(), metricSchema),
    performance: performanceSchema.optional(),
  })
  .refine(
    (entry) =>
      entry.baseline === undefined ||
      (entry.track === "pinned" &&
        entry.baseline.commit === entry.target_commit),
    "Baseline must identify the pinned target commit",
  );
export const historySchema = z.array(snapshotSchema);
export type Snapshot = z.infer<typeof snapshotSchema>;
export type Metric = z.infer<typeof metricSchema>;

export function utcDay(timestamp: string): string {
  return new Date(timestampSchema.parse(timestamp)).toISOString().slice(0, 10);
}

/** Complete runs take priority over interrupted attempts, then latest finish wins. */
export function daily(
  history: readonly Snapshot[],
  entry?: Snapshot,
): Snapshot[] {
  const selected = new Map<string, Snapshot>();
  for (const item of entry ? [...history, entry] : history) {
    const key = `${targetKey(item)}/${utcDay(item.timestamp)}`;
    const previous = selected.get(key);
    if (
      !previous ||
      Number(item.complete) > Number(previous.complete) ||
      (item.complete === previous.complete &&
        Date.parse(item.timestamp) >= Date.parse(previous.timestamp))
    ) {
      selected.set(key, item);
    }
  }
  return [...selected.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([, item]) => item);
}

export function credit(entry: Snapshot, name: Series) {
  const metric = entry.metrics[name];
  if (
    !entry.complete ||
    entry.verification !== "current" ||
    !metric ||
    metric.passed === null ||
    metric.total === 0
  )
    return null;
  return {
    passed: metric.passed,
    total: metric.total,
    percent: (metric.passed * 100) / metric.total,
  };
}

export const dayMilliseconds = 86_400_000;
/** Insert an explicit null after a missing day so charts cannot bridge the gap. */
export function dailyEntries(entries: readonly Snapshot[]) {
  const rows: { day: number; date: string; entry: Snapshot | null }[] = [];
  for (const entry of [...entries].sort(
    (a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp),
  )) {
    const date = utcDay(entry.timestamp);
    const day = Date.parse(date) / dayMilliseconds;
    const previous = rows.at(-1);
    if (previous && day - previous.day > 1) {
      rows.push({
        day: previous.day + 1,
        date: "",
        entry: null,
      });
    }
    rows.push({ day, date, entry });
  }
  return rows;
}

export function chartRows(entries: readonly Snapshot[], name: Series) {
  return dailyEntries(entries).map(({ day, date, entry }) => {
    const value = entry ? credit(entry, name) : null;
    return {
      day,
      date,
      percent: value?.percent ?? null,
      passed: value?.passed ?? null,
      total: value?.total ?? null,
      label: series[name].label,
    };
  });
}
