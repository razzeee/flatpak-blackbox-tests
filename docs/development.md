# Development

## Checks

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

## Scenarios and coverage mappings

[`scenario-data/`](../scenario-data/) groups cases and mappings by primary CLI
command or public libflatpak type. Requirement indexes under
[`coverage-data/`](../coverage-data/) mirror those groups. Cross-command/type
cases have one home. Shared baseline registrations remain in `inventory.json`
and `coverage-data/mapping.json`; follow their requirement IDs to the owning
command or type. Nested JSON participates in discovery and report hashes.

Map assertions to existing requirements without changing denominators merely to
increase coverage. See [coverage semantics](../COVERAGE.md) for the counting rules.

Use `surface_assertions` for focused CLI-option, library-function, or
library-signal checks that do not establish a complete behavior requirement.
Each entry needs its interface ID and assertion rationale. Library function and
signal credit also requires the matching call trace or emission in a passing
case. These annotations do not add behavior or CLI-command credit.

Use `equivalent_options` when a case checks ordinary results under a
default-equivalent or context-inapplicable option without demonstrating its
specific effect. These checks add only separate inventory accounting. Passing
credit requires a current, complete, verified passing case and a recorded CLI
invocation containing the option. Wrapped invocations record their exact
`cli_argv` suffix; option-like payload arguments cannot earn credit.

## Version-dependent library APIs

Register optional APIs in `library_features.py`. Each entry supplies a typed
function-pointer declaration and the behavior IDs that require it. Include the
generated `blackbox-features.h` in the relevant C client and guard dependent code
with `BLACKBOX_HAVE_<UPPERCASE_API_NAME>`.

Probes use the client's compiler and flags without executing their test programs.
A baseline probe distinguishes a broken compiler/SDK setup from an unavailable
API. Each probe declares `blackbox_probe` as a volatile function pointer with the
required signature, checking both the signature and linker reference.

Use availability rather than version comparisons so backports work. Keep newer
API assertions in dedicated behaviors where possible. One missing API should not
suppress unrelated checks. Adding a feature registration does not add coverage;
assertion mappings and recorded call traces still apply.

## Interface catalogue

Check the committed catalogue against a separate Flatpak checkout:

```sh
python3 catalogue.py --source-root ../flatpak --output coverage-data/surfaces.json --check
```

The generator parses public headers and signal documentation without a built
Flatpak. It validates source hashes and rejects unsupported or unresolved input
forms. It is not a general C or Meson interpreter; build conditions, subdirectory
includes, and dependency-provided sources are not evaluated. New build structures
or generated public APIs require parser review.

Regeneration should include review of affected requirements and mappings.
Execution consumes the committed JSON and does not require the source checkout.
Source drift is separate from report freshness; test-definition changes invalidate
old passing evidence.
