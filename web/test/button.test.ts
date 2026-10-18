// SPDX-License-Identifier: LGPL-2.1-or-later
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Button } from "../src/components/ui/button.tsx";

test("native buttons default to non-submit while explicit types are preserved", () => {
  assert.match(
    renderToStaticMarkup(createElement(Button, null, "Inspect")),
    /type="button"/,
  );
  assert.match(
    renderToStaticMarkup(createElement(Button, { type: "submit" }, "Save")),
    /type="submit"/,
  );
});

test("composed buttons leave the child type under its control", () => {
  const link = renderToStaticMarkup(
    createElement(
      Button,
      { asChild: true },
      createElement("a", { href: "#cases" }, "Cases"),
    ),
  );
  assert.doesNotMatch(link, /type=/);
  const submit = renderToStaticMarkup(
    createElement(
      Button,
      { asChild: true },
      createElement("button", { type: "submit" }, "Save"),
    ),
  );
  assert.match(submit, /type="submit"/);
});
