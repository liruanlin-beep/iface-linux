"""NEB preparation, force/barrier inspection, and harmonic frequency checks."""

import itertools
import math
from pathlib import Path
import shutil

import numpy as np

from iface.files import new_directory, write_new, write_json, fingerprint
from iface.formats import Poscar, read_incar, incar_text, number
from iface.results import inspect_calculation


def compatible_endpoints(initial, final):
    if initial.species != final.species or initial.counts != final.counts:
        raise ValueError("NEB endpoints must have the same species and atom ordering.")
    if not np.allclose(initial.cell, final.cell, rtol=1e-7, atol=1e-7):
        raise ValueError("NEB endpoints must use the same lattice.")
    if initial.flags != final.flags:
        raise ValueError("Selective-dynamics constraints must match between NEB endpoints.")


def minimum_image(delta, cell):
    """Exact closest periodic displacement, including skewed cells.

    A singular-value bound limits the integer lattice search. Extremely skewed
    cells are rejected instead of returning an approximate distance silently.
    """
    centered = np.asarray(delta, dtype=float) - np.rint(delta)
    smallest = np.linalg.svd(cell, compute_uv=False)[-1]
    if smallest <= 1e-12:
        raise ValueError("Cannot compute periodic distances in a singular cell.")
    answer = []
    for row in centered:
        upper = np.linalg.norm(row @ cell) / smallest
        ranges = [range(math.ceil(v - upper), math.floor(v + upper) + 1) for v in row]
        if math.prod(len(r) for r in ranges) > 100000:
            raise ValueError("Cell is too skewed for a reliable periodic search. Use a reduced lattice.")
        shifts = np.array(list(itertools.product(*ranges)), dtype=float)
        candidates = row - shifts
        best = np.argmin(np.linalg.norm(candidates @ cell, axis=1))
        answer.append(candidates[best])
    return np.array(answer)


def prepare_neb(initial_path, final_path, template, output, images=5, wrap=True, climb=False):
    if int(images) != images or not 1 <= images <= 32:
        raise ValueError("The number of intermediate images must be between 1 and 32.")
    initial, final = Poscar.read(initial_path), Poscar.read(final_path)
    compatible_endpoints(initial, final)
    root = Path(template)
    params = read_incar(root / "INCAR")
    params.update(IMAGES=str(images), SPRING="-5", IBRION="1", ISIF="2", NSW="200",
                  EDIFFG="-0.03", ISYM="0")
    params.pop("IOPT", None)
    params.pop("ICHAIN", None)
    if climb:
        params.update(LCLIMB=".TRUE.")
    else:
        params.pop("LCLIMB", None)
    delta = final.fractional - initial.fractional
    if wrap:
        delta = minimum_image(delta, initial.cell)
    lengths = np.linalg.norm(delta @ initial.cell, axis=1)
    with new_directory(output) as stage:
        write_new(stage / "POSCAR", initial.text())
        write_new(stage / "INCAR", incar_text(params))
        for name in ("KPOINTS", "POTCAR", "job.sh"):
            shutil.copyfile(root / name, stage / name)
        for i in range(images + 2):
            image = Poscar(f"iface NEB image {i:02d}", initial.cell, initial.species, initial.counts,
                           initial.fractional + delta * i / (images + 1), initial.flags)
            write_new(stage / f"{i:02d}" / "POSCAR", image.text())
        manifest = {"kind": "neb", "images": images, "climbing_image": bool(climb),
                    "periodic_shortest_path": bool(wrap), "max_endpoint_displacement_a": float(max(lengths)),
                    "input_sha256": fingerprint(stage),
                    "note": "Linear interpolation only. Verify atom identity, endpoint relaxation, image collisions and MPI allocation. CI-NEB requires a compatible VASP/VTST build."}
        write_json(stage / "manifest.json", manifest)
    return dict(manifest, directory=str(Path(output).resolve()))


def neb_report(directory):
    root = Path(directory)
    folders = sorted(path for path in root.iterdir() if path.is_dir() and len(path.name) == 2 and path.name.isdigit())
    if len(folders) < 3 or [int(p.name) for p in folders] != list(range(len(folders))):
        raise ValueError("NEB requires consecutive image directories starting at 00 and including both endpoints.")
    rows = [dict(image=path.name, **inspect_calculation(path)) for path in folders]
    energies = [row["energy_ev"] for row in rows]
    complete = all(value is not None for value in energies)
    baseline = energies[0]
    for row in rows:
        row["relative_energy_ev"] = row["energy_ev"] - baseline if baseline is not None and row["energy_ev"] is not None else None
    peak = max(energies) if complete else None
    return {"directory": str(root.resolve()), "images": rows, "all_energies_available": complete,
            "forward_barrier_ev": peak - energies[0] if complete else None,
            "reverse_barrier_ev": peak - energies[-1] if complete else None,
            "note": "Barriers are provisional until every image is converged. Endpoints need their own static OUTCAR/OSZICAR energies."}


def prepare_vibration(structure, template, output, atoms, displacement=0.015):
    poscar = Poscar.read(structure)
    indices = sorted(set(int(v) for v in atoms))
    if not indices or min(indices) < 1 or max(indices) > poscar.atom_count:
        raise ValueError("Moving atom indices are one-based and must exist in the structure.")
    if number(displacement) <= 0:
        raise ValueError("Finite-difference displacement must be positive.")
    root = Path(template)
    params = read_incar(root / "INCAR")
    for key in ("IMAGES", "LCLIMB", "SPRING", "IOPT", "ICHAIN"):
        params.pop(key, None)
    params.update(IBRION="5", NFREE="2", POTIM=f"{displacement:g}", NSW="1", ISYM="0")
    poscar.flags = [["T" if i + 1 in indices else "F"] * 3 for i in range(poscar.atom_count)]
    with new_directory(output) as stage:
        write_new(stage / "POSCAR", poscar.text())
        write_new(stage / "INCAR", incar_text(params))
        for name in ("KPOINTS", "POTCAR", "job.sh"):
            shutil.copyfile(root / name, stage / name)
        write_json(stage / "manifest.json", {"kind": "vibration", "moving_atoms_one_based": indices,
                                             "input_sha256": fingerprint(stage)})
    return {"directory": str(Path(output).resolve()), "moving_atoms_one_based": indices}


def effective_frequency(initial_directory, saddle_directory):
    structures = []
    for label, directory in (("initial", initial_directory), ("saddle", saddle_directory)):
        try:
            structures.append(Poscar.read(Path(directory) / "POSCAR"))
        except (OSError, ValueError) as exc:
            raise ValueError(
                f"A valid {label} POSCAR is required to verify species and active degrees of freedom.") from exc
    first, second = structures
    def species_order(structure):
        return [species for species, count in zip(structure.species, structure.counts)
                for _ in range(count)]

    def active(structure):
        return structure.flags if structure.flags is not None else [["T"] * 3 for _ in range(structure.atom_count)]

    if species_order(first) != species_order(second):
        raise ValueError("Initial and saddle POSCAR structures must have the same species and atom ordering.")
    if active(first) != active(second):
        raise ValueError("Initial and saddle POSCAR structures must have matching active degrees of freedom for every atom and direction.")
    active_dof = sum(value == "T" for row in active(first) for value in row)
    if active_dof == 0:
        raise ValueError("At least one active degree of freedom is required for a harmonic prefactor.")
    initial = inspect_calculation(initial_directory)
    saddle = inspect_calculation(saddle_directory)
    if not initial["finished"] or not saddle["finished"] or initial["errors"] or saddle["errors"]:
        raise ValueError("Both vibrational calculations must finish without detected errors.")
    a, b = initial["frequencies"], saddle["frequencies"]
    if len(a) != active_dof or len(b) != active_dof:
        raise ValueError(
            f"Each vibrational calculation must contain exactly {active_dof} modes for its active degrees of freedom; found {len(a)} initial and {len(b)} saddle modes.")
    if not a or len(a) != len(b) or any(v["imaginary"] for v in a) or sum(v["imaginary"] for v in b) != 1:
        raise ValueError("Use equal mode counts, a stable initial state, and exactly one imaginary saddle mode.")
    positive_a = [v["thz"] for v in a]
    positive_b = [v["thz"] for v in b if not v["imaginary"]]
    if min(positive_a + positive_b) <= 1e-6:
        raise ValueError("Zero or near-zero modes prevent a reliable harmonic prefactor.")
    log_ratio = sum(math.log(v) for v in positive_a) - sum(math.log(v) for v in positive_b)
    frequency = math.exp(log_ratio)
    return {"effective_frequency_thz": frequency, "effective_frequency_hz": frequency * 1e12,
            "initial_modes": len(a), "saddle_real_modes": len(positive_b),
            "active_degrees_of_freedom": active_dof,
            "verified_checks": ["species_order", "active_coordinates", "mode_count"],
            "note": "Harmonic Vineyard prefactor for matching POSCAR species order and active coordinates; no quantum correction. Atom identity and a common physical vibrational model still require user verification."}
