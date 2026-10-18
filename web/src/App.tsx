// SPDX-License-Identifier: LGPL-2.1-or-later
import { Chart } from "@tanstack/charts/react";
import { useMemo, useState } from "react";
import { CubeFocusIcon } from "@phosphor-icons/react/dist/csr/CubeFocus";
import { DownloadSimpleIcon } from "@phosphor-icons/react/dist/csr/DownloadSimple";
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
import { RunHealth } from "./RunHealth.tsx";
import { ThemeSelect } from "./ThemeSelect.tsx";
import { focusSection } from "./RunDiagnostics.tsx";
import { defaultOutcomeFilter, type OutcomeFilter } from "./runComparison.ts";
import { DashboardTabs, type DashboardTab } from "./DashboardTabs.tsx";
import { ChartCard } from "./ChartCard.tsx";
import { Disclosure } from "./Disclosure.tsx";
import { Button } from "./components/ui/button.tsx";
import { Field, FieldGroup, FieldLabel } from "./components/ui/field.tsx";
import {
  NativeSelect,
  NativeSelectOption,
} from "./components/ui/native-select.tsx";
import { Separator } from "./components/ui/separator.tsx";
import { ToggleGroup, ToggleGroupItem } from "./components/ui/toggle-group.tsx";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
} from "./components/ui/empty.tsx";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
  TableCaption,
} from "./components/ui/table.tsx";

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
    <ChartCard
      title={title}
      description="Daily passing percentage. Catalogue totals can change."
      legend={
        <ToggleGroup
          type="multiple"
          size="sm"
          className="max-w-full flex-wrap"
          aria-label={`${title} series`}
          value={names.filter((name) => !hidden.includes(name))}
          onValueChange={(visible) =>
            setHidden(names.filter((name) => !visible.includes(name)))
          }
        >
          {names.map((name) => (
            <ToggleGroupItem key={name} value={name}>
              <span
                className="legend-dot"
                style={{ background: series[name].color }}
              />
              {series[name].label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      }
    >
      {hasEvidence ? (
        <Chart
          definition={definition}
          height={210}
          onSelect={(point) => {
            if (point) onSelectDay(point.datum.date);
          }}
          ariaLabel={`${title}, daily passing percentages`}
        />
      ) : (
        <Empty>
          <EmptyHeader>
            <EmptyDescription>
              No verified evidence in these runs yet.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}
      {hidden.length === names.length ? (
        <p role="status">
          All series hidden. Select a legend label to show it.
        </p>
      ) : null}
    </ChartCard>
  );
}

function DailyCounts({ entries }: { entries: Snapshot[] }) {
  return (
    <Disclosure title="Daily counts and run details">
      <Table>
        <TableCaption>
          Passing / total. Each run records its own catalogue definition.
        </TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead scope="col">UTC day / run</TableHead>
            {seriesNames.map((name) => (
              <TableHead scope="col" key={name}>
                {series[name].label}
              </TableHead>
            ))}
            <TableHead scope="col">Source commits</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {[...entries].reverse().map((entry) => (
            <TableRow key={entry.timestamp}>
              <TableHead scope="row">
                {entry.run_url.startsWith("https://github.com/") ? (
                  <a href={entry.run_url}>{utcDay(entry.timestamp)}</a>
                ) : (
                  utcDay(entry.timestamp)
                )}
                <small>{entry.verification}</small>
              </TableHead>
              {seriesNames.map((name) => {
                const value = credit(entry, name);
                return (
                  <TableCell key={name}>
                    {value ? (
                      <>
                        {value.passed}/{value.total}
                        <small>{value.percent.toFixed(2)}%</small>
                      </>
                    ) : (
                      "No evidence"
                    )}
                  </TableCell>
                );
              })}
              <TableCell>
                Suite {entry.suite_commit.slice(0, 12)}
                <br />
                Target {entry.target_commit.slice(0, 12)}
                <small>
                  Reported: {entry.target_version ?? "not recorded"}
                </small>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Disclosure>
  );
}

export function App({ history }: { history: Snapshot[] }) {
  const options = useMemo(() => targetOptions(history), [history]);
  const [selection, setSelection] = useState(() =>
    history.some((entry) => entry.track === "upstream") ? "upstream" : "",
  );
  const [runSelection, setRunSelection] = useState("");
  const [outcomeChoice, setOutcomeChoice] = useState<{
    target: string;
    timestamp: string;
    value: OutcomeFilter;
  }>();
  const [tab, setTab] = useState<DashboardTab>("trends");
  const selected =
    options.find((item) => item.key === selection) ?? options[0]!;
  const entries = useMemo(
    () => daily(history).filter((entry) => targetKey(entry) === selected.key),
    [history, selected.key],
  );
  const run =
    entries.find((entry) => entry.timestamp === runSelection) ?? entries.at(-1);
  const outcomeFilter =
    outcomeChoice?.target === selected.key &&
    outcomeChoice.timestamp === run?.timestamp
      ? outcomeChoice.value
      : defaultOutcomeFilter(run);
  function setOutcomeFilter(value: OutcomeFilter) {
    if (run)
      setOutcomeChoice({
        target: selected.key,
        timestamp: run.timestamp,
        value,
      });
  }
  function showCases() {
    setTab("cases");
    requestAnimationFrame(() => focusSection("case-results"));
  }
  function selectDay(date: string) {
    const entry = entries.find((item) => utcDay(item.timestamp) === date);
    if (entry) {
      setRunSelection(entry.timestamp);
      showCases();
    }
  }
  function filterOutcomes(status: OutcomeFilter) {
    setOutcomeFilter(status);
    showCases();
  }
  const targetControl = (
    <Field orientation="horizontal">
      <FieldLabel htmlFor="target">Target</FieldLabel>
      <NativeSelect
        id="target"
        value={selected.key}
        onChange={(event) => {
          setSelection(event.target.value);
          setRunSelection("");
          setOutcomeChoice(undefined);
        }}
      >
        {options.map((item) => (
          <NativeSelectOption key={item.key} value={item.key}>
            {item.label}
          </NativeSelectOption>
        ))}
      </NativeSelect>
    </Field>
  );
  return (
    <main className="dashboard">
      <header className="masthead">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            <CubeFocusIcon weight="light" />
          </div>
          <div>
            <span className="eyebrow">
              PUBLIC INTERFACE / COMPATIBILITY OBSERVATORY
            </span>
            <h1>Flatpak daily coverage</h1>
          </div>
        </div>
        <div className="masthead-actions">
          <span className="subtitle">Evidence, not assumptions.</span>
          <ThemeSelect />
        </div>
      </header>
      <Separator />
      {run ? (
        <>
          <RunSummary
            controls={targetControl}
            entries={entries}
            run={run}
            onRunChange={setRunSelection}
            onFilter={filterOutcomes}
          />
          <DashboardTabs
            value={tab}
            onChange={setTab}
            range={`${entries.length} recorded days / UTC`}
          >
            <PerformancePanel
              activeTab={tab}
              entries={entries}
              key={selected.key}
              run={run}
              filter={outcomeFilter}
              onFilter={setOutcomeFilter}
              onSelectDay={selectDay}
              evidence={
                <>
                  <div className="section-heading">
                    <h2>Evidence & provenance</h2>
                    <p>
                      {utcDay(entries[0]!.timestamp)} to{" "}
                      {utcDay(entries.at(-1)!.timestamp)} · Latest complete run
                      per target and UTC day.
                    </p>
                  </div>
                  <RunHealth key={selected.key} entries={entries} />
                  <DailyCounts entries={entries} />
                </>
              }
            >
              <div className="chart-grid">
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
              </div>
            </PerformancePanel>
          </DashboardTabs>
        </>
      ) : (
        <>
          <FieldGroup className="scope-fields scope-bar">
            {targetControl}
          </FieldGroup>
          <Empty>
            <EmptyHeader>
              <EmptyTitle>No recorded runs</EmptyTitle>
              <EmptyDescription>
                No recorded runs for {selected.label} yet. History starts with
                the first published CI run.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        </>
      )}
      <footer className="page-footer">
        <span>
          Passing evidence from public-interface tests. Missing measurements are
          never zero.
        </span>
        <Button variant="link" size="sm" asChild>
          <a href="./history.json">
            <DownloadSimpleIcon data-icon="inline-start" />
            Download history JSON
          </a>
        </Button>
      </footer>
    </main>
  );
}
