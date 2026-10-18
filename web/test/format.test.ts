// SPDX-License-Identifier: LGPL-2.1-or-later
import assert from "node:assert/strict";
import { test } from "node:test";
import { signed } from "../src/format.ts";

test("signed deltas retain precision when small changes round below a centisecond", () => {
  assert.equal(signed(0.0047), "+0.0047s");
  assert.equal(signed(-0.001), "-0.001s");
  assert.equal(signed(0.01), "+0.01s");
  assert.equal(signed(0), "0.00s");
  assert.equal(signed(null), "n/a");
});

test("extremely small non-zero changes do not display as signed zero", () => {
  assert.equal(signed(0.00000001), "+1.00e-8s");
  assert.equal(signed(-0.00000001), "-1.00e-8s");
});
