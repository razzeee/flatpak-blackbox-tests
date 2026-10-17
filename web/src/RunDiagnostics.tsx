// SPDX-License-Identifier: LGPL-2.1-or-later
import { useMemo, useState } from "react";
import { ArrowUpRightIcon } from "@phosphor-icons/react/dist/csr/ArrowUpRight";
import { WarningCircleIcon } from "@phosphor-icons/react/dist/csr/WarningCircle";
import { seconds, signed } from "./format.ts";
import { caseStatusSchema, utcDay, type Snapshot } from "./history.ts";
import { verifiedPerformance } from "./performance.ts";
import { RunLink } from "./RunSummary.tsx";
import { OutcomeBadge } from "./OutcomeBadge.tsx";
import { Disclosure } from "./Disclosure.tsx";
import { Button } from "./components/ui/button.tsx";
import { Badge } from "./components/ui/badge.tsx";
import { Input } from "./components/ui/input.tsx";
import { FieldGroup, Field, FieldLabel } from "./components/ui/field.tsx";
import {
  NativeSelect,
  NativeSelectOption,
} from "./components/ui/native-select.tsx";
import { ToggleGroup, ToggleGroupItem } from "./components/ui/toggle-group.tsx";
import { Alert, AlertDescription } from "./components/ui/alert.tsx";
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
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
} from "./components/ui/table.tsx";
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

export function Change({
  value,
  unit,
}: {
  value: number | null;
  unit?: string;
}) {
  return (
    <span
      className={
        value !== null && value > 0
          ? "increase"
          : value !== null && value < 0
            ? "decrease"
            : undefined
      }
    >
      {signed(value, unit)}
    </span>
  );
}

export function OutcomeFilters({
  run,
  value,
  onChange,
}: {
  run: Snapshot;
  value: OutcomeFilter;
  onChange: (value: OutcomeFilter) => void;
}) {
  const statuses = verifiedPerformance(run)?.case_statuses;
  if (!statuses) return null;
  const total = Object.values(statuses).reduce((sum, count) => sum + count, 0);
  return (
    <ToggleGroup
      type="single"
      variant="outline"
      spacing={0}
      aria-label="Filter cases by outcome"
      value={value}
      onValueChange={(value) => {
        if (value) onChange(value as OutcomeFilter);
      }}
      className="flex-wrap"
    >
      <ToggleGroupItem value="all">
        All cases <span className="outcome-count">{total}</span>
      </ToggleGroupItem>
      {caseStatusSchema.options
        .filter((status) => (statuses[status] ?? 0) > 0 || status === value)
        .map((status) => (
          <ToggleGroupItem value={status} key={status}>
            {outcomeLabels[status]}{" "}
            <span className="outcome-count">{statuses[status] ?? 0}</span>
          </ToggleGroupItem>
        ))}
    </ToggleGroup>
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
  onInspect: (key: string, trigger?: HTMLElement) => void;
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
      <div className="cases-heading">
        <h2 id="case-results" tabIndex={-1}>
          Case results
        </h2>
        <FieldGroup className="comparison-fields">
          <Field orientation="horizontal">
            <FieldLabel htmlFor="comparison">Compare</FieldLabel>
            <NativeSelect
              id="comparison"
              value={earlier.length ? comparisonChoice : "none"}
              onChange={(event) => {
                onComparison(event.target.value);
                setExpanded(false);
              }}
            >
              {earlier.length ? (
                <NativeSelectOption value="auto">
                  Previous available run
                </NativeSelectOption>
              ) : null}
              <NativeSelectOption value="none">
                No comparison / slowest cases
              </NativeSelectOption>
              {earlier.map((item) => (
                <NativeSelectOption key={item.timestamp} value={item.timestamp}>
                  {utcDay(item.timestamp)} UTC
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </Field>
          {reference ? (
            <span className="comparison-source">
              <RunLink run={reference}>{utcDay(reference.timestamp)}</RunLink>
            </span>
          ) : null}
        </FieldGroup>
      </div>
      {reference && reference.fingerprint !== run.fingerprint ? (
        <Alert variant="warning">
          <WarningCircleIcon />
          <AlertDescription>
            The suite definition changed between these runs. Differences may
            reflect changes to the tests.
          </AlertDescription>
        </Alert>
      ) : null}
      {partial ? (
        <Alert variant="warning">
          <AlertDescription>
            This older snapshot retained only some case details. Outcome counts
            include cases whose names or timings are unavailable.
          </AlertDescription>
        </Alert>
      ) : null}
      {reference && !inventoryComplete(reference) ? (
        <Alert variant="warning">
          <AlertDescription>
            The comparison snapshot has incomplete case details. Missing entries
            are labelled "Not recorded before", not added cases.
          </AlertDescription>
        </Alert>
      ) : null}
      <div className="case-tools">
        <OutcomeFilters
          run={run}
          value={filter}
          onChange={(value) => {
            onFilter(value);
            setExpanded(false);
          }}
        />
        <FieldGroup className="case-search">
          <Field>
            <FieldLabel htmlFor="case-search" className="sr-only">
              Search cases
            </FieldLabel>
            <Input
              id="case-search"
              type="search"
              value={query}
              placeholder="Search cases"
              title="Search by case, driver or profile"
              onChange={(event) => {
                setQuery(event.target.value);
                setExpanded(false);
              }}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="case-sort" className="sr-only">
              Sort by
            </FieldLabel>
            <NativeSelect
              id="case-sort"
              value={effectiveSort}
              onChange={(event) => {
                setSort(event.target.value as CaseSort);
                setExpanded(false);
              }}
            >
              {reference ? (
                <NativeSelectOption value="change">
                  Added seconds
                </NativeSelectOption>
              ) : null}
              <NativeSelectOption value="duration">
                Current duration
              </NativeSelectOption>
            </NativeSelect>
          </Field>
        </FieldGroup>
      </div>
      <div className="results-meta">
        <p role="status">
          Showing {displayed.length} of {filtered.length} recorded cases
          {filter !== "all" ? ` with outcome ${outcomeLabels[filter]}` : ""}.
          {filtered.some((row) => !row.after)
            ? " Includes cases present only in the comparison run."
            : ""}
        </p>
        <span className="results-hint">
          Select a case to inspect evidence & timings{" "}
          <span aria-hidden="true">↗</span>
        </span>
      </div>
      {filtered.length ? (
        <>
          <Table className="case-comparison">
            <TableCaption className="sr-only">
              Case timings and outcomes. Added/removed contributions are
              labelled separately; missing timings are never zero.
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Case / interface</TableHead>
                {reference ? (
                  <TableHead scope="col">Added time</TableHead>
                ) : null}
                <TableHead scope="col">Duration</TableHead>
                <TableHead scope="col">Outcome</TableHead>
                <TableHead scope="col">
                  <span className="sr-only">Inspect</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {displayed.map((row) => {
                const item = row.after ?? row.before!;
                return (
                  <TableRow
                    key={row.key}
                    data-selected={row.key === selectedCase}
                    data-failed={
                      row.after?.status === "failed" ||
                      row.after?.status === "setup-error"
                    }
                  >
                    <TableHead scope="row">
                      <div className="case-name">
                        <Button
                          variant="case"
                          aria-label={`Inspect ${row.label}`}
                          onClick={(event) =>
                            onInspect(row.key, event.currentTarget)
                          }
                        >
                          {item.behavior_id}
                        </Button>
                        <small>
                          {item.driver} / {item.profile}
                          {row.kind !== "Comparable" && row.kind !== "Recorded"
                            ? ` · ${row.kind}`
                            : ""}
                        </small>
                      </div>
                    </TableHead>
                    {reference ? (
                      <TableCell data-label="Added time">
                        <span className="duration">
                          <Change value={row.addedSeconds} />
                        </span>
                        <small>
                          <Change value={row.percent} unit="%" />
                        </small>
                      </TableCell>
                    ) : null}
                    <TableCell data-label="Duration">
                      <span className="duration">
                        {seconds(row.afterSeconds)}
                      </span>
                    </TableCell>
                    <TableCell data-label="Outcome">
                      <OutcomeBadge status={row.after?.status} />
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Open details for ${row.label}`}
                        onClick={(event) =>
                          onInspect(row.key, event.currentTarget)
                        }
                      >
                        <ArrowUpRightIcon />
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          <div className="table-footer">
            <span>Timings include setup, execution & cleanup.</span>
            {filtered.length > 20 ? (
              <Button
                variant="outline"
                onClick={() => setExpanded((value) => !value)}
              >
                {expanded ? "Show top 20" : `Show all ${filtered.length} cases`}
              </Button>
            ) : (
              <Badge variant="outline">End of results</Badge>
            )}
          </div>
        </>
      ) : (
        <Empty>
          <EmptyHeader>
            <EmptyTitle>No matching cases</EmptyTitle>
            <EmptyDescription>
              {partial
                ? "No retained case details match this filter. Check the CI report for omitted cases."
                : "No cases match this filter."}
            </EmptyDescription>
          </EmptyHeader>
          {query || filter !== "all" ? (
            <Button
              variant="outline"
              onClick={() => {
                setQuery("");
                onFilter("all");
              }}
            >
              Clear filters
            </Button>
          ) : null}
        </Empty>
      )}
      {!earlier.length ? (
        <p className="view-description">
          No earlier run with case data is available for this target. Showing
          current durations.
        </p>
      ) : null}
      {performance ? (
        <Disclosure
          title={`Runner time breakdown · ${seconds(currentTotals.total)} total`}
        >
          <Table>
            <TableCaption>Where the runner's time went</TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Measurement</TableHead>
                {reference ? <TableHead scope="col">Before</TableHead> : null}
                <TableHead scope="col">Now</TableHead>
                {reference ? <TableHead scope="col">Change</TableHead> : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {(
                [
                  ["total", "Run total"],
                  ["cases", "Recorded case time"],
                  ["outside", "Outside recorded cases"],
                ] as const
              ).map(([key, label]) => (
                <TableRow key={key}>
                  <TableHead scope="row">{label}</TableHead>
                  {reference ? (
                    <TableCell>{seconds(previousTotals?.[key])}</TableCell>
                  ) : null}
                  <TableCell>{seconds(currentTotals[key])}</TableCell>
                  {reference ? (
                    <TableCell>
                      <Change
                        value={delta(previousTotals?.[key], currentTotals[key])}
                      />
                    </TableCell>
                  ) : null}
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="view-description">
            Outside recorded cases includes shared preflight, client builds and
            any work without case timings. CI load and outcome changes can
            affect duration.
          </p>
        </Disclosure>
      ) : (
        <p className="view-description">
          No verified case data is available for the selected run.
        </p>
      )}
    </section>
  );
}
