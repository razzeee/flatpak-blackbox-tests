// SPDX-License-Identifier: LGPL-2.1-or-later
import { createRoot } from "react-dom/client";
import { App } from "./App.tsx";
import { historySchema } from "./history.ts";
import { ThemeSelect } from "./ThemeSelect.tsx";
import { Button } from "./components/ui/button.tsx";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
  EmptyContent,
} from "./components/ui/empty.tsx";
import { Skeleton } from "./components/ui/skeleton.tsx";

const root = createRoot(document.getElementById("root")!);
root.render(
  <div
    className="loading-shell"
    role="status"
    aria-label="Loading coverage history"
  >
    <Skeleton className="h-12 w-64" />
    <Skeleton className="h-40 w-full" />
    <Skeleton className="h-80 w-full" />
    <span className="sr-only">Loading coverage history…</span>
  </div>,
);
async function load() {
  try {
    const response = await fetch(`${import.meta.env.BASE_URL}history.json`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const history = historySchema.parse(await response.json());
    root.render(<App history={history} />);
  } catch {
    root.render(
      <main className="dashboard">
        <ThemeSelect />
        <Empty>
          <EmptyHeader>
            <EmptyTitle>Coverage history could not be loaded</EmptyTitle>
            <EmptyDescription role="alert">
              Check the published history file or try again.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button onClick={() => void load()}>Try again</Button>
            <Button variant="link" asChild>
              <a href="./history.json">Download history</a>
            </Button>
          </EmptyContent>
        </Empty>
      </main>,
    );
  }
}
void load();
