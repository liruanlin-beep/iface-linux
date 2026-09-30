# Windows-to-Linux feature parity

The baseline is the author's current Windows `v2.0` source, identifying itself
as `2.0.1-rc3`. The port retains the complete application. The baseline hashes
are recorded in `WINDOWS_BASELINE.json`; parity means preserving functionality,
not byte-identical translated/platform-adapted source.

| Original function group | Retained Linux behavior |
| --- | --- |
| Projects | Create/open/save, project tree, task copy/delete, remembered directories, export |
| Structure viewer | Multiple structures, periodic full cells, atom/bond modes, crystal-axis views, rotation, zoom, selection, undo/redo, file drag/drop |
| Structure editing | Replace/delete/fix atoms, vacancies, adsorbates, supercells, distance/angle/dihedral tools |
| Surfaces | Miller orientation, layers, thickness, vacuum, termination, fixed bottom layers, previews and export |
| Interfaces | Original lattice matching, materials A/B, independent layer ranges, gap ranges, lateral offsets, strain/mismatch/area/atom limits, candidate ranking |
| High throughput | Multiple A/B combinations, joint layer/gap scans, original 300-model guard, adaptive bulk relaxation/rebuilding, fingerprints and energy ranking |
| VASP inputs | POSCAR/INCAR/KPOINTS/POTCAR preparation, all original presets, Slurm scripts |
| Workflows | Relaxation → static → PDOS; dependent interface/substrate/film preparation and charge calculations |
| Task center | Persistent SQLite queue, default 10 concurrent jobs, dependencies, reservations, deduplication, stale-claim recovery, retries, cancellation and uncertain-submission reconciliation |
| Remote tools | SSH/SFTP history/connections, file browsing/upload/download/editing, external SSH terminal, commands, bundle integrity checks, Slurm status and diagnostics |
| Results | OUTCAR/OSZICAR/CONTCAR reading, energy/forces/convergence/progress, surface-energy calculation, result structure viewing |
| Post-processing | Three-system CHGCAR grid/cell validation and subtraction, PDOS, PNG/TIFF/PDF/SVG/Excel/NPZ exports |
| AI assistant | DeepSeek, all 19 original tools and risk classifications, workspace context, approval controls, INCAR proposals, conversations and secure key storage |
| Settings | White theme, background image, language selection, paths, SSH/submission settings, responsive panels |

## Input templates

All ten original keys remain: `bulk_relax`, `surface_interface_relax`, `static`,
`pdos`, `bader`, `charge_difference`, `neb`, `molecular_dynamics`, `vaspsol`,
and `cohp`. Their parameter values match the Windows source for the audited
element fixtures. The `neb` item is the input template already present in that
Windows source. No reference-software NEB path generation, NEB execution,
vibration workflow or terminal-only scientific extension is carried into 4.0.

## Platform changes

English display text, Linux fonts/scroll events, package-relative resources,
XDG user-data paths, native file/editor/SSH-terminal opening and Secret Service
credential storage replace the corresponding Windows integrations. Original
internal identifiers and persisted theme/data semantics are retained. Original
Chinese input placeholders remain recognized alongside their English forms.

## Source comparison

The independent source audit retained all 68 baseline application files, all
987 original class/function/method declarations, and all 167 direct Tk command
bindings. Original interactive controls and event bindings were preserved;
layout containers and explanatory labels were adapted for English text. Scientific
geometry, analysis and workflow implementations were retained in 4.0.0.
Version 4.0.1 corrects surface-normal geometry and atomic-layer counting in
`slab_builder.py` and `interface_builder.py`. Their reviewed fingerprints are
recorded separately; the original Windows baseline is not overwritten.
All other audited computational modules retain their prior fingerprints.
Automated baseline verification can
be repeated with the included parity script and its embedded baseline fingerprints.

The historical rc3 release manifest covers 64 Python files. Of the current
baseline files, 63 match that manifest; `language_manager.py` was modified
before this port. Therefore the comparison is with the recorded current
Windows source, without claiming a byte-identical historical rc3 snapshot.

Local and CI runtime checks are described separately in `VALIDATION.md`.
