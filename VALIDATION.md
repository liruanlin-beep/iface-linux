# Validation record

Software: iface Linux terminal edition 3.0.1

Validation date: 2026-09-28

## Tested behaviour

| Environment or check | Result | Scope |
| --- | --- | --- |
| Windows development tests | 56 / 56 passed, no skips | Regression and actual structure-library integration |
| Ubuntu 24.04 LTS Linux, Python 3.12.3 | 56 / 56 passed, no skips | Installed source release, including five actual pymatgen integration tests |
| Independent revised Linux protocol | 22 / 22 passed, no skips | Explicit boundary-condition assertions |
| Linux terminal interaction | Passed | Enter submenu, return, exit through a pseudo-terminal |
| Al(111) slab example | Passed | 16 atoms, four layers, 12 angstrom vacuum on each side, independently checked from coordinates |

The Linux environment used NumPy 2.5.3, pymatgen 2026.9.24,
pymatgen-core 2026.9.23 and spglib 2.7.0. The unmodified installer was exercised
as an ordinary Linux user using a local collection of compatible dependency
wheels. Installed modules were compared with the source-release files. CLI
queries and imports were also checked from outside the source directory.
An initial online build-dependency download failed; it was not counted as a
successful online installation. These results cover the recorded local Linux
environment, not arbitrary Linux distributions or HPC installations.

## Development audit and protocol changes

The original 35 offline tests passed. An independent 21-check development audit
initially passed 16 checks and identified five gaps: invalid element symbols,
missing OSZICAR fallback, complete force tables ending at EOF, truncated force
tables and inconsistent vibrational coordinates. The fixes added 21 regression
cases, giving the 56-test suite above.

The original independent protocol, rerun unchanged after the fixes, passed
20 of 21 checks. R03 supplied no NIONS or POSCAR atom count and therefore could
not establish force-table completeness. R03v2 added NIONS = 2 to its two-row
force table; an additional R06 control required a null force and warning when
the atom count was unavailable. This revised protocol passed 22 of 22 checks.
The change is explicit: the original protocol is not described as having passed
all 21 checks. The public reproduction script retains the revised assertions.

A numerical check compared 64 displacements in one specified skewed cell with
4,913 enumerated translations per displacement. The maximum absolute distance
difference was 0.0 angstrom, with absolute and relative tolerances of 1e-10.
That finite check does not establish coverage of every lattice.

## Reproduce

From the repository root, after installing the structures extra:

```bash
python -m unittest discover -s tests -v
python tools/independent_checks.py --output /tmp/iface-independent-checks
```

Choose a new output directory for each independent run. CI executes the unit and
structure tests on Ubuntu; its badge and run logs report actual remote outcomes.
A workflow file alone is not evidence of a completed CI run.

## Interpretation

The tests use fabricated output fragments and mocked scheduler commands.
No real VASP calculation, live Slurm/PBS submission or MPI execution was part
of this validation. Synthetic potential metadata is not suitable for VASP.
Input presets still require system-specific convergence checks and review.

Geometry candidate scores are not interface energies. Test pass counts describe
specified assertions, not reliability probabilities or physical accuracy.
Scheduler simulations do not establish exactly-once execution remotely.

## Packaging provenance

The public 3.0.1 distribution adds open-source licensing, documentation, examples
and reproducibility tooling to the locally validated implementation. Runtime
module equality and installation checks are recorded in `docs/validation/`.
Archive checksums identify each packaged artifact; a packaging revision must not
be confused with the earlier local archive's checksum.
