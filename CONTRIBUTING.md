# Contributing to iface

Contributions to the Linux terminal interface, input validation, parsers,
structure tools, documentation and tests are welcome.

## Development setup

Use Python 3.10 or newer. From a checkout:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[structures]'
python -m unittest discover -s tests -v
python -m iface --help
```

The `structures` extra enables the pymatgen integration tests. Without it, those
tests are skipped; include the skip count when reporting test results.

## Reporting a problem

Open an issue in this repository with the iface version, Linux distribution,
Python version, command, expected behavior and actual output. A small reproducible
example is more useful than a complete calculation directory. For a parser bug,
include a minimal synthetic fixture and the expected parsed fields when possible.

Before sharing files, remove credentials, private hostnames, unpublished research
and personal paths. Do not upload VASP binaries, licensed POTCAR datasets or files
you do not have permission to redistribute. Synthetic POTCAR-like strings in tests
are parser fixtures and must not be used for physical calculations.

## Making a change

1. Create a branch for one focused change.
2. Keep all built-in menus, prompts, errors, comments and documentation in English.
3. Add a meaningful regression test when fixing a behavioral defect.
4. Run the relevant tests, then the complete offline suite.
5. Update the affected documentation and describe the change and checks in a pull request.

Use standard-library `unittest` for offline tests. Scheduler tests must mock
external commands; the test suite must never submit or cancel a real job. Keep
fixtures small and deterministic. Geometry checks should test physical units,
atom counts or invariants rather than only whether a file exists.

## Behavior to preserve

- Do not overwrite existing user input or output paths silently.
- Keep preparation and inspection separate from submission and cancellation.
- Preserve explicit confirmation and durable submission records.
- Report missing measurements as `None` / JSON `null`, never as invented zeros.
- Do not treat normal VASP termination as evidence of physical convergence.
- Keep optional structure dependencies optional for basic workflows.
- Preserve actual external output and user filenames, even when they are not English.

Changes to the public API should document signatures, return values and filesystem
or scheduler effects in [docs/API.md](docs/API.md). Please review the
[validation scope](VALIDATION.md) before making performance or scientific claims.
