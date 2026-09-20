// SPDX-License-Identifier: LGPL-2.1-or-later
import { z } from "zod";
import { caseTimingSchema } from "../src/history.ts";
import { isFailure, type FailureDetails } from "../src/failureDetails.ts";

const resultSchema = caseTimingSchema.omit({ failure_details: true }).extend({
  error: z.string().optional(),
  cleanup_error: z.string().optional(),
  evidence: z.array(z.record(z.string(), z.unknown())).optional(),
});

// Keep history downloads bounded even when commands produce enormous logs.
export const diagnosticBudget = 24_000;
const fieldLimit = 4_000;
const recordLimit = 12;
const fields = [
  ["argv", "Command arguments"],
  ["interface", "Interface"],
  ["exit_status", "Exit status"],
  ["timed_out", "Timed out"],
  ["error", "Error"],
  ["stderr", "Standard error"],
  ["stdout", "Standard output"],
  ["api_calls", "API calls"],
  ["signals", "Signals"],
  ["observation", "Observation"],
  ["data", "Structured data"],
  ["query_network_observation", "Query network observation"],
  ["sideload_network_observation", "Sideload network observation"],
  ["sideload_image_network_observation", "Sideload image network observation"],
] as const;

export function diagnosticCase(raw: unknown) {
  const result = resultSchema.parse(raw);
  const item = caseTimingSchema.parse(raw);
  delete item.failure_details;
  if (!isFailure(result.status)) return item;
  const details: FailureDetails = { evidence: [], truncated: false };
  let remaining = diagnosticBudget;
  function bounded(text: string) {
    const length = Math.min(remaining, fieldLimit);
    remaining -= Math.min(text.length, length);
    if (text.length <= length) return text;
    details.truncated = true;
    return text.slice(0, length) + "\n[truncated]";
  }
  if (result.error !== undefined) details.error = bounded(result.error);
  if (result.cleanup_error !== undefined)
    details.cleanup_error = bounded(result.cleanup_error);
  const evidence = result.evidence ?? [];
  if (evidence.length > recordLimit) details.truncated = true;
  // Spend the budget on the most recent commands first, then display them in
  // execution order. Setup chatter must not crowd out the failing command.
  for (
    let index = evidence.length - 1;
    index >= Math.max(0, evidence.length - recordLimit);
    index--
  ) {
    const record = evidence[index]!;
    const retained: FailureDetails["evidence"] = [];
    for (const [key, label] of fields) {
      const value = record[key];
      if (value === undefined || value === "") continue;
      if (remaining === 0) {
        details.truncated = true;
        continue;
      }
      retained.push({
        title: `Evidence ${index + 1}: ${label}`,
        body: bounded(
          typeof value === "string" ? value : JSON.stringify(value, null, 2),
        ),
      });
    }
    details.evidence.unshift(...retained);
  }
  return { ...item, failure_details: details };
}
