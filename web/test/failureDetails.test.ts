// SPDX-License-Identifier: LGPL-2.1-or-later
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { diagnosticBudget, diagnosticCase } from "../scripts/diagnostics.ts";
import { CaseFailureDetails } from "../src/CaseFailureDetails.tsx";
import { timedEntry } from "./fixtures.ts";

const failed = timedEntry().performance!.cases[1]!;

test("diagnostics retain errors and typed evidence without publishing unrelated fields", () => {
  const item = diagnosticCase({
    ...failed,
    error: "Expected a ref",
    cleanup_error: "Cleanup failed",
    evidence: [
      {
        argv: ["flatpak", "install", "a b"],
        exit_status: 0,
        timed_out: false,
        stdout: "output",
        stderr: "error",
        api_calls: ["flatpak_installation_install"],
        signals: ["changed"],
        data: { expected: 1, actual: 0 },
        private_field: "omit me",
      },
    ],
  });
  assert.equal(item.failure_details?.error, "Expected a ref");
  assert.equal(item.failure_details?.cleanup_error, "Cleanup failed");
  const evidence = item.failure_details!.evidence;
  assert.equal(
    evidence.find((record) => record.title.endsWith("Exit status"))?.body,
    "0",
  );
  assert.equal(
    evidence.find((record) => record.title.endsWith("Timed out"))?.body,
    "false",
  );
  assert.match(JSON.stringify(evidence), /flatpak_installation_install/);
  assert.doesNotMatch(JSON.stringify(evidence), /omit me/);
  assert.equal(item.failure_details?.truncated, false);
  assert.equal(
    diagnosticCase({
      ...item,
      status: "passed",
      evidence: [{ stdout: "noise" }],
    }).failure_details,
    undefined,
  );
});

test("oversized diagnostics are bounded and marked, retaining only recent evidence records", () => {
  const item = diagnosticCase({
    ...failed,
    error: "x".repeat(10_000),
    evidence: Array.from({ length: 20 }, (_, i) => ({
      stdout: `${i}:` + "x".repeat(10_000),
    })),
  });
  const details = item.failure_details!;
  assert.equal(details.truncated, true);
  assert.ok(
    details.evidence.some(
      (record) => record.title === "Evidence 20: Standard output",
    ),
  );
  assert.ok(
    details.evidence.every((record) => !/^Evidence [1-8]:/.test(record.title)),
  );
  const bodies = [
    details.error!,
    ...details.evidence.map((record) => record.body),
  ];
  assert.ok(bodies.every((body) => body.length <= 4_012));
  assert.ok(
    bodies.reduce(
      (sum, body) => sum + body.replace(/\n\[truncated\]$/, "").length,
      0,
    ) <= diagnosticBudget,
  );
});

test("case inspector renders escaped failure output, setup errors, truncation and legacy fallback", () => {
  const run = timedEntry();
  const item = diagnosticCase({
    ...failed,
    status: "setup-error",
    error: "<script>alert(1)</script>",
    cleanup_error: "Could not remove installation",
    evidence: [{ stderr: "x".repeat(5_000) }],
  });
  const html = renderToStaticMarkup(
    createElement(CaseFailureDetails, { item, run }),
  );
  assert.match(html, /Setup error for/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /Cleanup error/);
  assert.match(html, /<details><summary>Evidence 1: Standard error/);
  assert.match(html, /Diagnostic output was truncated/);
  assert.match(html, /View CI run and full report artifacts/);
  assert.match(
    renderToStaticMarkup(
      createElement(CaseFailureDetails, { item: failed, run }),
    ),
    /weren&#x27;t recorded/,
  );
  assert.equal(
    renderToStaticMarkup(
      createElement(CaseFailureDetails, {
        item: { ...failed, status: "passed" },
        run,
      }),
    ),
    "",
  );
});
