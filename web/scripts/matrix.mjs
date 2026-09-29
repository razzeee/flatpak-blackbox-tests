// SPDX-License-Identifier: LGPL-2.1-or-later
import { readFileSync } from "node:fs";

const config = JSON.parse(
  readFileSync(new URL("../../ci/baselines.json", import.meta.url), "utf8"),
);
const selector = process.env.BASELINE ?? "";
const eventName = process.env.EVENT_NAME ?? "";
const ref = process.env.REF ?? "";
const defaultBranch = process.env.DEFAULT_BRANCH ?? "";
const publishesCoverage =
  eventName === "schedule" ||
  (eventName === "push" && ref === `refs/heads/${defaultBranch}`);

function selectPinned(value) {
  const byCommit = config.baselines.find(
    (baseline) => baseline.commit === value,
  );
  if (byCommit) return byCommit;
  const matches = config.baselines.filter(
    (baseline) => baseline.version === value,
  );
  if (matches.length === 1) return matches[0];
  throw new Error(`Unknown or ambiguous baseline: ${value}`);
}

let entries;
if (publishesCoverage) {
  entries = [
    ...config.baselines.map((baseline) => ({
      track: "pinned",
      baseline: baseline.commit,
      ref: baseline.ref,
    })),
    { track: "upstream", baseline: "", ref: config.current },
  ];
} else if (!selector) {
  entries = [{ track: "upstream", baseline: "", ref: config.current }];
} else {
  const baseline = selectPinned(selector);
  entries = [{ track: "pinned", baseline: baseline.commit, ref: baseline.ref }];
}

console.log(`matrix=${JSON.stringify({ include: entries })}`);
