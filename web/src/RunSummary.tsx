// SPDX-License-Identifier: LGPL-2.1-or-later
import type { ReactNode } from "react";
import { ArrowRightIcon } from "@phosphor-icons/react/dist/csr/ArrowRight";
import { ArrowUpRightIcon } from "@phosphor-icons/react/dist/csr/ArrowUpRight";
import { utcDay, type Snapshot } from "./history.ts";
import { verifiedPerformance } from "./performance.ts";
import type { OutcomeFilter } from "./runComparison.ts";
import { seconds } from "./format.ts";
import { Button } from "./components/ui/button.tsx";
import { Badge } from "./components/ui/badge.tsx";
import { FieldGroup, Field, FieldLabel } from "./components/ui/field.tsx";
import {
  NativeSelect,
  NativeSelectOption,
} from "./components/ui/native-select.tsx";
import { Alert, AlertDescription } from "./components/ui/alert.tsx";

export function RunLink({
  run,
  children,
}: {
  run: Snapshot;
  children: ReactNode;
}) {
  return run.run_url.startsWith("https://github.com/") ? (
    <Button variant="link" size="sm" asChild>
      <a href={run.run_url}>
        {children}
        <ArrowUpRightIcon data-icon="inline-end" />
      </a>
    </Button>
  ) : null;
}

export function RunSummary({
  entries,
  run,
  onRunChange,
  onFilter,
  controls,
}: {
  entries: Snapshot[];
  run: Snapshot;
  onRunChange: (timestamp: string) => void;
  onFilter: (status: OutcomeFilter) => void;
  controls?: ReactNode;
}) {
  const performance = verifiedPerformance(run);
  const total = Object.values(performance?.case_statuses ?? {}).reduce(
    (sum, count) => sum + count,
    0,
  );
  const failures =
    (performance?.case_statuses.failed ?? 0) +
    (performance?.case_statuses["setup-error"] ?? 0);
  const passed = performance?.case_statuses.passed ?? 0;
  return (
    <section aria-label="Selected run outcomes">
      <div className="scope-bar">
        <FieldGroup className="scope-fields">
          {controls}
          <Field orientation="horizontal">
            <FieldLabel htmlFor="recorded-run">Run</FieldLabel>
            <NativeSelect
              id="recorded-run"
              aria-label="Recorded run"
              value={run.timestamp}
              onChange={(event) => onRunChange(event.target.value)}
            >
              {[...entries].reverse().map((entry) => (
                <NativeSelectOption
                  key={entry.timestamp}
                  value={entry.timestamp}
                >
                  {utcDay(entry.timestamp)} UTC
                  {entry.verification !== "current"
                    ? ` / ${entry.verification}`
                    : ""}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </Field>
        </FieldGroup>
        <div className="run-source">
          <code>target {run.target_commit.slice(0, 8)}</code>
        </div>
      </div>
      <div
        className="verdict entry-animation"
        data-alert={!performance || failures > 0}
      >
        <div className="verdict-heading">
          {performance ? (
            <span className="verdict-number" aria-hidden="true">
              {failures ? failures : passed}
            </span>
          ) : null}
          <div className="verdict-copy">
            <span className="eyebrow">
              SELECTED RUN / {utcDay(run.timestamp)} UTC
            </span>
            <h2>
              {!performance ? (
                "Evidence unavailable."
              ) : failures ? (
                <>
                  <span className="sr-only">{failures} </span>
                  {failures === 1 ? "case needs" : "cases need"} attention.
                </>
              ) : (
                "No failures recorded."
              )}
            </h2>
            {!performance ? (
              <p>
                This run has no complete, current test report. Check CI before
                drawing conclusions.
              </p>
            ) : null}
            <div className="verdict-actions">
              {failures ? (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() =>
                    onFilter(
                      performance?.case_statuses.failed
                        ? "failed"
                        : "setup-error",
                    )
                  }
                >
                  Inspect{" "}
                  {performance?.case_statuses.failed
                    ? "failed cases"
                    : "setup errors"}
                  <ArrowRightIcon data-icon="inline-end" />
                </Button>
              ) : (
                <Badge variant="outline">
                  {run.complete && run.verification === "current"
                    ? "Verified evidence"
                    : "Unverified evidence"}
                </Badge>
              )}
              <RunLink run={run}>CI run</RunLink>
            </div>
          </div>
        </div>
        <div className="verdict-metrics">
          <div>
            <span className="eyebrow">PASSING</span>
            <strong className="metric-value">
              {performance && total
                ? `${((passed / total) * 100).toFixed(1)}%`
                : "—"}
            </strong>
            <span className="metric-caption">
              {performance
                ? `${passed} passed / ${total} recorded`
                : "Outcomes unavailable"}
            </span>
          </div>
          <div>
            <span className="eyebrow" title="Test runner wall time">
              RUN TIME
            </span>
            <strong className="metric-value">
              {seconds(performance?.duration_seconds)}
            </strong>
            <span className="metric-caption">Excludes CI build & fixtures</span>
          </div>
        </div>
      </div>
      {!performance ? (
        <Alert>
          <AlertDescription>
            Verified case outcomes are unavailable for this run. See the CI
            report for details.
          </AlertDescription>
        </Alert>
      ) : null}
    </section>
  );
}
