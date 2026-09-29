// SPDX-License-Identifier: LGPL-2.1-or-later
import { baselineConfig, findBaseline, type Baseline } from "./baselines.ts";
import type { Snapshot } from "./history.ts";

export function baselineKey(baseline: Baseline): string {
  return `pinned:${baseline.commit}`;
}

export function targetKey(entry: Snapshot): string {
  return entry.track === "upstream"
    ? "upstream"
    : `pinned:${entry.target_commit}`;
}

/** Infer only known legacy pins; never relabel historical data as today's baseline. */
export function withBaseline(entry: Snapshot): Snapshot {
  if (entry.track !== "pinned" || entry.baseline) return entry;
  const baseline = findBaseline(entry.target_commit);
  return baseline ? { ...entry, baseline } : entry;
}

export function targetOptions(history: readonly Snapshot[]) {
  const options = new Map<string, string>(
    baselineConfig.baselines.map((baseline) => [
      baselineKey(baseline),
      `Flatpak ${baseline.version}`,
    ]),
  );
  for (const snapshot of history) {
    const entry = withBaseline(snapshot);
    const key = targetKey(entry);
    if (entry.track !== "pinned") continue;
    if (!entry.baseline && options.has(key)) continue;
    const label = entry.baseline
      ? `Flatpak ${entry.baseline.version}`
      : "Pinned commit";
    options.set(key, `${label} / ${entry.target_commit.slice(0, 12)}`);
  }
  const archived = [...options.entries()].sort(([, a], [, b]) =>
    b.localeCompare(a, undefined, { numeric: true }),
  );
  return [
    ...archived.map(([key, label]) => ({ key, label })),
    { key: "upstream", label: "Upstream main" },
  ];
}
