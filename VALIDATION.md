# Validation of iface 3.1.0

This release corrects the feature scope of the Linux port to follow the original
surface/interface application. Validation records from 3.0.x belong to those
versions and must not be presented as results for the changed 3.1.0 suite.

The current suite checks the remaining input/result/scheduler safeguards, actual
pymatgen geometry generation, layer/gap scan coverage and grouping, and the
original surface-energy arithmetic and oriented surface area. Parser energies
are synthetic fixtures. No real VASP run or live scheduler operation is performed
by the tests. Actual checks on 2026-09-28:

| Check | Result |
| --- | --- |
| Windows development suite | 65 passed, 0 skipped |
| Ubuntu / WSL 2, Python 3.12.3, installed package outside source | 65 passed, 0 skipped |
| Ordinary-user source installation with modelling dependencies | Passed |
| Installed transition-state module absent | Confirmed |
| Surface-energy analytical example | 0.1 eV/A2 = 1.602176634 J/m2 |
| Bash installer syntax and dependency consistency | Passed |

The Linux installation used the allowlisted source archive and locally cached
Linux dependency wheels. The first developer-directory install exposed stale
build-cache content; that cache was archived outside the source tree, and the
clean archive installation was independently checked for module absence.
This validation is local Ubuntu under WSL 2, not a bare-metal/cluster test.

Run locally with the modelling dependencies installed:

```bash
python -m unittest discover -s tests -v
```

The Linux CI installs the package and executes tests outside the source tree.
Offline software checks establish tested behaviour only; they do not demonstrate
physical accuracy, material stability or convergence of a user's calculation.
