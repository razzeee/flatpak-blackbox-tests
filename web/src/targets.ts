// SPDX-License-Identifier: LGPL-2.1-or-later
import { currentBaseline, findBaseline, type Baseline } from "./baselines.ts";
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

export function targetOptions(
  history: readonly Snapshot[],
  active = currentBaseline,
) {
  const current = baselineKey(active);
  const options = new Map<string, string>([
    [current, `Flatpak ${active.version} / current baseline`],
  ]);
  for (const snapshot of history) {
    const entry = withBaseline(snapshot);
    const key = targetKey(entry);
    if (entry.track !== "pinned" || key === current) continue;
    if (!entry.baseline && options.has(key)) continue;
    const label = entry.baseline
      ? `Flatpak ${entry.baseline.version}`
      : "Pinned commit";
    options.set(key, `${label} / ${entry.target_commit.slice(0, 12)}`);
  }
  const archived = [...options.entries()]
    .filter(([key]) => key !== current)
    .sort(([, a], [, b]) => b.localeCompare(a, undefined, { numeric: true }));
  return [
    { key: current, label: options.get(current)! },
    ...archived.map(([key, label]) => ({ key, label })),
    { key: "upstream", label: "Upstream main" },
  ];
}
