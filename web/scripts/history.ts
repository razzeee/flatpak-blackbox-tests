// SPDX-License-Identifier: LGPL-2.1-or-later
import { mkdir, readdir, rename, unlink, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { parseArgs } from "node:util";
import {
  daily,
  historySchema,
  snapshotSchema,
  trackSchema,
  utcDay,
  type Snapshot,
} from "../src/history.ts";
import { optionalJson, readJson, record } from "./record.ts";
import { withBaseline } from "../src/targets.ts";

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    report: { type: "string" },
    track: { type: "string" },
    timestamp: { type: "string" },
    "suite-commit": { type: "string" },
    "target-commit": { type: "string" },
    "run-url": { type: "string" },
    "workflow-event": { type: "string" },
    "workflow-created-at": { type: "string" },
    output: { type: "string" },
    snapshot: { type: "string" },
    history: { type: "string" },
    "history-dir": { type: "string" },
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
    throw new Error("Usage: history record|update|split|export [options]");
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
        workflow:
          values["workflow-event"] || values["workflow-created-at"]
            ? {
                event: required("workflow-event"),
                created_at: required("workflow-created-at"),
              }
            : undefined,
      }),
    );
  } else if (positionals[0] === "update") {
    const snapshot = snapshotSchema.parse(await readJson(required("snapshot")));
    const path = values["history-dir"]
      ? join(values["history-dir"], `${utcDay(snapshot.timestamp)}.json`)
      : required("history");
    const existing = await optionalJson(path);
    const history = historySchema.parse(existing === undefined ? [] : existing);
    await save(path, daily(history, snapshot).map(withBaseline));
  } else if (positionals[0] === "split") {
    const path = required("history");
    const directory = required("history-dir");
    const existing = await optionalJson(path);
    await mkdir(directory, { recursive: true });
    if (existing !== undefined) {
      const groups = new Map<string, Snapshot[]>();
      for (const snapshot of historySchema.parse(existing)) {
        const day = utcDay(snapshot.timestamp);
        const group = groups.get(day) ?? [];
        group.push(snapshot);
        groups.set(day, group);
      }
      for (const [day, snapshots] of groups) {
        const shard = join(directory, `${day}.json`);
        let history = historySchema.parse((await optionalJson(shard)) ?? []);
        for (const snapshot of snapshots) history = daily(history, snapshot);
        await save(shard, history.map(withBaseline));
      }
      await unlink(path);
    }
  } else if (positionals[0] === "export") {
    const directory = required("history-dir");
    const history: Snapshot[] = [];
    for (const file of (await readdir(directory)).sort()) {
      if (!/^\d{4}-\d{2}-\d{2}\.json$/.test(file)) continue;
      history.push(
        ...historySchema.parse(await readJson(join(directory, file))),
      );
    }
    await save(required("output"), history);
  } else {
    throw new Error("Usage: history record|update|split|export [options]");
  }
} catch (error) {
  console.error(
    `coverage history: ${error instanceof Error ? error.message : String(error)}`,
  );
  process.exitCode = 1;
}
