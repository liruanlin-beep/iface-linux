# Surface and interface examples

These examples create geometry without VASP. They do not calculate energies.
Install with `bash install.sh --structures` and use a fresh output directory.

```bash
python - <<'PY'
from pymatgen.core import Lattice, Structure
al = Structure(Lattice.cubic(4.05), ["Al"] * 4,
               [[0,0,0], [0,.5,.5], [.5,0,.5], [.5,.5,0]])
al.to(filename="Al.cif")
PY
iface structure slab Al.cif surface-111 --miller 1,1,1 --layers 4 --vacuum 12
iface structure scan interface-gaps --substrates Al.cif --films Al.cif \
  --substrate-layer-values 2 --film-layer-values 2 --gaps 2.0 2.5 3.0 \
  --max-area 40 --limit-per-gap 1
iface structure scan-results interface-gaps
```

Before VASP is run, the scan report has no calculated energies and no confirmed
best spacing. Each candidate has its own POSCAR and recorded input parameters.
The Al lattice constant is illustrative and is not a claimed relaxed value.

An arithmetic check of the original surface-energy formula can be run without
VASP. The following values are synthetic, not material data:

```python
from iface import api
gamma_ev_a2, gamma_j_m2 = api.calculate_surface_energy(-8, -5, 2, 10, 2)
assert abs(gamma_ev_a2 - 0.1) < 1e-12
assert abs(gamma_j_m2 - 1.602176634) < 1e-12
```

For real results, use `iface structure surface-energy CALCULATION_DIRECTORY
--bulk-energy-per-atom YOUR_VALUE --surfaces 2`. The energy and geometry must
come from your own consistent VASP calculations; review the assumptions and
provisional status described in the main README.
