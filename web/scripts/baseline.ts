// SPDX-License-Identifier: LGPL-2.1-or-later
import { parseArgs } from "node:util";
import { resolveBaseline } from "../src/baselines.ts";

try {
  const { values } = parseArgs({ options: { baseline: { type: "string" } } });
  const baseline = resolveBaseline(values.baseline);
  // Version and commit are validated before becoming GitHub Actions env values.
  console.log(`FLATPAK_REFERENCE_COMMIT=${baseline.commit}`);
  console.log(`FLATPAK_BASELINE_VERSION=${baseline.version}`);
  console.log(`FLATPAK_BASELINE_REF=${baseline.ref}`);
} catch (error) {
  console.error(
    `baseline: ${error instanceof Error ? error.message : String(error)}`,
  );
  process.exitCode = 1;
}
