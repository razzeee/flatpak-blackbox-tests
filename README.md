# Flatpak black-box tests

Compatibility tests for the Flatpak CLI and source-compatible libflatpak
implementations, using public interfaces and independently prepared fixtures.
See [COVERAGE.md](COVERAGE.md) for coverage measurements and known failures.

## Requirements

- Linux, Python 3.10+, D-Bus, and working unprivileged user/mount namespaces.
- A reference Flatpak, OSTree, GPG, `ldconfig`, and a C compiler to prepare fixtures.
- The target's public development headers and libraries, `pkg-config`, and `ldd`
  for library tests.
- Desktop services and tools, including a document portal, for the relevant cases.

Run as an ordinary user. Python execution uses only the standard library.
The [CI setup script](ci/compatibility.sh) lists the full Ubuntu dependencies.

## Prepare fixtures

Run these commands from the repository root:

```sh
python3 prepare.py /tmp/blackbox-fixtures --flatpak /usr/bin/flatpak
```

Use a new directory. Preparation creates versioned repositories, apps, runtimes,
and supplemental inputs with a checksummed `fixture.json` manifest. Fixtures are
architecture-specific and can be reused across target runs. `--basic` prepares
only the inputs needed by the basic cases.

## Configure a target

Copy [target.example.json](target.example.json) and edit it for your installation:

- `cli`: absolute path to the target executable.
- `adapter`: setup command; `flatpak-adapter.py` supports reference Flatpak.
- `environment`: target-specific settings and helper paths.
- `library.environment`: build settings such as `PKG_CONFIG_PATH`.
- `library.runtime_library_dirs`: absolute directories containing the target
  library, such as `/usr/lib64` or `/usr/lib/x86_64-linux-gnu`.

For system-selector cases, set `BLACKBOX_SYSTEM_INSTALL_DIR` and
`BLACKBOX_SYSTEM_CONFIG_DIR` to the target's compiled defaults. These are expected
locations, not directory redirects.

Custom adapters receive a fresh state directory and print a JSON object of
environment variables. Keep setup inside that directory; send diagnostics to
stderr. Exit 77 reports an unmet prerequisite.

## Run tests

```sh
python3 run.py \
  --target target.json \
  --fixtures /tmp/blackbox-fixtures \
  --output /tmp/blackbox-results
```

Use a new output directory for each run. Useful options:

- `--driver cli|library|all` selects an interface.
- `--scenario lifecycle` selects one scenario; `--help` lists all names.
- `--timeout 120` sets the per-command timeout in seconds.

Each case gets isolated state and a private session bus. If `/tmp` is too small,
set `TMPDIR` to a short path on a filesystem with enough space.

## Results

The output directory contains `report.json` with command evidence and provenance,
and `coverage.md` with the coverage summary. Failed checks, missing prerequisites,
unsupported capabilities, and setup errors make the run unsuccessful.

A passing run covers only its selected, implemented cases. It does not establish
full Flatpak compatibility. Coverage reports are tied to the suite definitions;
changing those definitions requires a new run for current evidence.

```sh
python3 coverage_report.py --report /tmp/blackbox-results/report.json
```

## Development

```sh
uv sync --locked
uv run --locked ruff check .
uv run --locked ty check .
uv run --locked mypy
uv run --locked python format_json.py --check
uv run --locked python -m unittest discover -p 'test_*.py'
```

Use `python3 format_json.py --write` to format static JSON. Set
`BLACKBOX_TEST_FIXTURE` to a prepared `fixture.json` to include its optional
round-trip unit test.

Cases and their coverage mappings live together in topic files under
[`scenario-data/`](scenario-data/). Requirement indexes and category files live
under [`coverage-data/`](coverage-data/). Add assertions against public behavior
and map them to existing requirements; keep coverage denominators independent of
the number of implemented cases.

To check the generated interface catalogue against a separate Flatpak checkout:

```sh
python3 catalogue.py --source-root ../flatpak --output coverage-data/surfaces.json --check
```

## CI

Every push and pull request runs lint, type and formatting checks, unit tests on
Python 3.10 and 3.14, and the full compatibility suite against a pinned reference
Flatpak build. Compatibility failures remain failures; reports and diagnostic
logs are uploaded even when a run fails.

Both [workflows](.github/workflows/) can also be started from GitHub's Actions tab.

## License

[LGPL-2.1-or-later](COPYING).
