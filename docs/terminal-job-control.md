# Terminal job-control regression

## Upstream findings

In [Flatpak issue #6866](https://github.com/flatpak/flatpak/issues/6866), apps
reading piped stdin can be suspended when interacting with a terminal on stdout.
[smcv's explanation on October 19, 2026](https://github.com/flatpak/flatpak/issues/6866#issuecomment-6264901583)
confirms that this is a side-effect of the fix for
[CVE-2026-97029](https://github.com/flatpak/flatpak/security/advisories/GHSA-f3p8-vr7v-gxf2).
The advisory identifies
[commit a3cf27b](https://github.com/flatpak/flatpak/commit/a3cf27b5d6f365777259bd26ffa0d369c5ed7874),
which puts each bubblewrap child in its own process group.

The security fix prevents sandboxed apps from sending process-group signals to
unsandboxed processes through `kill(0, signal)` or `killpg(0, signal)`. PID
namespace separation alone does not prevent that signal delivery.

A separate process group is not automatically the terminal's foreground process
group. Terminal reads and terminal-setting operations are subject to job-control
rules; in particular, `tcsetattr()` can cause a background group to receive
`SIGTTOU`. The reported `Stopped (tty output)` is suspension, not a crash or proof
that the stdin pipe is broken. Ordinary terminal writes need not trigger it.

## Contracts to preserve together

A successful fix must preserve both:

- **Signal isolation:** group-directed signals from the sandbox must not reach
  unsandboxed processes in the launcher's process group.
- **Foreground terminal interaction:** an app launched as a foreground job must
  be able to perform legitimate terminal operations without unintended
  job-control suspension. The launching shell must regain foreground ownership
  after the app exits.

Reverting the security fix is not an acceptable resolution. A terminal test
passing on an older version does not establish that version's signal isolation.

Upstream suggested transferring terminal foreground ownership to the new group,
either in Flatpak or through a new bubblewrap option. These are proposed
approaches, not fixes verified by this repository. The comment also suggests
that Bash claims foreground ownership during initialization; using Bash as a
workaround or control case remains unverified here. Wrapping the primary probe
in a shell that repairs ownership could hide the regression.

## Existing coverage

[`stdin_tty_scenarios.py`](../stdin_tty_scenarios.py) runs an interactive Bash
session on a private pseudo-terminal and pipes a marker into the fixture app.
The fixture's `-` mode in [`fixture-app.c`](../fixture-app.c) echoes stdin and,
when stdout is a terminal, applies and restores terminal attributes. It logs the
pipe/TTY setup, process-group information, and `SIGTTOU` disposition.

The scenario requires successful completion of the terminal operations, not
merely successful output. It detects suspension and cleans up the private
terminal session. [`test_runner.py`](../test_runner.py)'s
`test_terminal_control_probe_and_background_suspension` also checks the real
fixture against a simulated loss of foreground ownership, without Flatpak.

Treat logged process-group IDs as diagnostics: PID namespaces can affect their
visibility and representation. Successful terminal operations are stronger
evidence than naive equality checks between IDs observed across namespaces.

## Follow-up coverage

These are coverage gaps, not assertions made by the existing scenario:

- Launch with inherited terminal stdin instead of a pipe, matching the broader
  subprocess case mentioned in the issue.
- Exercise an actual terminal read as well as terminal-setting operations.
- Verify that foreground ownership returns to the launching shell after exit.
- Evaluate Bash foreground claiming as a separate control case, without changing
  the direct fixture launch used to detect the regression.

Any candidate fix should be evaluated against both terminal interaction and
host signal isolation; a pass in one does not establish the other.
