// SPDX-License-Identifier: LGPL-2.1-or-later
import {
  seriesNames,
  type CaseTiming,
  type Snapshot,
  type Track,
} from "../src/history.ts";
import { currentBaseline } from "../src/baselines.ts";

export function entry(
  timestamp = "2026-09-17T21:00:00Z",
  track: Track = "pinned",
): Snapshot {
  return {
    schema: 1,
    track,
    timestamp,
    complete: true,
    verification: "current",
    suite_commit: "a".repeat(40),
    target_commit: track === "pinned" ? currentBaseline.commit : "b".repeat(40),
    ...(track === "pinned"
      ? {
          baseline: { ...currentBaseline },
          target_version: `Flatpak ${currentBaseline.version}`,
        }
      : {}),
    run_url: "https://github.com/example/suite/actions/runs/123",
    fingerprint: "c".repeat(64),
    metrics: Object.fromEntries(
      seriesNames.map((name) => [
        name,
        {
          total: 10,
          implemented: 9,
          implemented_percent: 90,
          passed: 8,
          passed_percent: 80,
        },
      ]),
    ),
  };
}

export function timedEntry(
  timestamp?: string,
  track: Track = "pinned",
): Snapshot {
  return {
    ...entry(timestamp, track),
    performance: {
      duration_seconds: 430,
      case_statuses: { passed: 1, failed: 1, "not-selected": 2 },
      cases: [
        {
          behavior_id: "lifecycle.user",
          driver: "cli",
          profile: "user",
          status: "passed",
          duration_seconds: 8,
          timings: {
            setup_seconds: 1,
            execution_seconds: 6,
            cleanup_seconds: 1,
          },
        },
        {
          behavior_id: "lifecycle.user",
          driver: "library",
          profile: "user",
          status: "failed",
          duration_seconds: 12,
          timings: {
            setup_seconds: 2,
            execution_seconds: 10,
            cleanup_seconds: 0,
          },
        },
      ],
    },
  };
}

export function completeEntry(
  timestamp: string,
  cases: CaseTiming[],
  duration = 100,
): Snapshot {
  const counts: Record<string, number> = {};
  for (const item of cases)
    counts[item.status] = (counts[item.status] ?? 0) + 1;
  return {
    ...entry(timestamp),
    performance: {
      duration_seconds: duration,
      case_statuses: counts,
      cases,
      cases_complete: true,
    },
  };
}
