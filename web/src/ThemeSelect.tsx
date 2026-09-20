// SPDX-License-Identifier: LGPL-2.1-or-later
import { useState } from "react";

export function ThemeSelect() {
  const [theme, setTheme] = useState(
    () =>
      (typeof document !== "undefined" &&
        document.documentElement.dataset.theme) ||
      "system",
  );
  return (
    <label className="theme-select">
      Theme
      <select
        value={theme}
        onChange={(event) => {
          const value = event.target.value;
          setTheme(value);
          if (value === "system") {
            delete document.documentElement.dataset.theme;
          } else {
            document.documentElement.dataset.theme = value;
          }
          try {
            localStorage.setItem("coverage-theme-v1", value);
          } catch {
            // The selection still works when storage is unavailable.
          }
        }}
      >
        <option value="system">System</option>
        <option value="dark">Dark</option>
        <option value="light">Light</option>
      </select>
    </label>
  );
}
