// SPDX-License-Identifier: LGPL-2.1-or-later
import { spawnSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { z } from "zod";
import {
  metricSchema,
  caseTimingSchema,
  secondsSchema,
  snapshotSchema,
  timestampSchema,
  type Snapshot,
  type Track,
} from "../src/history.ts";
import { hasCaseTiming } from "../src/performance.ts";
import { findBaseline } from "../src/baselines.ts";

export async function readJson(path: string): Promise<unknown> {
  return JSON.parse(await readFile(path, "utf8"));
}

export async function optionalJson(path: string): Promise<unknown | undefined> {
  try {
    return await readJson(path);
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT")
      return undefined;
    throw error;
  }
}

const summarySchema = z.object({
  schema: z.literal(1),
  verification: z.object({ status: snapshotSchema.shape.verification }),
  definition: z.object({ fingerprint: z.string() }),
  metrics: z.object({
    behaviors: z.record(z.string(), metricSchema),
    surfaces: z.record(z.string(), metricSchema),
  }),
});
const reportMetadata = z.object({
  complete: z.boolean().optional(),
  finished_at: timestampSchema.optional(),
  target_version: z.string().optional(),
});
const timingMetadata = z.object({
  duration_seconds: secondsSchema.optional(),
  results: z.array(caseTimingSchema).optional(),
});

export interface RecordOptions {
  report: string;
  track: Track;
  timestamp: string;
  suiteCommit: string;
  targetCommit: string;
  runUrl: string;
}

export async function record(options: RecordOptions): Promise<Snapshot> {
  const baseline =
    options.track === "pinned" ? findBaseline(options.targetCommit) : undefined;
  if (options.track === "pinned" && !baseline) {
    throw new Error(
      `Unknown pinned commit ${options.targetCommit}; add it to ci/baselines.json`,
    );
  }
  const rawReport = await optionalJson(options.report);
  const report =
    rawReport === undefined ? undefined : reportMetadata.parse(rawReport);
  const args = [
    fileURLToPath(new URL("../../coverage_report.py", import.meta.url)),
    "--json",
  ];
  if (report) args.push("--report", options.report);
  // The existing engine owns attribution and evidence checks. Status 1 can be a
  // valid unverified summary; malformed input or engine failure has no JSON output.
  const result = spawnSync("python3", args, {
    encoding: "utf8",
    maxBuffer: 32 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if ((result.status !== 0 && result.status !== 1) || !result.stdout.trim()) {
    throw new Error(
      result.stderr || `Coverage engine exited with ${result.status}`,
    );
  }
  const summary = summarySchema.parse(JSON.parse(result.stdout));
  if (
    baseline &&
    summary.verification.status === "current" &&
    report?.target_version &&
    report.target_version.trim() !== `Flatpak ${baseline.version}`
  ) {
    throw new Error(
      `Reported version ${report.target_version} does not match baseline ${baseline.version}`,
    );
  }
  let performance: Snapshot["performance"];
  if (report?.complete && summary.verification.status === "current") {
    const timings = timingMetadata.parse(rawReport);
    const cases = (timings.results ?? []).filter(hasCaseTiming);
    if (timings.duration_seconds !== undefined || cases.length) {
      const statuses: Record<string, number> = {};
      for (const item of timings.results ?? []) {
        statuses[item.status] = (statuses[item.status] ?? 0) + 1;
      }
      performance = {
        duration_seconds: timings.duration_seconds,
        case_statuses: statuses,
        cases,
      };
    }
  }
  return snapshotSchema.parse({
    schema: 1,
    track: options.track,
    timestamp: new Date(
      timestampSchema.parse(report?.finished_at ?? options.timestamp),
    ).toISOString(),
    complete: report?.complete ?? false,
    verification: summary.verification.status,
    suite_commit: options.suiteCommit,
    target_commit: options.targetCommit,
    baseline,
    target_version: report?.target_version,
    run_url: options.runUrl,
    fingerprint: summary.definition.fingerprint,
    metrics: { ...summary.metrics.behaviors, ...summary.metrics.surfaces },
    performance,
  });
}
