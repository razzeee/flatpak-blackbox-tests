// SPDX-License-Identifier: LGPL-2.1-or-later
import { snapshotSchema, type Snapshot } from "../src/history.ts";

const buildErrorCorrection = "library-client-build-setup-error-v1";

/** Repair classification only. Never manufacture execution or passing credit. */
export function correctSnapshot(snapshot: Snapshot): Snapshot {
  const performance = snapshot.performance;
  if (!performance) return snapshot;
  let changed = 0;
  const cases = performance.cases.map((item) => {
    if (
      item.driver !== "library" ||
      item.status !== "failed" ||
      item.duration_seconds !== undefined ||
      item.timings !== undefined ||
      !item.failure_details?.error?.startsWith(
        "public library client did not compile:",
      ) ||
      item.failure_details.evidence.length !== 0
    )
      return item;
    changed++;
    return { ...item, status: "setup-error" as const };
  });
  if (!changed) return snapshot;
  const statuses = { ...performance.case_statuses };
  if ((statuses.failed ?? 0) < changed)
    throw new Error("Build-error correction exceeds recorded failure count");
  statuses.failed! -= changed;
  if (!statuses.failed) delete statuses.failed;
  statuses["setup-error"] = (statuses["setup-error"] ?? 0) + changed;
  const corrections = [...(snapshot.corrections ?? [])];
  const previous = corrections.find((item) => item.id === buildErrorCorrection);
  if (previous)
    throw new Error(
      "Previously corrected snapshot contains new build failures",
    );
  corrections.push({ id: buildErrorCorrection, changed_cases: changed });
  return snapshotSchema.parse({
    ...snapshot,
    performance: { ...performance, cases, case_statuses: statuses },
    corrections,
  });
}
