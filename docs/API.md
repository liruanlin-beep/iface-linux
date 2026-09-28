# Python API

Import the public surface with:

```python
from iface import api
```

This reference describes the exports of `iface.api` in version 3.0.1. Paths accept
strings or path-like objects. Functions returning dictionaries use ordinary Python
values; unavailable measurements are `None`. The CLI serializes these values as
JSON `null`. Reported output paths are usually absolute.

Input and structure generators refuse existing output paths. Preparation does not
submit jobs. Invalid inputs generally raise `ValueError`; missing files and failed
filesystem access raise `OSError` subclasses. Optional geometry operations require
the `structures` extra. Scheduler commands can also raise `RuntimeError`.

## Input preparation

```python
prepare(structure, output, preset="relax", encut=520, mesh=(7, 7, 1),
        potcar_root=None, variants=None, scheduler="slurm", partition="",
        nodes=1, tasks=1, walltime="01:00:00", executable="vasp_std", name="iface")
```

Creates a new calculation directory with POSCAR, INCAR, KPOINTS, job.sh and
manifest.json. If `potcar_root` is supplied, also combines the requested licensed
potentials into POTCAR. Presets are `relax`, `surface`, `static`, `pdos` and
`charge`. Returns the manifest fields plus `directory`, including `kind`,
`scheduler`, `source`, `atom_count`, `ready_for_preflight` and `input_sha256`.
The `ready_for_preflight` flag records whether potentials were supplied; it is
not a substitute for calling `preflight`. `tasks` is the task count per node.

```python
to_static(source, output)
```

Reads CONTCAR and INCAR from `source`, copies KPOINTS, POTCAR and job.sh, and
creates a new static calculation. Preserves the physical settings while changing
optimization controls and removing NEB controls. Returns `directory` and
`kind="static"`.

```python
convergence_sweep(source, output, parameter, values)
```

Requires fixed geometry with `NSW=0` and a complete source input set, including
POTCAR and job.sh. `parameter` is `"encut"` or `"kpoints"`; `values` contains
positive cutoffs or three-integer meshes. Creates one directory per case and a
manifest. Returns `directory`, `parameter` and `cases`; each case records its
relative directory, value and input hashes. Accepts 1 to 300 unique values.

```python
potcar_bytes(poscar, library, variants=None)
```

Reads exact potential directories below `library` in `poscar.species` order and
returns combined `bytes`. `poscar` is an `api.Poscar` instance. If `variants` is
omitted, uses exact element names; it never substitutes a suffixed variant.
Checks element metadata and dataset terminators. Does not write files.

## Formats

```python
Poscar(title, cell, species, counts, fractional, flags=None)
Poscar.read(path)
poscar.text()
poscar.atom_count
```

`Poscar` is a dataclass with NumPy cell and fractional-coordinate arrays, species
and count lists, and optional per-atom T/F flag lists. `read` loads a VASP 5 POSCAR,
validates it, and normalizes Cartesian coordinates and supported scaling forms.
`text()` returns a Direct-coordinate POSCAR string without writing it;
`atom_count` returns the sum of species counts. The constructor itself does not
perform the same checks as `read`.

```python
read_incar(path)
incar_text(params)
kpoints_text(mesh=(7, 7, 1), mode="Gamma")
```

`read_incar` returns a dictionary of uppercase keys and string values, processing
comments and semicolon-separated assignments. `incar_text` formats a dictionary
as text. `kpoints_text` validates a positive integer mesh and returns an automatic
KPOINTS string; `mode` is `"Gamma"` or `"Monkhorst-Pack"`. None writes output files.

## NEB and vibrations

```python
prepare_neb(initial_path, final_path, template, output,
            images=5, wrap=True, climb=False)
```

Creates a new NEB input directory with `images` intermediate images plus two
endpoints. Reads endpoint POSCARs and template INCAR, KPOINTS, POTCAR and job.sh.
Requires matching cells, species groups, counts and selective-dynamics flags.
With `wrap=True`, finds the shortest periodic displacement in the supplied cell,
including skewed cells, then interpolates linearly. Very skewed searches are
bounded and can be rejected. `climb=True` writes LCLIMB and requires a compatible
VASP/VTST build. Returns the manifest plus `directory`, including `images`,
`climbing_image`, `periodic_shortest_path`, maximum endpoint displacement and hashes.
Accepts 1 to 32 intermediate images. It does not infer atom correspondence.

```python
neb_report(directory)
```

Reads consecutive image directories beginning with `00`, including separately
calculated endpoint energies. Returns `images`, `all_energies_available`,
`forward_barrier_ev`, `reverse_barrier_ev`, `directory` and a qualification note.
Each image includes the result-inspection fields and its relative energy.
Barriers are `None` until every image has an energy; available barriers still
require convergence review. Does not modify files.

```python
prepare_vibration(structure, template, output, atoms, displacement=0.015)
```

Creates a new finite-difference input directory, taking INCAR, KPOINTS, POTCAR
and job.sh from `template`. `atoms` contains one-based moving atom indices.
Sets all three coordinates of those atoms active and freezes all others, replacing
the input selective-dynamics flags. Sets IBRION=5, NFREE=2 and POTIM to
`displacement` in angstrom. Returns `directory` and `moving_atoms_one_based`.

```python
effective_frequency(initial_directory, saddle_directory)
```

Reads POSCARs and vibrational results from both directories. Requires normal
termination with no detected errors, matching species order and active coordinate
flags, a mode count matching active degrees of freedom, no initial imaginary mode,
exactly one saddle imaginary mode and no real mode at or below 1e-6 THz. Returns
`effective_frequency_thz`, `effective_frequency_hz`, `initial_modes`,
`saddle_real_modes`, `active_degrees_of_freedom`, `verified_checks` and a note.
Computes a harmonic Vineyard prefactor with no quantum correction. Users must
still verify atom identity and a common physical vibrational model. Read-only.

## Result inspection

```python
inspect_calculation(directory)
inspect_tree(directory, recursive=False, limit=1000)
convergence_report(directory, tolerance_mev_atom=1.0)
```

These functions read files without changing them.

- `inspect_calculation` returns a dictionary with energy and its source, atom
  count, ionic/electronic step fields, final force information, frequencies,
  magnetization, termination/convergence flags, status, errors and warnings.
  OUTCAR TOTEN takes priority over OSZICAR F. `finished` means normal termination;
  `electronic_convergence` remains `"not_assessed"`. Missing data remains `None`.
  A final force table must agree with a known atom count before its force is used.
- `inspect_tree` returns a list of calculation reports. Without recursion it
  inspects only the supplied directory. Recursion skips hidden directories and
  does not follow directory symlinks; more than `limit` matching directories
  raises an error.
- `convergence_report` reads a sweep manifest and returns `parameter`, `reference`,
  `tolerance_mev_atom`, `cases` and a note. Cases include `delta_mev_atom` and
  `within_tolerance`. The reference is the largest cutoff or mesh point count;
  unusable or unfinished reference data yields no energy comparison.

## Structures

```python
convert_structure(source, output)
slab(source, output, miller=(1, 0, 0), layers=6, vacuum=15, termination=0)
interfaces(substrate, film, output, substrate_miller=(1, 0, 0),
           film_miller=(1, 0, 0), substrate_layers=6, film_layers=6,
           gaps=(2.5,), max_strain=0.05, max_area=500, max_atoms=1000, limit=24)
```

All three functions require pymatgen. Fractionally occupied structures must be
resolved explicitly before export. The structure size limit is 1000 atoms.

- `convert_structure` reads an ordered structure, sorts species, writes a new
  POSCAR file, and returns `file` and `atoms`.
- `slab` writes POSCAR and manifest.json in a new directory and returns `directory`
  and `summary`. `vacuum` is the vacuum thickness on each side in angstrom;
  `termination` is a zero-based termination index. The summary includes Miller
  index, surface species, atom/layer counts, area and thicknesses.
- `interfaces` creates candidate subdirectories and a manifest. Returns
  `directory` and `candidates`; each candidate records relative directory, atom
  count, gap, area, strain, geometric score, termination and lateral offset.
  `gaps` uses angstrom and `max_area` uses square angstrom. Gaps must be 0.5 to
  10 angstrom; `limit` must be 1 to 300. No matching candidates raises an error.
  Scores describe geometric matching, not formation energy or stability.

## Scheduler operations

```python
script_text(scheduler="slurm", name="iface", partition="", nodes=1, tasks=1,
            walltime="01:00:00", executable="vasp_std")
preflight(directory, scheduler="slurm")
submit(directory, scheduler="slurm", confirmed=False)
queue_status(scheduler="slurm")
cancel(job_id, scheduler="slurm", confirmed=False)
```

`scheduler` is `"slurm"` or `"pbs"`.

| Function | Result and effects |
| --- | --- |
| `script_text` | Returns script text; writes no file. Uses Slurm `srun` or PBS Professional/OpenPBS `select` syntax with `mpirun`. `tasks` is per node. Review site-specific settings. |
| `preflight` | Reads inputs and returns `directory`, `ok`, `errors`, `warnings` and, when available, `input_sha256`. Does not contact the scheduler. |
| `submit` | Requires `confirmed=True`, reruns preflight, writes a durable exclusive `.iface-submission.json`, and invokes `sbatch` or `qsub`. Returns a record with state, job ID, scheduler, directory and input hashes on success. |
| `queue_status` | Runs `squeue` or `qstat` for the current user and returns its text output. |
| `cancel` | Requires `confirmed=True`; invokes `scancel` or `qdel`. Returns `job_id`, `cancellation_requested=True` and the scheduler response. This records a request, not verified completion of cancellation. |

An existing submission record blocks repeat submission. A timeout, interruption
or unrecognized scheduler response leaves acceptance uncertain and the record
in state `unknown`. Reconcile the job with the scheduler before preparing a
separate reviewed retry directory. Do not delete the record simply to force a retry.

## Minimal example

```python
from iface import api

created = api.prepare("examples/Al/POSCAR", "api-demo", preset="static",
                      mesh=(7, 7, 7))
report = api.inspect_calculation(created["directory"])
assert report["energy_ev"] is None
checks = api.preflight(created["directory"])
assert not checks["ok"]  # No licensed POTCAR was supplied.
```

Run from the repository root with a fresh `api-demo` output name. This example
does not require VASP, potentials or a scheduler.
