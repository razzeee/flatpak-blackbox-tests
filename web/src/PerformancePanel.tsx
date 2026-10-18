// SPDX-License-Identifier: LGPL-2.1-or-later
import { Chart } from "@tanstack/charts/react";
import { useMemo, useRef, useState, type ReactNode } from "react";
import { outcomeChart, performanceChart } from "./chart.ts";
import { utcDay, type Snapshot } from "./history.ts";
import { seconds } from "./format.ts";
import { Change, RunDiagnostics } from "./RunDiagnostics.tsx";
import { CaseFailureDetails } from "./CaseFailureDetails.tsx";
import { OutcomeBadge } from "./OutcomeBadge.tsx";
import { ChartCard } from "./ChartCard.tsx";
import { Disclosure } from "./Disclosure.tsx";
import type { DashboardTab } from "./DashboardTabs.tsx";
import {
  caseOptions,
  caseRecord,
  caseSeconds,
  compareRuns,
  earlierRuns,
  rankCases,
  outcomeLabels,
  type CaseComparison,
  type OutcomeFilter,
} from "./runComparison.ts";
import {
  runOutcomes,
  outcomeNames,
  outcomeSeries,
  timingNames,
  timingSeries,
  verifiedPerformance,
} from "./performance.ts";
import { TabsContent } from "./components/ui/tabs.tsx";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "./components/ui/sheet.tsx";
import { Field, FieldLabel } from "./components/ui/field.tsx";
import {
  NativeSelect,
  NativeSelectOption,
} from "./components/ui/native-select.tsx";
import { Alert, AlertDescription } from "./components/ui/alert.tsx";
import {
  Empty,
  EmptyHeader,
  EmptyDescription,
} from "./components/ui/empty.tsx";
import {
  Table,
  TableHeader,
  TableBody,
  TableCaption,
  TableHead,
  TableRow,
  TableCell,
} from "./components/ui/table.tsx";

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
      height={210}
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

export function CaseHistory({
  entries,
  run,
  caseId,
  comparison,
  onSelectDay,
}: {
  entries: Snapshot[];
  run: Snapshot;
  caseId?: string;
  comparison?: CaseComparison;
  onSelectDay?: (date: string) => void;
}) {
  const selected = caseId
    ? caseOptions(entries).find((item) => item.key === caseId)
    : undefined;
  const item = caseId ? caseRecord(run, caseId) : undefined;
  return (
    <>
      {selected ? (
        <>
          <div>
            <h2 className="sheet-case-name">
              {item?.behavior_id ?? selected.label}
            </h2>
            <div className="inspector-meta">
              <OutcomeBadge status={item?.status} />
              <span className="view-description">
                {item
                  ? `${item.driver} / ${item.profile}`
                  : "Not recorded in this run"}
              </span>
            </div>
          </div>
          {!item ? (
            <Alert>
              <AlertDescription>
                This case was not recorded in the selected run. Historical
                results are shown below; missing entries are not zero.
              </AlertDescription>
            </Alert>
          ) : null}
          <CaseFailureDetails item={item} run={run} />
          <section className="inspector-section">
            <h3>Timing breakdown</h3>
            <dl className="phase-list">
              {timingNames.map((name) => (
                <div key={name}>
                  <dt>{timingSeries[name].label}</dt>
                  <dd>
                    {seconds(caseSeconds(item, name))}
                    {comparison ? (
                      <small>
                        Change: <Change value={comparison.phases[name]} />
                      </small>
                    ) : null}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
          {comparison ? (
            <Alert>
              <AlertDescription>
                {comparison.kind} · Before: {seconds(comparison.beforeSeconds)}{" "}
                (
                {comparison.before
                  ? outcomeLabels[comparison.before.status]
                  : "Not recorded"}
                ) → Now: {seconds(comparison.afterSeconds)}.{" "}
                {comparison.kind === "Comparable" &&
                comparison.beforeSeconds === 0 &&
                comparison.afterSeconds !== 0
                  ? "From 0s; no percentage is calculated."
                  : ""}
              </AlertDescription>
            </Alert>
          ) : null}
          <section className="inspector-section">
            <h3>Duration over time</h3>
            {entries.some((entry) =>
              timingNames.some(
                (name) =>
                  caseSeconds(caseRecord(entry, selected.key), name) !== null,
              ),
            ) ? (
              <DurationChart
                entries={entries}
                caseId={selected.key}
                onSelectDay={onSelectDay}
              />
            ) : (
              <p className="view-description">
                This case has no recorded timings. Its outcomes are listed
                below.
              </p>
            )}
            <ul className="legend" aria-label="Timing series">
              {timingNames.map((name) => (
                <li key={name}>
                  <span
                    className="legend-dot"
                    style={{ background: timingSeries[name].color }}
                  />
                  {timingSeries[name].label}
                </li>
              ))}
            </ul>
          </section>
        </>
      ) : (
        <Empty>
          <EmptyHeader>
            <EmptyDescription>
              No per-case timings recorded yet.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}
      <Disclosure title="Daily timings and outcomes">
        <Table>
          <TableCaption>
            {selected ? `Case: ${selected.label}. ` : ""}All durations in
            seconds.
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">UTC day / run</TableHead>
              <TableHead scope="col">Run duration</TableHead>
              <TableHead scope="col">Run outcomes</TableHead>
              {selected ? (
                <>
                  <TableHead scope="col">Case outcome</TableHead>
                  {timingNames.map((name) => (
                    <TableHead scope="col" key={name}>
                      {timingSeries[name].label}
                    </TableHead>
                  ))}
                </>
              ) : null}
            </TableRow>
          </TableHeader>
          <TableBody>
            {[...entries].reverse().map((entry) => {
              const record = caseId ? caseRecord(entry, caseId) : undefined;
              return (
                <TableRow key={entry.timestamp}>
                  <TableHead scope="row">
                    {entry.run_url.startsWith("https://github.com/") ? (
                      <a href={entry.run_url}>{utcDay(entry.timestamp)}</a>
                    ) : (
                      utcDay(entry.timestamp)
                    )}
                  </TableHead>
                  <TableCell>
                    {seconds(verifiedPerformance(entry)?.duration_seconds)}
                  </TableCell>
                  <TableCell>{runOutcomes(entry)}</TableCell>
                  {selected ? (
                    <>
                      <TableCell>
                        {record ? outcomeLabels[record.status] : "Not recorded"}
                      </TableCell>
                      {timingNames.map((name) => (
                        <TableCell key={name}>
                          {seconds(caseSeconds(record, name))}
                        </TableCell>
                      ))}
                    </>
                  ) : null}
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Disclosure>
    </>
  );
}

export function PerformancePanel({
  entries,
  run = entries.at(-1)!,
  filter = "all",
  onFilter = () => {},
  onSelectDay,
  children,
  activeTab = "cases",
  evidence,
}: {
  entries: Snapshot[];
  run?: Snapshot;
  filter?: OutcomeFilter;
  onFilter?: (status: OutcomeFilter) => void;
  onSelectDay?: (date: string) => void;
  children?: ReactNode;
  activeTab?: DashboardTab;
  evidence?: ReactNode;
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
  const [inspection, setInspection] = useState<{ run: string; key: string }>();
  const trigger = useRef<HTMLElement | undefined>(undefined);
  const inspecting = inspection?.run === run.timestamp;
  const selected =
    cases.find((item) => item.key === inspection?.key) ??
    cases.find((item) => item.key === recommended) ??
    cases[0];
  const hasRunTiming = entries.some(
    (entry) => verifiedPerformance(entry)?.duration_seconds !== undefined,
  );
  const hasOutcomes = entries.some(
    (entry) => verifiedPerformance(entry)?.case_statuses !== undefined,
  );
  return (
    <section aria-label="Run investigation">
      <TabsContent
        value="cases"
        id="panel-cases"
        aria-labelledby="tab-cases"
        forceMount
        hidden={activeTab !== "cases"}
      >
        <RunDiagnostics
          run={run}
          reference={reference}
          earlier={earlier}
          comparisonChoice={choice}
          onComparison={(value) => setComparison({ run: run.timestamp, value })}
          rows={rows}
          filter={filter}
          onFilter={onFilter}
          selectedCase={inspecting ? selected?.key : undefined}
          onInspect={(key, element) => {
            trigger.current = element;
            setInspection({ run: run.timestamp, key });
          }}
        />
      </TabsContent>
      <TabsContent
        value="trends"
        id="panel-trends"
        aria-labelledby="tab-trends"
        forceMount
        hidden={activeTab !== "trends"}
      >
        <div className="section-heading">
          <h2>Coverage & performance</h2>
          <p>
            Daily verified evidence. Gaps mean missing measurements, not zero.
            Select a chart point to investigate that run in Cases.
          </p>
        </div>
        <div className="chart-grid">
          <ChartCard
            title="Test run duration"
            description="Runner wall time, including shared preflight and client builds. Excludes CI build and fixture preparation."
          >
            {hasRunTiming ? (
              <DurationChart entries={entries} onSelectDay={onSelectDay} />
            ) : (
              <Empty>
                <EmptyHeader>
                  <EmptyDescription>
                    No run timings recorded yet.
                  </EmptyDescription>
                </EmptyHeader>
              </Empty>
            )}
          </ChartCard>
          <ChartCard
            title="Case outcomes"
            description="Daily counts by outcome, including cases that did not run."
            legend={
              <ul className="legend" aria-label="Outcome series">
                {outcomeNames.map((name) => (
                  <li key={name}>
                    <span
                      className="legend-dot"
                      style={{ background: outcomeSeries[name].color }}
                    />
                    {outcomeSeries[name].label}
                  </li>
                ))}
              </ul>
            }
          >
            {hasOutcomes ? (
              <Chart
                definition={outcomeChart(entries)}
                height={210}
                ariaLabel="Daily case outcomes"
              />
            ) : (
              <Empty>
                <EmptyHeader>
                  <EmptyDescription>
                    No case outcomes recorded yet.
                  </EmptyDescription>
                </EmptyHeader>
              </Empty>
            )}
          </ChartCard>
        </div>
        {children}
      </TabsContent>
      <TabsContent
        value="evidence"
        id="panel-evidence"
        aria-labelledby="tab-evidence"
        forceMount
        hidden={activeTab !== "evidence"}
      >
        {evidence}
      </TabsContent>
      <Sheet
        open={inspecting}
        onOpenChange={(open) => {
          if (!open) setInspection(undefined);
        }}
      >
        <SheetContent
          size="inspector"
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            trigger.current?.focus();
          }}
        >
          <SheetHeader>
            <SheetTitle>Case details and history</SheetTitle>
            <SheetDescription>
              {utcDay(run.timestamp)} UTC · Evidence, phase timings and
              historical outcomes.
            </SheetDescription>
          </SheetHeader>
          <div className="sheet-body">
            {selected ? (
              <Field>
                <FieldLabel htmlFor="inspector-case">Case</FieldLabel>
                <NativeSelect
                  id="inspector-case"
                  className="w-full"
                  value={selected.key}
                  onChange={(event) =>
                    setInspection({
                      run: run.timestamp,
                      key: event.target.value,
                    })
                  }
                >
                  {cases.map((item) => (
                    <NativeSelectOption key={item.key} value={item.key}>
                      {item.label}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
              </Field>
            ) : null}
            <CaseHistory
              entries={entries}
              run={run}
              caseId={selected?.key}
              comparison={
                reference
                  ? rows.find((row) => row.key === selected?.key)
                  : undefined
              }
              onSelectDay={onSelectDay}
            />
          </div>
        </SheetContent>
      </Sheet>
    </section>
  );
}
