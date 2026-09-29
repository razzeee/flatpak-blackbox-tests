// SPDX-License-Identifier: LGPL-2.1-or-later
import { buildCompatibilityMatrix } from "../src/baseline-matrix.ts";

const entries = buildCompatibilityMatrix({
  eventName: process.env.EVENT_NAME ?? "",
  ref: process.env.REF ?? "",
  defaultBranch: process.env.DEFAULT_BRANCH ?? "",
  selector: process.env.BASELINE ?? "",
});

console.log(`matrix=${JSON.stringify({ include: entries })}`);
