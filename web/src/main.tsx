// SPDX-License-Identifier: LGPL-2.1-or-later
import { createRoot } from "react-dom/client";
import { App } from "./App.tsx";
import { historySchema } from "./history.ts";
import "./style.css";

const root = createRoot(document.getElementById("root")!);
async function load() {
  try {
    const response = await fetch(`${import.meta.env.BASE_URL}history.json`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const history = historySchema.parse(await response.json());
    root.render(<App history={history} />);
  } catch {
    root.render(
      <main>
        <h1>Flatpak daily coverage</h1>
        <p role="alert">
          Coverage history could not be loaded. Check the published history file
          or try again.
        </p>
        <button type="button" onClick={() => void load()}>
          Try again
        </button>{" "}
        <a href="./history.json">Download history</a>
      </main>,
    );
  }
}
void load();
