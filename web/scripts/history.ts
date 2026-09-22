// SPDX-License-Identifier: LGPL-2.1-or-later
import { mkdir, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { parseArgs } from "node:util";
import {
  daily,
  historySchema,
  snapshotSchema,
  trackSchema,
} from "../src/history.ts";
import { optionalJson, readJson, record } from "./record.ts";
import { withBaseline } from "../src/targets.ts";
import { correctSnapshot } from "./corrections.ts";

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    report: { type: "string" },
    track: { type: "string" },
    timestamp: { type: "string" },
    "suite-commit": { type: "string" },
    "target-commit": { type: "string" },
    "run-url": { type: "string" },
    output: { type: "string" },
    snapshot: { type: "string" },
    history: { type: "string" },
  },
});

function required(name: keyof typeof values): string {
  const value = values[name];
  if (typeof value !== "string" || !value) throw new Error(`Missing --${name}`);
  return value;
}

async function save(path: string, value: unknown) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(`${path}.tmp`, JSON.stringify(value, null, 2) + "\n");
  await rename(`${path}.tmp`, path);
}

try {
  if (positionals.length !== 1)
    throw new Error("Usage: history record|update|migrate [options]");
  if (positionals[0] === "record") {
    const output = required("output");
    await save(
      output,
      await record({
        report: required("report"),
        track: trackSchema.parse(required("track")),
        timestamp: required("timestamp"),
        suiteCommit: required("suite-commit"),
        targetCommit: required("target-commit"),
        runUrl: required("run-url"),
      }),
    );
  } else if (positionals[0] === "update") {
    const path = required("history");
    const existing = await optionalJson(path);
    const history = historySchema.parse(existing === undefined ? [] : existing);
    const snapshot = snapshotSchema.parse(await readJson(required("snapshot")));
    await save(
      path,
      daily(history, snapshot).map(correctSnapshot).map(withBaseline),
    );
  } else if (positionals[0] === "migrate") {
    const path = required("history");
    const history = historySchema.parse(await readJson(path));
    const corrected = history.map(correctSnapshot);
    const changed = corrected.filter(
      (item, index) => item !== history[index],
    ).length;
    await save(values.output ?? path, corrected);
    console.error(`Corrected ${changed} coverage snapshots`);
  } else {
    throw new Error("Usage: history record|update|migrate [options]");
  }
} catch (error) {
  console.error(
    `coverage history: ${error instanceof Error ? error.message : String(error)}`,
  );
  process.exitCode = 1;
}
