// SPDX-License-Identifier: LGPL-2.1-or-later
import { useEffect, useState } from "react";
import { Field, FieldLabel } from "./components/ui/field.tsx";
import {
  NativeSelect,
  NativeSelectOption,
} from "./components/ui/native-select.tsx";

export function ThemeSelect() {
  const [theme, setTheme] = useState(
    () =>
      (typeof document !== "undefined" &&
        document.documentElement.dataset.theme) ||
      "system",
  );
  useEffect(() => {
    const preference = matchMedia("(prefers-color-scheme: dark)");
    function apply() {
      document.documentElement.classList.toggle(
        "dark",
        theme === "dark" || (theme === "system" && preference.matches),
      );
      if (theme === "system") delete document.documentElement.dataset.theme;
      else document.documentElement.dataset.theme = theme;
    }
    apply();
    preference.addEventListener("change", apply);
    return () => preference.removeEventListener("change", apply);
  }, [theme]);
  return (
    <Field orientation="horizontal" className="theme-select">
      <FieldLabel htmlFor="theme" className="sr-only">
        Theme
      </FieldLabel>
      <NativeSelect
        id="theme"
        value={theme}
        onChange={(event) => {
          const value = event.target.value;
          setTheme(value);
          try {
            localStorage.setItem("coverage-theme-v1", value);
          } catch {
            /* Theme still works without storage. */
          }
        }}
      >
        <NativeSelectOption value="system">System</NativeSelectOption>
        <NativeSelectOption value="dark">Dark</NativeSelectOption>
        <NativeSelectOption value="light">Light</NativeSelectOption>
      </NativeSelect>
    </Field>
  );
}
