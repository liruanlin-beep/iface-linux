# Python API

```python
from iface import api
```

The public API follows the original surface/interface workflow. Paths may be
strings or path-like objects. Creation functions require new output paths;
inspection functions do not submit jobs. Errors use English messages.

## Geometry

```python
convert_structure(source, output)
slab(source, output, miller=(1, 0, 0), layers=6, vacuum=15, termination=0)
interfaces(substrate, film, output, substrate_miller=(1, 0, 0),
           film_miller=(1, 0, 0), substrate_layers=6, film_layers=6,
           gaps=(2.5,), max_strain=0.05, max_area=500, max_atoms=1000, limit=24,
           lateral_offsets=((0,0),(.5,0),(0,.5),(.5,.5)))
interface_scan(substrates, films, output, substrate_layer_values=(6,),
               film_layer_values=(6,), gaps=(2.5,), substrate_miller=(1,0,0),
               film_miller=(1,0,0), max_strain=0.05, max_area=500,
               max_atoms=1000, limit_per_gap=1, lateral_offsets=((0.0,0.0),))
inspect_interface_scan(output)
```

Geometry construction requires the `structures` extra. `substrates` and `films`
are sequences of input paths. Layer counts on the two sides are independent;
gaps are explicit separations in angstrom. Interface layer values follow the
original oriented-unit-cell repetition convention, not necessarily individual
atomic planes. The manifest retains side-specific atom indices and measured gaps. The scan bounds the planned number
of models to 300, with up to 1000 atoms per model. Manifests record parameters,
composition and geometry. Geometric ranking is separate from energy ranking.

`inspect_interface_scan` reads candidate results (preferring `02_static` when
present) without writing files. It reports missing/incomplete energies and
groups compatible structures for gap comparisons. Electronic convergence and
consistency of VASP settings still require review. Gap labels refer to the
requested starting geometry; use fixed-geometry static runs for a spacing-energy
curve. Relaxed outputs do not establish the final interfacial separation.

## Surface energy

```python
calculate_surface_energy(slab_energy_ev, bulk_energy_per_atom_ev,
                         atom_count, area_a2, surfaces=2)
surface_energy(directory, bulk_energy_per_atom, surfaces=2)
```

`calculate_surface_energy` preserves the original formula and returns a pair
`(gamma_ev_a2, gamma_j_m2)`. All values must be finite; atom count and number of
surfaces must be positive integers, and area must be positive.

`surface_energy` reads total energy using the result parser and geometry from
CONTCAR or POSCAR. Its report includes the input energies, atom count, oriented
area `|a x b|`, units, formula assumptions, geometry/energy source and provisional
status. Missing energy raises an error. A consistent bulk reference must be
provided by the user. Two equivalent surfaces and appropriate stoichiometry
are required for the usual two-surface interpretation.

## Inputs, results and scheduler

```python
prepare(structure, output, preset="relax", encut=520, mesh=(7,7,1),
        potcar_root=None, variants=None, scheduler="slurm", partition="",
        nodes=1, tasks=1, walltime="01:00:00", executable="vasp_std", name="iface")
to_static(source, output)
convergence_sweep(source, output, parameter, values)
inspect_calculation(directory)
inspect_tree(directory, recursive=False, limit=1000)
convergence_report(directory, tolerance_mev_atom=1.0)
preflight(directory, scheduler="slurm")
submit(directory, scheduler="slurm", confirmed=False)
queue_status(scheduler="slurm")
cancel(job_id, scheduler="slurm", confirmed=False)
```

Input preparation does not submit jobs. The user supplies licensed potentials.
Submission and cancellation require explicit confirmation. Missing measured
values remain `None`; normal program termination does not establish convergence.
See `help(api.function_name)` and command `--help` for the installed signatures.

Format utilities remain public: `Poscar`, `read_incar`, `incar_text`,
`kpoints_text`, `potcar_bytes` and `script_text`.
