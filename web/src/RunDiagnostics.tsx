// SPDX-License-Identifier: LGPL-2.1-or-later
import { useMemo, useState } from "react";
import { seconds, signed } from "./format.ts";
import { utcDay, type Snapshot } from "./history.ts";
import { timingSeries, verifiedPerformance } from "./performance.ts";
import { RunLink } from "./RunSummary.tsx";
import {
  delta,
  filterCases,
  inventoryComplete,
  outcomeLabels,
  rankCases,
  runAccounting,
  type CaseComparison,
  type CaseSort,
  type OutcomeFilter,
} from "./runComparison.ts";

export function focusSection(id: string) {
  const element = document.getElementById(id);
  element?.scrollIntoView({ block: "start" });
  element?.focus({ preventScroll: true });
}

function Change({ value, unit }: { value: number | null; unit?: string }) {
  return (
    <span
      className={
        value !== null && value > 0
          ? "increase"
          : value !== null && value < 0
            ? "decrease"
            : ""
      }
    >
      {signed(value, unit)}
    </span>
  );
}

function Status({ item }: { item: CaseComparison["after"] }) {
  return item ? (
    <span data-status={item.status}>{outcomeLabels[item.status]}</span>
  ) : (
    <>Not recorded</>
  );
}

export function RunDiagnostics({
  run,
  reference,
  earlier,
  comparisonChoice,
  onComparison,
  rows,
  filter,
  onFilter,
  selectedCase,
  onInspect,
}: {
  run: Snapshot;
  reference?: Snapshot;
  earlier: Snapshot[];
  comparisonChoice: string;
  onComparison: (choice: string) => void;
  rows: CaseComparison[];
  filter: OutcomeFilter;
  onFilter: (status: OutcomeFilter) => void;
  selectedCase?: string;
  onInspect: (key: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<CaseSort>("change");
  const [expanded, setExpanded] = useState(false);
  const effectiveSort = reference ? sort : "duration";
  const filtered = useMemo(
    () => filterCases(rankCases(rows, effectiveSort), filter, query),
    [rows, effectiveSort, filter, query],
  );
  const displayed = expanded ? filtered : filtered.slice(0, 20);
  const currentTotals = runAccounting(run);
  const previousTotals = reference ? runAccounting(reference) : undefined;
  const performance = verifiedPerformance(run);
  const partial = performance && !inventoryComplete(run);
  return (
    <section aria-label="Run diagnostics" className="run-diagnostics">
      <h3>{reference ? "What changed?" : "Slowest cases"}</h3>
      <p>
        Inspecting {utcDay(run.timestamp)} UTC.{" "}
        <RunLink run={run}>Current CI run</RunLink>
      </p>
      <div className="toolbar">
        <label>
          Compare with{" "}
          <select
            value={earlier.length ? comparisonChoice : "none"}
            onChange={(event) => {
              onComparison(event.target.value);
              setExpanded(false);
            }}
          >
            {earlier.length ? (
              <option value="auto">Previous available run</option>
            ) : null}
            <option value="none">No comparison / slowest cases</option>
            {earlier.map((item) => (
              <option key={item.timestamp} value={item.timestamp}>
                {utcDay(item.timestamp)} UTC
              </option>
            ))}
          </select>
        </label>
        {reference ? (
          <RunLink run={reference}>
            Comparison CI run: {utcDay(reference.timestamp)}
          </RunLink>
        ) : null}
      </div>
      {!earlier.length ? (
        <p>
          No earlier run with case data is available for this target. Showing
          current durations.
        </p>
      ) : null}
      {reference && reference.fingerprint !== run.fingerprint ? (
        <p className="data-note">
          The suite definition changed between these runs. Differences may
          reflect changes to the tests.
        </p>
      ) : null}
      {performance ? (
        <>
          <div className="table-scroll">
            <table className="time-accounting">
              <caption>Where the runner's time went</caption>
              <thead>
                <tr>
                  <th scope="col">Measurement</th>
                  {reference ? <th scope="col">Before</th> : null}
                  <th scope="col">Now</th>
                  {reference ? <th scope="col">Change</th> : null}
                </tr>
              </thead>
              <tbody>
                {(
                  [
                    ["total", "Run total"],
                    ["cases", "Recorded case time"],
                    ["outside", "Outside recorded cases"],
                  ] as const
                ).map(([key, label]) => (
                  <tr key={key}>
                    <th scope="row">{label}</th>
                    {reference ? (
                      <td>{seconds(previousTotals?.[key])}</td>
                    ) : null}
                    <td>{seconds(currentTotals[key])}</td>
                    {reference ? (
                      <td>
                        <Change
                          value={delta(
                            previousTotals?.[key],
                            currentTotals[key],
                          )}
                        />
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            Outside recorded cases includes shared preflight, client builds and
            any work without case timings. CI load and outcome changes can
            affect duration.
          </p>
        </>
      ) : (
        <p>No verified case data is available for the selected run.</p>
      )}
      {partial ? (
        <p className="data-note">
          This older snapshot retained only some case details. Outcome counts
          include cases whose names or timings are unavailable.
        </p>
      ) : null}
      {reference && !inventoryComplete(reference) ? (
        <p className="data-note">
          The comparison snapshot has incomplete case details. Missing entries
          are labelled "Not recorded before", not added cases.
        </p>
      ) : null}
      <h4 id="case-results" tabIndex={-1}>
        Cases for {utcDay(run.timestamp)}
        {reference ? ` compared with ${utcDay(reference.timestamp)}` : ""}
      </h4>
      <div className="case-tools">
        <label>
          Search cases{" "}
          <input
            type="search"
            value={query}
            placeholder="Case, driver or profile"
            onChange={(event) => {
              setQuery(event.target.value);
              setExpanded(false);
            }}
          />
        </label>
        <label>
          Sort by{" "}
          <select
            value={effectiveSort}
            onChange={(event) => {
              setSort(event.target.value as CaseSort);
              setExpanded(false);
            }}
          >
            {reference ? <option value="change">Added seconds</option> : null}
            <option value="duration">Current duration</option>
          </select>
        </label>
        {filter !== "all" ? (
          <button type="button" onClick={() => onFilter("all")}>
            Clear {outcomeLabels[filter]} filter
          </button>
        ) : null}
      </div>
      <p role="status">
        Showing {displayed.length} of {filtered.length} recorded cases
        {filter !== "all" ? ` with outcome ${outcomeLabels[filter]}` : ""}.
        {filtered.some((row) => !row.after)
          ? " Includes cases present only in the comparison run."
          : ""}
      </p>
      {filtered.length ? (
        <>
          <p>
            {reference
              ? "Added/removed contributions are labelled separately; missing timings are never zero. Select a case to inspect its history."
              : "Select a case to inspect its timing history."}
          </p>
          <div className="table-scroll">
            <table className="case-comparison">
              <caption>Case timings and outcomes</caption>
              <thead>
                <tr>
                  <th scope="col">Case</th>
                  {reference ? <th scope="col">Added time</th> : null}
                  {reference ? <th scope="col">Before</th> : null}
                  <th scope="col">Now</th>
                  {reference ? (
                    <>
                      <th scope="col">Change</th>
                      <th scope="col">Phase deltas</th>
                    </>
                  ) : null}
                  <th scope="col">Outcome</th>
                  {reference ? <th scope="col">Comparison</th> : null}
                </tr>
              </thead>
              <tbody>
                {displayed.map((row) => {
                  const item = row.after ?? row.before!;
                  return (
                    <tr key={row.key} data-selected={row.key === selectedCase}>
                      <th scope="row">
                        <button
                          className="case-button"
                          type="button"
                          aria-label={`Inspect ${row.label}`}
                          onClick={() => onInspect(row.key)}
                        >
                          {item.behavior_id}
                        </button>
                        <small>
                          {item.driver} / {item.profile}
                        </small>
                      </th>
                      {reference ? (
                        <td>
                          <Change value={row.addedSeconds} />
                        </td>
                      ) : null}
                      {reference ? <td>{seconds(row.beforeSeconds)}</td> : null}
                      <td>{seconds(row.afterSeconds)}</td>
                      {reference ? (
                        <>
                          <td>
                            <Change value={row.percent} unit="%" />
                          </td>
                          <td>
                            {(
                              [
                                "setup_seconds",
                                "execution_seconds",
                                "cleanup_seconds",
                              ] as const
                            ).map((name) => (
                              <div className="phase-delta" key={name}>
                                {timingSeries[name].label}:{" "}
                                <Change value={row.phases[name]} />
                              </div>
                            ))}
                          </td>
                        </>
                      ) : null}
                      <td>
                        {reference ? (
                          <>
                            <Status item={row.before} /> →{" "}
                          </>
                        ) : null}
                        <Status item={row.after} />
                      </td>
                      {reference ? (
                        <td>
                          {row.kind}
                          {row.kind === "Comparable" &&
                          row.beforeSeconds === 0 &&
                          row.afterSeconds !== 0
                            ? " / from 0s"
                            : ""}
                        </td>
                      ) : null}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {filtered.length > 20 ? (
            <button
              type="button"
              className="show-cases"
              onClick={() => setExpanded((value) => !value)}
            >
              {expanded ? "Show top 20" : `Show all ${filtered.length} cases`}
            </button>
          ) : null}
        </>
      ) : (
        <p>
          {partial
            ? "No retained case details match this filter. Check the CI report for omitted cases."
            : "No cases match this filter."}
        </p>
      )}
    </section>
  );
}
