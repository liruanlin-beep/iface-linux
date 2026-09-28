# Reproducing the independent checks

`tools/independent_checks.py` runs the revised 22-case protocol against an
**installed** iface package on Linux. It is a public reproduction runner, not a
copy of the original execution log. The scientific fixtures, assertions,
tolerances, random seed and case ordering are unchanged from the revised
protocol. The runner generates new results each time; it contains no hard-coded
pass counts.

## Run against a clean installation

From the root of a downloaded or cloned source tree:

```bash
SOURCE_DIR="$PWD"
RUN_DIR="$(mktemp -d)"
python3 -m venv "$RUN_DIR/venv"
"$RUN_DIR/venv/bin/python" -m pip install "$SOURCE_DIR"
cd "$RUN_DIR"
env -u PYTHONPATH "$RUN_DIR/venv/bin/python" \
  "$SOURCE_DIR/tools/independent_checks.py" \
  --output "$RUN_DIR/independent-results"
```

The base installation is sufficient for these 22 checks. Install the
`structures` extra separately to run the additional pymatgen integration tests
in the regression suite. The installation may access the configured package
index; the check runner does not access a cluster or download data.

If iface is already installed in a virtual environment, use its Python
interpreter and supply a new output directory. Both relative and absolute output
paths are accepted. Existing output directories are refused, so a previous run
cannot be silently overwritten. Run outside the source tree and clear
`PYTHONPATH`, as shown above. Editable installs and source-tree imports are
intentionally rejected. Do not use Python `-O` or `PYTHONOPTIMIZE`: these checks
require assertions.

The runner writes:

- `offline_test_report.json`: actual case outcomes, platform, dependency versions,
  installed-source hashes and protocol provenance.
- `offline_test_report.md`: a readable report of the same execution.
- `fixtures/`: generated synthetic inputs retained for inspection.

The exit status is zero only when all 22 checks pass; any failed assertion gives
a nonzero status. Environment/import/protocol validation failures stop the run
before a case report is produced. Locally generated reports include actual
interpreter and output paths; review those paths before sharing a report.

## Protocol and revision history

The cases are:

| Group | IDs | Scope |
| --- | --- | --- |
| POSCAR | P01-P05 | Scale factors, skew cells, selective dynamics and element validation |
| Periodic displacement | N01-N03 | Finite translation oracle, translation invariance and singular-cell rejection |
| NEB reporting | B01-B03 | Synthetic barriers and missing-energy handling |
| Result parsing | R01, R02, R03v2, R04-R06 | Energy fallback and force-table completeness |
| Scheduler | S01-S03 | Mocked submission, durable state and duplicate prevention |
| Harmonic frequency | V01-V02 | Analytical frequency ratio and active-coordinate mismatch |

The earlier 21-case protocol included R03 without an independent atom count.
After the completeness rule was made explicit, R03v2 declared `NIONS = 2` for
its two force rows. R06 was added to check that an unavailable atom count gives
an unknown maximum force plus a warning. The revised protocol therefore has
21 corrected core cases and one additional control, totaling 22. This public
runner preserves that revision; it does not retrospectively relabel the
original 21-case experiment or merge its results into a new execution.

`protocol_manifest.json` records the case IDs and provenance hashes. The
scientific block's LF-normalized SHA-256 is
`9f8ba27db2c78b49253c012270c444dbf20a9edf44aa14bd7f725b5c9392ce3a`.
The runner verifies that hash before executing the checks.

## Interpretation limits

All inputs are synthetic, including the deliberately short `POTCAR TEST`
metadata generated inside `fixtures/`. It is not a usable VASP potential and
contains no licensed pseudopotential dataset. Scheduler calls are mocked; no
real Slurm/PBS submission, VASP executable, MPI computation or physical
benchmark is involved.

The skew-cell oracle evaluates 64 deterministic displacements in one specified
cell; this is a finite numerical check rather than a proof for arbitrary
lattices. The 22 assertions are not 22 physical benchmark systems. Installer,
CLI and regression-suite checks are separate and are not counted in this
report. A passing run establishes only the assertions in the recorded
environment.
