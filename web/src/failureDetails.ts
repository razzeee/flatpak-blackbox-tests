// SPDX-License-Identifier: LGPL-2.1-or-later
import { z } from "zod";

export const failureDetailsSchema = z.object({
  error: z.string().optional(),
  cleanup_error: z.string().optional(),
  evidence: z.array(z.object({ title: z.string(), body: z.string() })),
  truncated: z.boolean(),
});

export type FailureDetails = z.infer<typeof failureDetailsSchema>;

export function isFailure(status: string) {
  return status === "failed" || status === "setup-error";
}
