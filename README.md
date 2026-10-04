# Flatpak black-box tests

Compatibility tests for the Flatpak CLI and source-compatible libflatpak
implementations, using public interfaces and independently prepared fixtures.

[Daily coverage dashboard](https://razzeee.github.io/flatpak-blackbox-tests/)
· [GitHub Actions](https://github.com/razzeee/flatpak-blackbox-tests/actions)
· [What coverage means](COVERAGE.md)

## Requirements

- Linux, Python 3.10+, D-Bus, and working unprivileged user/mount namespaces.
- A reference Flatpak, OSTree, GPG, `ldconfig`, and a C compiler to prepare fixtures.
  Full preparation also needs `pkg-config` and GIO development files.
- The target's public development headers and libraries, `pkg-config`, and `ldd`
  for library tests.
- Desktop services and tools, including a document portal, for relevant cases.
  Pseudo-terminal cases need Bash and util-linux `setsid`.

Run as an ordinary user. The Python runner uses only the standard library.
The [CI setup script](ci/compatibility.sh) lists the full Ubuntu dependencies.

## Prepare fixtures

Run from the repository root, using a new directory:

```sh
python3 prepare.py /tmp/blackbox-fixtures --flatpak /usr/bin/flatpak
```

Preparation creates repositories, apps, runtimes, and a checksummed `fixture.json`
manifest. Fixtures are architecture-specific and reusable across target runs.
Use `--basic` to prepare only the inputs needed by the basic cases.

## Configure a target

Copy [target.example.json](target.example.json) to `target.json` and set:

- `cli`: absolute path to the target executable.
- `adapter`: setup command. `flatpak-adapter.py` supports reference Flatpak.
- `environment`: target-specific settings and helper paths.
- `library.environment`: build settings such as `PKG_CONFIG_PATH`.
- `library.runtime_library_dirs`: absolute directories containing the target library.

See [target adapters](docs/target-adapters.md) for custom adapters and cases that
need additional setup.

## Run tests

Use a new output directory for each run:

```sh
python3 run.py \
  --target target.json \
  --fixtures /tmp/blackbox-fixtures \
  --output /tmp/blackbox-results
```

- `--driver cli|library|all` selects an interface.
- `--scenario lifecycle` selects one scenario; `--help` lists all names.
- `--timeout 120` sets the per-command timeout in seconds.

Each case gets isolated state and a private session bus. If `/tmp` is too small,
set `TMPDIR` to a short path on a filesystem with enough space.

## Results

The output directory contains `report.json` with results, command evidence, and
provenance, and `coverage.md` with the coverage summary. Failed checks, missing
prerequisites, unsupported capabilities, and setup errors make the run unsuccessful.
Library client compilation failures are setup errors; unavailable optional APIs
are reported as unsupported.

Console output shows passing coverage and the ten slowest executed cases. A
passing run establishes only its selected, implemented checks, not full Flatpak
compatibility. To inspect coverage from a saved report:

```sh
python3 coverage_report.py --report /tmp/blackbox-results/report.json
```

CI tests upstream Flatpak `main`. Default-branch pushes and daily scheduled runs
also test configured releases.
Some classified non-security assertion failures remain visible without failing
the CI job. See [CI and the dashboard](docs/ci.md) for the failure policy,
published results, and local dashboard development.

## Contributing

See [development](docs/development.md) for checks, scenario mappings, and support
for version-dependent library APIs.

## License

[LGPL-2.1-or-later](COPYING).
