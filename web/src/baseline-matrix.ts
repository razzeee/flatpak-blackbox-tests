// SPDX-License-Identifier: LGPL-2.1-or-later
import { baselineConfig, resolveBaseline } from "./baselines.ts";

export type CompatibilityMatrixEntry = {
  track: "pinned" | "upstream";
  baseline: string;
  ref: string;
};

export type CompatibilityMatrixInput = {
  eventName: string;
  ref: string;
  defaultBranch: string;
  selector: string;
};

export function buildCompatibilityMatrix({
  eventName,
  ref,
  defaultBranch,
  selector,
}: CompatibilityMatrixInput): CompatibilityMatrixEntry[] {
  const publishesCoverage =
    eventName === "schedule" ||
    (eventName === "push" && ref === `refs/heads/${defaultBranch}`);

  if (publishesCoverage) {
    return [
      ...baselineConfig.baselines.map((baseline) => ({
        track: "pinned" as const,
        baseline: baseline.commit,
        ref: baseline.ref,
      })),
      {
        track: "upstream",
        baseline: "",
        ref: baselineConfig.current,
      },
    ];
  }

  const selection = resolveBaseline(selector);
  return selection.kind === "upstream"
    ? [{ track: "upstream", baseline: "", ref: selection.ref }]
    : [
        {
          track: "pinned",
          baseline: selection.baseline.commit,
          ref: selection.baseline.ref!,
        },
      ];
}
