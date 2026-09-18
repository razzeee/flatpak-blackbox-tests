// SPDX-License-Identifier: LGPL-2.1-or-later
import { Chart } from "@tanstack/charts/react";
import { useMemo, useState } from "react";
import { performanceChart } from "./chart.ts";
import { utcDay, type Snapshot } from "./history.ts";
import {
  availableCases,
  caseTiming,
  runOutcomes,
  timingNames,
  timingSeries,
  verifiedPerformance,
} from "./performance.ts";

function DurationChart({
  entries,
  caseId,
}: {
  entries: Snapshot[];
  caseId?: string;
}) {
  const definition = useMemo(
    () => performanceChart(entries, caseId),
    [entries, caseId],
  );
  return (
    <Chart
      definition={definition}
      height={300}
      ariaLabel={
        caseId === undefined
          ? "Test run duration in seconds"
          : "Selected case duration in seconds"
      }
    />
  );
}

function seconds(value: number | undefined) {
  return value === undefined ? "No timing" : `${value.toFixed(2)}s`;
}

export function PerformancePanel({ entries }: { entries: Snapshot[] }) {
  const cases = useMemo(() => availableCases(entries), [entries]);
  const [selection, setSelection] = useState("");
  const selected = cases.find((item) => item.key === selection) ?? cases[0];
  const hasRunTiming = entries.some(
    (entry) => verifiedPerformance(entry)?.duration_seconds !== undefined,
  );
  return (
    <section className="chart-section" aria-label="Performance">
      <h2>Performance</h2>
      <p>
        Daily timings from complete, verified reports, including failed cases.
        CI load, case count and failures can affect timings. Older snapshots
        without timings leave gaps.
      </p>
      <h3>Test run duration</h3>
      <p>
        Test runner wall time, including shared preflight and client builds.
        Excludes CI's Flatpak build and fixture preparation.
      </p>
      {hasRunTiming ? (
        <DurationChart entries={entries} />
      ) : (
        <p className="empty">No run timings recorded yet.</p>
      )}
      <h3>Per-case duration</h3>
      {selected ? (
        <>
          <label>
            Case
            <select
              className="case-select"
              value={selected.key}
              onChange={(event) => setSelection(event.target.value)}
            >
              {cases.map((item) => (
                <option value={item.key} key={item.key}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <DurationChart entries={entries} caseId={selected.key} />
          <ul className="legend" aria-label="Timing series">
            {timingNames.map((name) => (
              <li key={name}>
                <span style={{ background: timingSeries[name].color }} />
                {timingSeries[name].label}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="empty">No per-case timings recorded yet.</p>
      )}
      {hasRunTiming || selected ? (
        <details>
          <summary>Daily timings and outcomes</summary>
          <div className="table-scroll">
            <table>
              <caption>
                {selected ? `Case: ${selected.label}. ` : ""}All durations in
                seconds.
              </caption>
              <thead>
                <tr>
                  <th scope="col">UTC day / run</th>
                  <th scope="col">Run duration</th>
                  <th scope="col">Run outcomes</th>
                  {selected ? (
                    <>
                      <th scope="col">Case outcome</th>
                      {timingNames.map((name) => (
                        <th scope="col" key={name}>
                          {timingSeries[name].label}
                        </th>
                      ))}
                    </>
                  ) : null}
                </tr>
              </thead>
              <tbody>
                {[...entries].reverse().map((entry) => {
                  const item = selected
                    ? caseTiming(entry, selected.key)
                    : undefined;
                  return (
                    <tr key={entry.timestamp}>
                      <th scope="row">
                        {entry.run_url.startsWith("https://github.com/") ? (
                          <a href={entry.run_url}>{utcDay(entry.timestamp)}</a>
                        ) : (
                          utcDay(entry.timestamp)
                        )}
                      </th>
                      <td>
                        {seconds(verifiedPerformance(entry)?.duration_seconds)}
                      </td>
                      <td>{runOutcomes(entry)}</td>
                      {selected ? (
                        <>
                          <td>{item?.status ?? "No timing"}</td>
                          {timingNames.map((name) => (
                            <td key={name}>
                              {seconds(
                                name === "duration_seconds"
                                  ? item?.duration_seconds
                                  : item?.timings?.[name],
                              )}
                            </td>
                          ))}
                        </>
                      ) : null}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
    </section>
  );
}
