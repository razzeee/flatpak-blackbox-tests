// SPDX-License-Identifier: LGPL-2.1-or-later
import { z } from "zod";
import configuration from "../../ci/baselines.json";

const commitSchema = z.string().regex(/^[0-9a-f]{40}$/);
const refSchema = z.string().regex(/^refs\/tags\/[0-9][0-9A-Za-z.+-]*$/);
const currentRefSchema = z.literal("refs/heads/main");
export const baselineSchema = z.object({
  version: z.string().regex(/^[0-9][0-9A-Za-z.+-]*$/),
  commit: commitSchema,
  // Optional so archived snapshots from the old schema remain readable.
  ref: refSchema.optional(),
});
export type Baseline = z.infer<typeof baselineSchema>;
const baselineDefinitionSchema = baselineSchema.extend({ ref: refSchema });

export const baselineConfigSchema = z
  .object({
    schema: z.literal(1),
    current: currentRefSchema,
    baselines: z.array(baselineDefinitionSchema).min(1),
  })
  .refine(
    (value) =>
      new Set(value.baselines.map((item) => item.commit)).size ===
      value.baselines.length,
    "Baseline commits must be unique",
  );

export const baselineConfig = baselineConfigSchema.parse(configuration);
// Used to infer legacy pinned snapshots; the default target is baselineConfig.current.
export const latestPinnedBaseline = baselineConfig.baselines[0]!;

export function findBaseline(commit: string): Baseline | undefined {
  return baselineConfig.baselines.find((item) => item.commit === commit);
}

export type BaselineSelection =
  { kind: "upstream"; ref: string } | { kind: "pinned"; baseline: Baseline };

/** Manual runs default to moving main or select a retained tag baseline. */
export function resolveBaseline(selector = ""): BaselineSelection {
  if (!selector) return { kind: "upstream", ref: baselineConfig.current };
  const byCommit = findBaseline(selector);
  if (byCommit) return { kind: "pinned", baseline: byCommit };
  const matches = baselineConfig.baselines.filter(
    (item) => item.version === selector,
  );
  if (matches.length !== 1) {
    throw new Error(
      matches.length
        ? "Ambiguous baseline version; select its commit"
        : `Unknown baseline ${selector}; add its definition to ci/baselines.json`,
    );
  }
  return { kind: "pinned", baseline: matches[0]! };
}
