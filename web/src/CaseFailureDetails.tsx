// SPDX-License-Identifier: LGPL-2.1-or-later
import { isFailure } from "./failureDetails.ts";
import { utcDay, type CaseTiming, type Snapshot } from "./history.ts";
import { RunLink } from "./RunSummary.tsx";

export function CaseFailureDetails({
  item,
  run,
}: {
  item?: CaseTiming;
  run: Snapshot;
}) {
  if (!item || !isFailure(item.status)) return null;
  const details = item.failure_details;
  return (
    <section className="failure-details" aria-label="Failure details">
      <h4>
        {item.status === "setup-error" ? "Setup error" : "Failure details"} for{" "}
        {utcDay(run.timestamp)} UTC
      </h4>
      {!details ? (
        <p>Failure details weren't recorded for this run.</p>
      ) : (
        <>
          {details.error ? (
            <pre>{details.error}</pre>
          ) : (
            <p>No failure message was recorded.</p>
          )}
          {details.cleanup_error ? (
            <>
              <h5>Cleanup error</h5>
              <pre>{details.cleanup_error}</pre>
            </>
          ) : null}
          {details.evidence.map((record, index) => (
            <details key={index}>
              <summary>{record.title}</summary>
              <pre>{record.body}</pre>
            </details>
          ))}
          {details.truncated ? (
            <p className="data-note">
              Diagnostic output was truncated. Only the last 12 evidence records
              and up to 4,000 characters per field are retained, with a
              24,000-character budget per case.
            </p>
          ) : null}
        </>
      )}
      <p>
        <RunLink run={run}>View CI run and full report artifacts</RunLink>
      </p>
    </section>
  );
}
