"""Surface energy from the original application's slab/bulk formula."""

from pathlib import Path
import re

import numpy as np

from iface.formats import Poscar, number
from iface.results import inspect_calculation


EV_PER_A2_TO_J_PER_M2 = 16.02176634


def _finite_number(value, label):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be a finite number.")
    try:
        return number(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a finite number.") from exc


def _positive_integer(value, label):
    parsed = _finite_number(value, label)
    if not parsed.is_integer() or parsed <= 0:
        raise ValueError(f"{label} must be a positive integer.")
    return int(parsed)


def calculate_surface_energy(slab_energy_ev, bulk_energy_per_atom_ev, atom_count,
                             area_a2, surfaces=2):
    """Return surface energy in eV/angstrom^2 and J/m^2.

    gamma = (E_slab - N * E_bulk_per_atom) / (surfaces * A).
    This assumes equivalent surfaces and a consistent stoichiometric bulk
    reference. For inequivalent faces the result is their average excess energy.
    """
    slab = _finite_number(slab_energy_ev, "Slab total energy")
    bulk = _finite_number(bulk_energy_per_atom_ev, "Bulk energy per atom")
    atoms = _positive_integer(atom_count, "Slab atom count")
    area = _finite_number(area_a2, "Single-face area")
    faces = _positive_integer(surfaces, "Surface count")
    if area <= 0:
        raise ValueError("Single-face area must be positive.")
    numerator = _finite_number(slab - atoms * bulk, "Slab excess energy")
    denominator = _finite_number(faces * area, "Total surface area")
    gamma = _finite_number(numerator / denominator, "Surface energy")
    gamma_si = _finite_number(gamma * EV_PER_A2_TO_J_PER_M2, "Surface energy")
    return gamma, gamma_si


def _read_geometry(root, warnings):
    structures = {}
    for filename in ("CONTCAR", "POSCAR"):
        path = root / filename
        if not path.is_file() or not path.stat().st_size:
            continue
        try:
            structures[filename] = Poscar.read(path)
        except (ValueError, OSError) as exc:
            warnings.append(f"Cannot use {filename} geometry: {exc}")
    if not structures:
        raise ValueError("A valid, nonempty CONTCAR or POSCAR is required for surface geometry.")
    if "CONTCAR" in structures and "POSCAR" in structures:
        final, initial = structures["CONTCAR"], structures["POSCAR"]
        if final.species != initial.species or final.counts != initial.counts:
            raise ValueError("CONTCAR and POSCAR species and atom counts must match.")
    source = "CONTCAR" if "CONTCAR" in structures else "POSCAR"
    if source == "POSCAR":
        warnings.append("Using POSCAR geometry because no valid, nonempty CONTCAR is available; verify the final slab area.")
    return structures[source], source


def _check_outcar_count(root, atom_count):
    path = root / "OUTCAR"
    if path.is_file():
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                match = re.search(r"\bNIONS\s*=\s*(\d+)", line)
                if match and int(match.group(1)) != atom_count:
                    raise ValueError(
                        f"OUTCAR NIONS ({match.group(1)}) differs from the geometry atom count ({atom_count}).")


def surface_energy(directory, bulk_energy_per_atom, surfaces=2):
    """Read a VASP slab calculation and report its surface energy and assumptions.

    Use a valid final CONTCAR when available, otherwise POSCAR, with single-face
    area |a cross b|. Missing total energies are errors, never zero. Completion
    and ionic-convergence evidence are reported separately from electronic
    convergence, which the result inspector does not assess.
    """
    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"Calculation directory does not exist: {root}")
    calculation = inspect_calculation(root)
    if calculation["energy_ev"] is None:
        raise ValueError("No slab total energy is available from OUTCAR TOTEN or OSZICAR F.")
    warnings = list(calculation["warnings"])
    geometry, source = _read_geometry(root, warnings)
    if calculation["atom_count"] is not None and calculation["atom_count"] != geometry.atom_count:
        raise ValueError("The calculation atom count differs from the surface geometry atom count.")
    _check_outcar_count(root, geometry.atom_count)
    with np.errstate(over="ignore", invalid="ignore"):
        oriented_area = np.cross(geometry.cell[0], geometry.cell[1])
        area = float(np.linalg.norm(oriented_area))
    gamma, gamma_si = calculate_surface_energy(
        calculation["energy_ev"], bulk_energy_per_atom, geometry.atom_count, area, surfaces)
    provisional = not (
        calculation["finished"] and calculation["ionic_converged"] and not calculation["errors"])
    if provisional:
        warnings.append("Provisional surface energy: a normal finish and ionic convergence without reported errors have not both been established.")
    warnings.append("Electronic convergence is not assessed; verify it and use matching energy conventions and calculation settings for the slab and bulk.")
    warnings.extend(calculation["errors"])
    return {
        "directory": str(root.resolve()),
        "slab_energy_ev": _finite_number(calculation["energy_ev"], "Slab total energy"),
        "bulk_energy_per_atom_ev": _finite_number(bulk_energy_per_atom, "Bulk energy per atom"),
        "atom_count": geometry.atom_count,
        "area_a2": area,
        "surfaces": _positive_integer(surfaces, "Surface count"),
        "gamma_ev_a2": gamma,
        "gamma_j_m2": gamma_si,
        "surface_normal": (oriented_area / area).tolist(),
        "geometry_source": source,
        "energy_source": calculation["energy_source"],
        "finished": calculation["finished"],
        "ionic_converged": calculation["ionic_converged"],
        "electronic_convergence": calculation["electronic_convergence"],
        "calculation_status": calculation["status"],
        "provisional": provisional,
        "formula": "gamma = (E_slab - N * E_bulk_per_atom) / (surfaces * A)",
        "assumptions": [
            "The slab faces are parallel to lattice vectors a and b; A = |a cross b| is the single-face area.",
            "Equivalent surfaces are assumed. For inequivalent surfaces the result is their average excess energy per unit area.",
            "The supplied bulk energy per atom must be a consistent stoichiometric reference for the slab, with matching calculation settings and energy convention.",
            "The default surface count is two; the caller must verify the modeled number of surfaces.",
        ],
        "warnings": warnings,
    }
