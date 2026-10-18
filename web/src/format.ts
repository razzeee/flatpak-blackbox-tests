// SPDX-License-Identifier: LGPL-2.1-or-later
export function seconds(value: number | null | undefined): string {
  return value == null ? "No timing" : `${value.toFixed(2)}s`;
}

export function signed(value: number | null, unit = "s"): string {
  if (value === null) return "n/a";
  const magnitude = Math.abs(value);
  const precision =
    magnitude === 0 || magnitude >= 0.01
      ? 2
      : Math.min(6, Math.max(3, Math.ceil(-Math.log10(magnitude)) + 2));
  const rounded = Number(value.toFixed(precision));
  const formatted =
    rounded === 0 && value !== 0
      ? value.toExponential(2)
      : magnitude > 0 && magnitude < 0.01
        ? rounded.toFixed(precision).replace(/0+$/, "").replace(/\.$/, "")
        : rounded.toFixed(precision);
  return `${value > 0 ? "+" : ""}${formatted}${unit}`;
}
