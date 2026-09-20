// SPDX-License-Identifier: LGPL-2.1-or-later
import { Chart } from "@tanstack/charts/react";
import { useMemo, useState } from "react";
import { performanceChart } from "./chart.ts";
import { utcDay, type Snapshot } from "./history.ts";
import { seconds } from "./format.ts";
import { RunDiagnostics, focusSection } from "./RunDiagnostics.tsx";
import { CaseFailureDetails } from "./CaseFailureDetails.tsx";
import {
  caseOptions,
  caseRecord,
  caseSeconds,
  compareRuns,
  earlierRuns,
  rankCases,
  outcomeLabels,
  type OutcomeFilter,
} from "./runComparison.ts";
import {
  runOutcomes,
  timingNames,
  timingSeries,
  verifiedPerformance,
} from "./performance.ts";

function DurationChart({
  entries,
  caseId,
  onSelectDay,
}: {
  entries: Snapshot[];
  caseId?: string;
  onSelectDay?: (date: string) => void;
}) {
  const definition = useMemo(
    () => performanceChart(entries, caseId),
    [entries, caseId],
  );
  return (
    <Chart
      definition={definition}
      height={300}
      onSelect={(point) => {
        if (point) onSelectDay?.(point.datum.date);
      }}
      ariaLabel={
        caseId === undefined
          ? "Test run duration in seconds"
          : "Selected case duration in seconds"
      }
    />
  );
}

export function PerformancePanel({
  entries,
  run = entries.at(-1)!,
  filter = "all",
  onFilter = () => {},
  onSelectDay,
}: {
  entries: Snapshot[];
  run?: Snapshot;
  filter?: OutcomeFilter;
  onFilter?: (status: OutcomeFilter) => void;
  onSelectDay?: (date: string) => void;
}) {
  const cases = useMemo(() => caseOptions(entries), [entries]);
  const earlier = useMemo(() => earlierRuns(entries, run), [entries, run]);
  const [comparison, setComparison] = useState<{
    run: string;
    value: string;
  }>();
  const choice = comparison?.run === run.timestamp ? comparison.value : "auto";
  const reference =
    choice === "none"
      ? undefined
      : (earlier.find((item) => item.timestamp === choice) ?? earlier[0]);
  const rows = useMemo(() => compareRuns(run, reference), [run, reference]);
  const recommended = useMemo(
    () => rankCases(rows, reference ? "change" : "duration")[0]?.key,
    [rows, reference],
  );
  const [selection, setSelection] = useState("");
  const selected =
    cases.find((item) => item.key === selection) ??
    cases.find((item) => item.key === recommended) ??
    cases[0];
  const hasRunTiming = entries.some(
    (entry) => verifiedPerformance(entry)?.duration_seconds !== undefined,
  );
  return (
    <section className="chart-section" aria-label="Performance">
      <h2>Performance</h2>
      <p>
        Daily timings from complete, verified reports, including failed cases.
        Select a chart point or recorded run to investigate. Older snapshots
        without timings leave gaps.
      </p>
      <h3>Test run duration</h3>
      <p>
        Test runner wall time, including shared preflight and client builds.
        Excludes CI's Flatpak build and fixture preparation.
      </p>
      {hasRunTiming ? (
        <DurationChart entries={entries} onSelectDay={onSelectDay} />
      ) : (
        <p className="empty">No run timings recorded yet.</p>
      )}
      <RunDiagnostics
        run={run}
        reference={reference}
        earlier={earlier}
        comparisonChoice={choice}
        onComparison={(value) => setComparison({ run: run.timestamp, value })}
        rows={rows}
        filter={filter}
        onFilter={onFilter}
        selectedCase={selected?.key}
        onInspect={(key) => {
          setSelection(key);
          focusSection("case-history");
        }}
      />
      <h3 id="case-history" tabIndex={-1}>
        Case details and history
      </h3>
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
          <CaseFailureDetails item={caseRecord(run, selected.key)} run={run} />
          {entries.some((entry) => {
            const item = caseRecord(entry, selected.key);
            return timingNames.some((name) => caseSeconds(item, name) !== null);
          }) ? (
            <DurationChart
              entries={entries}
              caseId={selected.key}
              onSelectDay={onSelectDay}
            />
          ) : (
            <p>
              This case has no recorded timings. Its outcomes are listed below.
            </p>
          )}
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
                    ? caseRecord(entry, selected.key)
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
                          <td>
                            {item ? outcomeLabels[item.status] : "Not recorded"}
                          </td>
                          {timingNames.map((name) => (
                            <td key={name}>
                              {seconds(caseSeconds(item, name))}
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
