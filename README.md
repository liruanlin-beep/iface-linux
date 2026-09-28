# iface for Linux

**Version 3.1.0** | [Examples](docs/EXAMPLES.md) | [Python API](docs/API.md) | [Validation](VALIDATION.md)

iface adapts the author's original surface and interface modelling software to
Linux with English numbered menus, commands and a Python API. Its main workflow
is to build surface/interface models, control the layer counts on both sides
and their separation, prepare VASP calculations, and inspect surface energies.
The terminal interface runs without a graphical desktop.

| Original workflow | Linux support |
| --- | --- |
| Surface models | Miller indices, atomic layers, termination and vacuum |
| Interface models | Two input crystals, independent layer counts and interface gaps |
| Layer and gap scans | Multiple structure pairs, layer lists and explicit gap lists |
| Spacing comparison | Inspect available energies within comparable geometry groups |
| Surface energy | Read VASP energy and geometry; supply the bulk reference energy |
| VASP preparation | Relaxation/static inputs, potential selection and input checks |
| Supporting tools | Cutoff/k-point convergence, result inspection, Slurm/PBS scripts |

## Install on Linux

Python 3.10 or newer and its venv module are required. The modelling workflow
uses pymatgen; the recommended install includes it:

```bash
tar -xzf iface-linux-3.1.0.tar.gz
cd iface-linux-3.1.0
bash install.sh --structures
export PATH="$HOME/.local/share/iface/terminal-3.0/bin:$PATH"
iface
```

The existing installation location is retained so upgrades keep the same command.
Set `IFACE_VENV` to use another virtual environment. `PYTHON` selects Python and
`XDG_DATA_HOME` controls the default data base. An existing virtual environment
is upgraded by the installer. For a minimal installation without geometry tools,
omit `--structures`; surface-energy arithmetic and input/result tools remain
available. VASP and licensed potential files must be supplied separately.

## Build surfaces and interfaces

```bash
iface structure convert Al.cif Al.vasp
iface structure slab Al.vasp slab-111 --miller 1,1,1 --layers 6 --vacuum 15
iface structure interface A.vasp B.vasp interface-models \
  --substrate-miller 1,1,1 --film-miller 1,1,1 \
  --substrate-layers 6 --film-layers 4 --gaps 2.0 2.5 3.0
```

For a complete layer/gap grid use the scan command. Both interface commands
reserve candidates for each requested gap. The scan adds multiple structure
pairs and independent layer lists:

```bash
iface structure scan gap-scan --substrates A.vasp --films B.vasp \
  --substrate-layer-values 4 6 --film-layer-values 4 6 \
  --gaps 2.0 2.5 3.0 --limit-per-gap 1
iface structure scan-results gap-scan
```

All gaps are in angstrom, areas in square angstrom, and strain limits are
fractions. As in the original interface engine, interface layer arguments are
repetitions of the oriented unit cell (`in_layers=True` in pymatgen), which can
contain more than one atomic plane. The separate slab command selects atomic
planes. Review the exported coordinates and measured gap in the manifest. Generated POSCAR files and the manifest record model parameters.
Candidate scores describe geometry only. They do not predict physical stability.
New output paths are required; generators refuse to overwrite existing work.

## Prepare calculations and inspect energies

```bash
iface os prepare slab-111/POSCAR slab-relax --preset surface --mesh 9x9x1 \
  --potcar-root /path/to/your/licensed/potentials
iface os check slab-relax
iface jobs submit slab-relax --yes
iface os results slab-relax
iface os static slab-relax slab-static
iface structure surface-energy slab-static --bulk-energy-per-atom -3.74 --surfaces 2
```

The example bulk reference above is a placeholder, not a measured Al value.
Replace it with your own consistent bulk calculation. The surface energy is
`gamma = (E_slab - N * E_bulk_per_atom) / (surfaces * area)` and is reported in
eV per square angstrom and J per square metre. The usual `surfaces=2` expression
assumes two equivalent surfaces and a compatible stoichiometric bulk reference;
it cannot isolate the energy of one face of an asymmetric slab. Missing energy
is an error, never a zero. A report can be provisional; a completed program run
alone does not demonstrate electronic or physical convergence.

For a gap scan, calculate each candidate using consistent settings and place
its results in the candidate directory or its `02_static` subdirectory. The
inspection command groups compatible models and preserves missing results.
The reported gap is the requested initial separation, not a measurement of a
relaxed CONTCAR. For a spacing-energy curve keep each geometry fixed (`NSW=0`);
after relaxation, interpret ranking only as a comparison of starting models.
Review convergence and calculation settings before interpreting the ranking.
It does not compare raw total energies across different compositions or layers.

The tool prepares and reads files; VASP performs the electronic-structure
calculation. No physical result is generated merely by creating a model.

## Supporting commands

```bash
iface test encut static-template cutoff-scan --values 400 450 500 550
iface test kpoints static-template mesh-scan --values 5x5x1 7x7x1 9x9x1
iface test results cutoff-scan
iface jobs status
iface --help
```

Convergence scans require a static input set including the user's POTCAR.
Submission and cancellation are explicit operations. `iface os clean` previews
archiving; `--apply` moves outputs into `.iface-archive` and retains inputs.

## Scope correction in 3.1.0

The 3.0.x port incorrectly adopted transition-state and vibrational workflows
from a reference program. These were outside the author's intended design and
have been removed from the commands, public API and distribution. Version 3.1.0
centres the original interface, spacing and surface workflow. VaspCZ was supplied
as an operating-style reference; its feature list does not define this project.
The original Windows application is maintained separately.

See [NOTICE.md](NOTICE.md) for provenance and dependency acknowledgements.
This repository contains software, synthetic fixtures and geometry examples.
It contains no manuscript, unpublished research dataset, VASP executable or
licensed potential dataset. The software is distributed under the MIT licence.
