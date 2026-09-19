// SPDX-License-Identifier: LGPL-2.1-or-later
import type { ReactNode } from "react";
import { caseStatusSchema, utcDay, type Snapshot } from "./history.ts";
import { verifiedPerformance } from "./performance.ts";
import { outcomeLabels, type OutcomeFilter } from "./runComparison.ts";

export function RunLink({
  run,
  children,
}: {
  run: Snapshot;
  children: ReactNode;
}) {
  return run.run_url.startsWith("https://github.com/") ? (
    <a href={run.run_url}>{children}</a>
  ) : null;
}

export function RunSummary({
  entries,
  run,
  onRunChange,
  filter,
  onFilter,
}: {
  entries: Snapshot[];
  run: Snapshot;
  onRunChange: (timestamp: string) => void;
  filter: OutcomeFilter;
  onFilter: (status: OutcomeFilter) => void;
}) {
  const performance = verifiedPerformance(run);
  const total = Object.values(performance?.case_statuses ?? {}).reduce(
    (sum, count) => sum + count,
    0,
  );
  return (
    <section className="run-summary" aria-label="Selected run outcomes">
      <div className="toolbar">
        <label>
          Recorded run{" "}
          <select
            value={run.timestamp}
            onChange={(event) => onRunChange(event.target.value)}
          >
            {[...entries].reverse().map((entry) => (
              <option key={entry.timestamp} value={entry.timestamp}>
                {utcDay(entry.timestamp)} UTC
                {entry.verification !== "current"
                  ? ` / ${entry.verification}`
                  : ""}
              </option>
            ))}
          </select>
        </label>
        <RunLink run={run}>View CI run</RunLink>
      </div>
      {performance ? (
        <div
          className="outcome-counts"
          role="group"
          aria-label="Filter cases by outcome"
        >
          <button
            type="button"
            aria-pressed={filter === "all"}
            onClick={() => onFilter("all")}
          >
            <strong>{total}</strong> All cases
          </button>
          {caseStatusSchema.options.map((status) => {
            const count = performance.case_statuses[status] ?? 0;
            return (
              <button
                key={status}
                type="button"
                data-status={status}
                disabled={count === 0}
                aria-pressed={filter === status}
                onClick={() => onFilter(status)}
              >
                <strong>{count}</strong> {outcomeLabels[status]}
              </button>
            );
          })}
        </div>
      ) : (
        <p>
          Verified case outcomes are unavailable for this run. See the CI report
          for details.
        </p>
      )}
    </section>
  );
}
