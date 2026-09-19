// SPDX-License-Identifier: LGPL-2.1-or-later
export function seconds(value: number | null | undefined): string {
  return value == null ? "No timing" : `${value.toFixed(2)}s`;
}

export function signed(value: number | null, unit = "s"): string {
  return value === null
    ? "n/a"
    : `${value > 0 ? "+" : ""}${value.toFixed(2)}${unit}`;
}
