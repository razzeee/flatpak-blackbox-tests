// SPDX-License-Identifier: LGPL-2.1-or-later
import { lineY } from "@tanstack/charts/line";
import { scaleLinear } from "@tanstack/charts/scales/linear";
import { defineChart } from "@tanstack/charts/scene";
import { tooltip } from "@tanstack/charts/tooltip";
import {
  chartRows,
  dayMilliseconds,
  series,
  utcDay,
  type Series,
  type Snapshot,
} from "./history.ts";
import { timingRows, timingSeries, timingNames } from "./performance.ts";

function dateScale(entries: readonly Snapshot[]) {
  const days = entries.map(
    (entry) => Date.parse(utcDay(entry.timestamp)) / dayMilliseconds,
  );
  const first = days.length ? Math.min(...days) : 0;
  const last = days.length ? Math.max(...days) : 0;
  return {
    scale: scaleLinear().domain(
      first === last ? [first - 1, last + 1] : [first, last],
    ),
    axis: {
      ticks: {
        values: [
          ...new Set(
            Array.from(
              { length: 4 },
              (_, index) => first + Math.round(((last - first) * index) / 3),
            ),
          ),
        ],
        format: (value: number) =>
          new Date(value * dayMilliseconds).toISOString().slice(5, 10),
      },
    },
  };
}

export function coverageChart(
  entries: readonly Snapshot[],
  names: readonly Series[],
) {
  return defineChart({
    marks: names.map((name) =>
      lineY(chartRows(entries, name), {
        id: name,
        x: "day",
        y: "percent",
        z: "label",
        key: "date",
        points: true,
        stroke: series[name].color,
      }),
    ),
    scales: {
      x: dateScale(entries),
      y: {
        scale: scaleLinear().domain([0, 100]),
        grid: true,
        axis: { ticks: { count: 5, format: (value) => `${value}%` } },
      },
    },
    focus: "group-x",
    tooltip: {
      use: tooltip,
      formatGroup: (points) =>
        points
          .map(
            ({ datum }) =>
              `${datum.date}: ${datum.label} ${datum.passed}/${datum.total} (${datum.percent?.toFixed(2)}%)`,
          )
          .join("\n"),
    },
  });
}

export function performanceChart(entries: readonly Snapshot[], key?: string) {
  const names = key === undefined ? ["duration_seconds" as const] : timingNames;
  const rows = names.map((name) => ({
    name,
    data: timingRows(entries, name, key),
  }));
  const maximum = Math.max(
    1,
    ...rows.flatMap(({ data }) => data.map((row) => row.seconds ?? 0)),
  );
  return defineChart({
    marks: rows.map(({ name, data }) =>
      lineY(data, {
        id: name,
        x: "day",
        y: "seconds",
        z: "label",
        key: "date",
        points: true,
        stroke: timingSeries[name].color,
      }),
    ),
    scales: {
      x: dateScale(entries),
      y: {
        scale: scaleLinear().domain([0, maximum]),
        nice: true,
        grid: true,
        axis: { ticks: { count: 5, format: (value) => `${value}s` } },
      },
    },
    focus: "group-x",
    tooltip: {
      use: tooltip,
      formatGroup: (points) =>
        [
          `${points[0]?.datum.date}: ${points[0]?.datum.outcome}`,
          ...points.map(
            ({ datum }) => `${datum.label}: ${datum.seconds?.toFixed(2)}s`,
          ),
        ].join("\n"),
    },
  });
}
