// SPDX-License-Identifier: LGPL-2.1-or-later
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { createServer } from "vite";
import { historySchema } from "../src/history.ts";

const root = resolve(import.meta.dirname, "..");
const history = historySchema.parse(
  JSON.parse(
    await readFile(
      process.env.HISTORY_PATH ?? resolve(root, "public/history.json"),
      "utf8",
    ),
  ),
);
const server = await createServer({
  configFile: resolve(root, "vite.config.ts"),
  root,
  server: { middlewareMode: true },
  appType: "custom",
});

try {
  const { App } = await server.ssrLoadModule("/src/App.tsx");
  const markup = renderToString(createElement(App, { history }));
  const indexPath = resolve(root, "dist/index.html");
  const html = await readFile(indexPath, "utf8");
  const updated = html.replace(
    '<div id="root"><p role="status">Loading coverage history...</p></div>',
    `<div id="root" data-prerendered="true">${markup}</div>`,
  );
  if (updated === html)
    throw new Error("Could not find the root placeholder in built index.html");
  await writeFile(indexPath, updated);
  console.log(
    `Prerendered ${history.length} history entries into dist/index.html`,
  );
} finally {
  await server.close();
}
