// SPDX-License-Identifier: LGPL-2.1-or-later
import { Chart } from "@tanstack/charts/react";
import { useMemo, useState } from "react";
import { coverageChart } from "./chart.ts";
import { PerformancePanel } from "./PerformancePanel.tsx";
import {
  credit,
  daily,
  series,
  seriesNames,
  utcDay,
  type Series,
  type Snapshot,
} from "./history.ts";
import { targetKey, targetOptions } from "./targets.ts";
import { RunSummary } from "./RunSummary.tsx";
import { ThemeSelect } from "./ThemeSelect.tsx";
import { focusSection } from "./RunDiagnostics.tsx";
import type { OutcomeFilter } from "./runComparison.ts";

const behaviors: Series[] = ["cli", "library"];
const surfaces: Series[] = [
  "cli-command",
  "cli-option",
  "library-function",
  "library-signal",
];

function CoverageChart({
  entries,
  names,
  title,
  onSelectDay,
}: {
  entries: Snapshot[];
  names: Series[];
  title: string;
  onSelectDay: (date: string) => void;
}) {
  const [hidden, setHidden] = useState<Series[]>([]);
  const definition = useMemo(
    () =>
      coverageChart(
        entries,
        names.filter((name) => !hidden.includes(name)),
      ),
    [entries, names, hidden],
  );
  const hasEvidence = entries.some((entry) =>
    names.some((name) => credit(entry, name) !== null),
  );
  return (
    <section className="chart-section" aria-label={title}>
      <h2>{title}</h2>
      {hasEvidence ? (
        <Chart
          definition={definition}
          height={300}
          onSelect={(point) => {
            if (point) onSelectDay(point.datum.date);
          }}
          ariaLabel={`${title}, daily passing percentages`}
        />
      ) : (
        <p className="empty">No verified evidence in these runs yet.</p>
      )}
      <ul className="legend" aria-label={`${title} series`}>
        {names.map((name) => (
          <li key={name}>
            <button
              type="button"
              aria-pressed={!hidden.includes(name)}
              onClick={() =>
                setHidden((current) =>
                  current.includes(name)
                    ? current.filter((item) => item !== name)
                    : [...current, name],
                )
              }
            >
              <span style={{ background: series[name].color }} />
              {series[name].label}
            </button>
          </li>
        ))}
      </ul>
      {hidden.length === names.length ? (
        <p role="status">
          All series hidden. Select a legend label to show it.
        </p>
      ) : null}
    </section>
  );
}

function DailyCounts({ entries }: { entries: Snapshot[] }) {
  return (
    <details>
      <summary>Daily counts and run details</summary>
      <div className="table-scroll">
        <table>
          <caption>
            Passing / total. Each run records its own catalogue definition.
          </caption>
          <thead>
            <tr>
              <th scope="col">UTC day / run</th>
              {seriesNames.map((name) => (
                <th scope="col" key={name}>
                  {series[name].label}
                </th>
              ))}
              <th scope="col">Source commits</th>
            </tr>
          </thead>
          <tbody>
            {[...entries].reverse().map((entry) => (
              <tr key={entry.timestamp}>
                <th scope="row">
                  {entry.run_url.startsWith("https://github.com/") ? (
                    <a href={entry.run_url}>{utcDay(entry.timestamp)}</a>
                  ) : (
                    utcDay(entry.timestamp)
                  )}
                  <small>{entry.verification}</small>
                </th>
                {seriesNames.map((name) => {
                  const value = credit(entry, name);
                  return (
                    <td key={name}>
                      {value ? (
                        <>
                          {value.passed}/{value.total}
                          <small>{value.percent.toFixed(2)}%</small>
                        </>
                      ) : (
                        "No evidence"
                      )}
                    </td>
                  );
                })}
                <td>
                  Suite {entry.suite_commit.slice(0, 12)}
                  <br />
                  Target {entry.target_commit.slice(0, 12)}
                  <small>
                    Reported: {entry.target_version ?? "not recorded"}
                  </small>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export function App({ history }: { history: Snapshot[] }) {
  const options = useMemo(() => targetOptions(history), [history]);
  const [selection, setSelection] = useState("");
  const [runSelection, setRunSelection] = useState("");
  const [outcomeFilter, setOutcomeFilter] = useState<OutcomeFilter>("all");
  const selected =
    options.find((item) => item.key === selection) ?? options[0]!;
  const entries = useMemo(
    () => daily(history).filter((entry) => targetKey(entry) === selected.key),
    [history, selected.key],
  );
  const run =
    entries.find((entry) => entry.timestamp === runSelection) ?? entries.at(-1);
  function selectDay(date: string) {
    const entry = entries.find((item) => utcDay(item.timestamp) === date);
    if (entry) {
      setRunSelection(entry.timestamp);
      focusSection("case-results");
    }
  }
  function filterOutcomes(status: OutcomeFilter) {
    setOutcomeFilter(status);
    focusSection("case-results");
  }
  return (
    <main>
      <header>
        <h1>Flatpak daily coverage</h1>
        <p>Passing evidence from public-interface compatibility tests.</p>
      </header>
      <div className="toolbar">
        <label>
          Target{" "}
          <select
            value={selected.key}
            onChange={(event) => {
              setSelection(event.target.value);
              setRunSelection("");
              setOutcomeFilter("all");
            }}
          >
            {options.map((item) => (
              <option key={item.key} value={item.key}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <a href="./history.json">Download history</a>
        <ThemeSelect />
      </div>
      <p>
        Latest complete run per target and UTC day. Gaps mean missing or
        unverified evidence. Percentages describe the catalogue and public
        interface reach; catalogue totals can change.
      </p>
      {run ? (
        <>
          <p className="date-range">
            {utcDay(entries[0]!.timestamp)} to{" "}
            {utcDay(entries.at(-1)!.timestamp)} · {entries.length} recorded days
          </p>
          <RunSummary
            entries={entries}
            run={run}
            onRunChange={setRunSelection}
            filter={outcomeFilter}
            onFilter={filterOutcomes}
          />
          <CoverageChart
            entries={entries}
            names={behaviors}
            title="Catalogued behavior"
            onSelectDay={selectDay}
          />
          <CoverageChart
            entries={entries}
            names={surfaces}
            title="Public interface reach"
            onSelectDay={selectDay}
          />
          <DailyCounts entries={entries} />
          <PerformancePanel
            entries={entries}
            key={selected.key}
            run={run}
            filter={outcomeFilter}
            onFilter={setOutcomeFilter}
            onSelectDay={selectDay}
          />
        </>
      ) : (
        <p className="empty">
          No recorded runs for {selected.label} yet. History starts with the
          first published CI run.
        </p>
      )}
    </main>
  );
}
