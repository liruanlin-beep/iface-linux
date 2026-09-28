# Examples without VASP

These examples exercise input generation, geometry and parsing on Linux. They
require no VASP binary, licensed potential library, server or scheduler. They do
not calculate electronic energies or establish physical stability.

Install the `structures` extra as described in the [README](../README.md). Start
from the repository root and use a fresh working directory:

```bash
mkdir geometry-demo
cd geometry-demo
```

iface refuses to overwrite outputs. Use another directory for a repeat run.

## 1. Create a conventional FCC Al cell

The lattice parameter below is an illustrative input, not a relaxed result.

```bash
python - <<'PY'
from pymatgen.core import Lattice, Structure
from pymatgen.io.cif import CifWriter

al = Structure(
    Lattice.cubic(4.05),
    ["Al"] * 4,
    [[0, 0, 0], [0, 0.5, 0.5], [0.5, 0, 0.5], [0.5, 0.5, 0]],
)
CifWriter(al).write_file("Al.cif")
PY
iface structure convert Al.cif Al.vasp
```

The conversion report contains `"atoms": 4`. This conventional cell differs from
the one-atom primitive cell in [`examples/Al/POSCAR`](../examples/Al/POSCAR).

## 2. Generate an Al(111) slab

```bash
iface structure slab Al.vasp slab-111 \
  --miller 1,1,1 --layers 4 --vacuum 12
```

The executed example produced the following geometry with iface 3.0.1:

| Quantity | Value |
| --- | --- |
| Atom count | 16 |
| Atomic layers | 4 |
| Surface area | 28.4100 square angstrom |
| Slab thickness | 7.0148 angstrom |
| Vacuum on each side | 12.00 angstrom |
| Cell c length | 31.0148 angstrom |

![Slab generation output excerpt](images/slab.png)

The screenshot is an excerpt of actual output, formatted for readability with
the directory and termination description omitted. Small numerical or structural
representation differences can occur with different dependency versions.

Inspect `slab-111/POSCAR` and `slab-111/manifest.json`. Independently check the
generated geometry by projecting atom positions along the surface normal:

```bash
python - <<'PY'
import numpy as np
from pymatgen.core import Structure

s = Structure.from_file("slab-111/POSCAR")
a, b, c = s.lattice.matrix
normal = np.cross(a, b)
area = np.linalg.norm(normal)
normal /= area
if np.dot(c, normal) < 0:
    normal *= -1
heights = s.cart_coords @ normal
cell_height = float(np.dot(c, normal))
print("Atoms:", len(s))
print("Area (A^2):", float(area))
print("Slab thickness (A):", float(np.ptp(heights)))
print("Lower vacuum (A):", float(heights.min()))
print("Upper vacuum (A):", float(cell_height - heights.max()))
assert len(s) == 16
assert np.isclose(area, 28.4099633711485, atol=1e-6)
assert np.isclose(heights.min(), 12.0, atol=1e-6)
assert np.isclose(cell_height - heights.max(), 12.0, atol=1e-6)
PY
```

## 3. Generate two geometric interface candidates

Use Al on both sides to demonstrate the interface search and registry output:

```bash
iface structure interface Al.vasp Al.vasp interface-demo \
  --substrate-miller 1,1,1 --film-miller 1,1,1 \
  --substrate-layers 4 --film-layers 4 --gaps 2.5 \
  --max-strain 0.05 --max-area 30 --max-atoms 100 --limit 2
```

The executed example produced two candidates with 8 atoms each, an area of
approximately 7.10249 square angstrom, a 2.5 angstrom gap and numerical strain
close to zero. Their lateral offsets were `(0.0, 0.0)` and `(0.5, 0.0)`.
The interface engine chooses a surface representation independently of the slab
command, so their atom counts and surface areas need not match.

Each candidate has its own POSCAR. The manifest records scores and geometric
parameters. These candidates have not been relaxed; the score is not an interface
energy, and this example makes no claim about stable structures.

## 4. Prepare inputs without submitting them

```bash
iface os prepare Al.vasp static-input --preset static --encut 520 --mesh 7x7x7
iface os results static-input
iface os check static-input
```

The preparation command writes input files but no POTCAR. The result report has
no energy and a `not_started` status. The final preflight command intentionally
returns exit code 2 with a missing-POTCAR error. This is expected: adding a real,
licensed potential and reviewing the settings are separate steps before any
real calculation. The numerical input values are illustrative defaults.

## 5. Check missing and truncated result data

Create deliberately synthetic parser inputs:

```bash
python - <<'PY'
from pathlib import Path
import shutil

for name in ("synthetic-energy", "synthetic-force"):
    Path(name).mkdir()
    shutil.copyfile("Al.vasp", Path(name) / "POSCAR")
Path("synthetic-energy/OUTCAR").write_text("", encoding="utf-8")
Path("synthetic-energy/OSZICAR").write_text(
    " 1 F= -.40000000E+01 E0= -.40000000E+01 d E = 0.0\n", encoding="utf-8")
Path("synthetic-force/OUTCAR").write_text(
    " NIONS = 4\n"
    " POSITION                                       TOTAL-FORCE (eV/Angst)\n"
    " -------------------------------------------------------------------\n"
    " 0.0 0.0 0.0 0.1 0.0 0.0\n", encoding="utf-8")
PY
iface os results synthetic-energy
iface os results synthetic-force
```

The first report has `energy_ev=-4.0` and `energy_source="OSZICAR:F"`; its maximum
force stays `null`. The value is a synthetic fixture, not an Al calculation.
The second report finds one force row for four atoms, reports an incomplete
table, emits a warning and leaves the maximum force `null`.

## 6. Run the regression tests

Return to the repository root:

```bash
cd ..
python -m unittest discover -s tests -v
```

The tests also cover periodic NEB interpolation, invalid structures, exact
potential selection, convergence reports, vibrational consistency and scheduler
failure handling. Scheduler calls are mocked and potential metadata is synthetic.
See [VALIDATION.md](../VALIDATION.md) for recorded results and their scope.
