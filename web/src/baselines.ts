// SPDX-License-Identifier: LGPL-2.1-or-later
import { z } from "zod";
import configuration from "../../ci/baselines.json";

const commitSchema = z.string().regex(/^[0-9a-f]{40}$/);
const refSchema = z.string().regex(/^refs\/tags\/[0-9][0-9A-Za-z.+-]*$/);
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
    current: commitSchema,
    baselines: z.array(baselineDefinitionSchema).min(1),
  })
  .refine(
    (value) => value.baselines.some((item) => item.commit === value.current),
    "Current baseline must have a definition",
  )
  .refine(
    (value) =>
      new Set(value.baselines.map((item) => item.commit)).size ===
      value.baselines.length,
    "Baseline commits must be unique",
  );

export const baselineConfig = baselineConfigSchema.parse(configuration);
export const currentBaseline = baselineConfig.baselines.find(
  (item) => item.commit === baselineConfig.current,
)!;

export function findBaseline(commit: string): Baseline | undefined {
  return baselineConfig.baselines.find((item) => item.commit === commit);
}

/** Manual runs may select a retained tag baseline or its exact source commit. */
export function resolveBaseline(selector = ""): Baseline {
  if (!selector) return currentBaseline;
  const byCommit = findBaseline(selector);
  if (byCommit) return byCommit;
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
  return matches[0]!;
}
