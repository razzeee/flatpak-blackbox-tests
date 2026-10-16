// SPDX-License-Identifier: LGPL-2.1-or-later
import { useState } from "react";
import { dayMilliseconds, utcDay, type Snapshot } from "./history.ts";

export function evidenceDays(entries: readonly Snapshot[]) {
  if (!entries.length) return [];
  const byDay = new Map(
    entries.map((entry) => [utcDay(entry.timestamp), entry]),
  );
  const dates = [...byDay.keys()].sort();
  const last = Date.parse(dates.at(-1)!);
  const first = Math.max(Date.parse(dates[0]!), last - 29 * dayMilliseconds);
  return Array.from(
    { length: (last - first) / dayMilliseconds + 1 },
    (_, index) => {
      const date = new Date(first + index * dayMilliseconds)
        .toISOString()
        .slice(0, 10);
      const entry = byDay.get(date);
      const state = !entry
        ? "missing"
        : entry.complete && entry.verification === "current"
          ? "verified"
          : "unverified";
      const label = !entry
        ? "No coverage snapshot"
        : state === "verified"
          ? "Verified evidence"
          : entry.verification === "not-run"
            ? "No test report"
            : !entry.complete
              ? "Incomplete results"
              : `${entry.verification} evidence`;
      return { date, entry, state, label };
    },
  );
}

const dateFormat = new Intl.DateTimeFormat("en", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});
const timeFormat = new Intl.DateTimeFormat("en", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "UTC",
});

export function RunHealth({ entries }: { entries: Snapshot[] }) {
  const days = evidenceDays(entries);
  const [selection, setSelection] = useState("");
  const selected =
    days.find((day) => day.date === selection) ??
    [...days].reverse().find((day) => day.state !== "verified") ??
    days.at(-1);
  if (!selected) return null;
  const gaps = days.filter((day) => day.state !== "verified").length;
  return (
    <section className="run-health" aria-labelledby="run-health-title">
      <div className="run-health-heading">
        <h2 id="run-health-title">Daily evidence</h2>
        <span>
          {days.length} days · {gaps} without verified evidence
        </span>
      </div>
      <p className="run-health-note">
        Runs are scheduled daily. Dates below are UTC completion days, not
        scheduled dates. A delayed schedule can leave a gap.
      </p>
      <div
        className="evidence-strip"
        role="group"
        aria-label="Daily evidence; select a day for details"
      >
        {days.map((day) => (
          <button
            type="button"
            key={day.date}
            className={`evidence-day ${day.state}`}
            aria-pressed={day.date === selected.date}
            aria-label={`${dateFormat.format(new Date(day.date))}: ${day.label}`}
            title={`${day.date}: ${day.label}`}
            onClick={() => setSelection(day.date)}
          >
            <span aria-hidden="true">{new Date(day.date).getUTCDate()}</span>
            <span className="evidence-symbol" aria-hidden="true">
              {day.state === "verified"
                ? "✓"
                : day.state === "missing"
                  ? "–"
                  : "!"}
            </span>
          </button>
        ))}
      </div>
      <div className="evidence-range" aria-hidden="true">
        <span>{dateFormat.format(new Date(days[0]!.date))}</span>
        <span>{dateFormat.format(new Date(days.at(-1)!.date))}</span>
      </div>
      <div
        className="evidence-detail"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        <strong>
          {dateFormat.format(new Date(selected.date))} · {selected.label}
        </strong>
        <p>
          {!selected.entry
            ? "No coverage snapshot was published for this UTC day. This does not prove the scheduled run was skipped; it may have started or finished on another day."
            : selected.state === "verified"
              ? "This run produced verified coverage evidence. Individual tests can still have failed."
              : selected.entry.verification === "not-run"
                ? "No test report was available when this snapshot was published. Check CI for build or setup failures."
                : "This attempt did not produce complete, current evidence. Check CI for details."}
        </p>
        {selected.entry?.workflow ? (
          <p>
            {selected.entry.workflow.event === "schedule"
              ? "Scheduled trigger"
              : `${selected.entry.workflow.event} trigger`}{" "}
            · created{" "}
            {timeFormat.format(new Date(selected.entry.workflow.created_at))}{" "}
            UTC. This is the observed trigger time, not the planned start.
          </p>
        ) : selected.entry ? (
          <p>Trigger timing was not recorded in this historical snapshot.</p>
        ) : null}
        {selected.entry?.run_url.startsWith("https://github.com/") ? (
          <a href={selected.entry.run_url}>View CI run</a>
        ) : null}
      </div>
      <ul className="run-health-legend" aria-label="Evidence legend">
        <li>✓ Verified</li>
        <li>! Unverified</li>
        <li>– No snapshot</li>
      </ul>
    </section>
  );
}
