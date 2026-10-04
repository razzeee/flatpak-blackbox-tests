# Target adapters

Start with [`target.example.json`](../target.example.json). An adapter receives a
fresh state directory and prints a JSON object of environment variables. Keep
setup inside that directory, send diagnostics to stderr, and exit 77 to report an
unmet prerequisite. The reference adapter is [`flatpak-adapter.py`](../flatpak-adapter.py).

## Case-specific setup

System-selector cases use `BLACKBOX_SYSTEM_INSTALL_DIR` and
`BLACKBOX_SYSTEM_CONFIG_DIR` for the target's compiled defaults. These are
expected locations, not directory redirects.

Vendor-definition cases use `BLACKBOX_PREINSTALL_DIR` for the public `.preinstall`
configuration directory. Point it inside the case's fresh state. The reference
adapter uses its isolated `preinstall.d` directory.

Ordinary runner commands receive EOF on stdin. The `stdin-terminal` scenario
instead runs an interactive shell on a pseudo-terminal and pipes a marker into
the fixture app's `-` mode. With stdout on a TTY, that mode applies and restores
terminal settings as well as echoing stdin. The scenario detects job-control
suspension. Prepare fresh fixtures to include the terminal-setting operations.

Filesystem-synchronization cases require `strace` and permission to trace the
target. They compare actual `fsync`/`fdatasync` calls while checking output content
and repository integrity.

SDK/base-extension copy cases require payload-bearing contract fixtures.
Preparation verifies marker bytes in exported OSTree commits; older fixtures
with empty extensions report an unmet prerequisite.

## Repair helper

Repair cases invoke the Python helper named by `BLACKBOX_REPAIR_FIXTURE` with:

```text
STATE_DIRECTORY OPERATION APP_COMMIT
```

The reference adapter supports:

- `remove-payload`: remove the fixture executable's OSTree object.
- `snapshot`: return a deterministic digest of installation paths, file types,
  ownership, modes, symlink targets, and contents.

These operations prepare and observe state. Public offline redeployment and app
execution establish repair success. An adapter without this helper reports an
unmet prerequisite for repair cases.

## Provisioned system cases

Cross-user cases use `execution_environment: provisioned-system` and require
`BLACKBOX_SYSTEM_TEST_ROOT`. The helper and loaded library must belong to the
selected target build. The runner needs noninteractive sudo to switch users.
Missing provisioning is an unmet prerequisite.

CI sets this up automatically. Local Podman reproduction also needs
`BLACKBOX_SYSTEM_TEST_CONTAINER=1`; the privileged bridge checks the container
marker. See [CI](ci.md) for provisioning and authorization checks.
