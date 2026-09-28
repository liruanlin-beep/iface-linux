from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.core.structure_model import from_pymatgen_structure, to_pymatgen_structure


@dataclass
class SlabTermination:
    index: int
    label: str
    top_species: list
    bottom_species: list
    shift: float


@dataclass
class SlabResult:
    structure: object
    lightweight: object
    termination: SlabTermination
    summary: dict


def cross_section_area(lattice):
    matrix = lattice.matrix if hasattr(lattice, "matrix") else np.array(lattice)
    return float(np.linalg.norm(np.cross(matrix[0], matrix[1])))


def _surface_species(slab):
    coords = slab.cart_coords
    z = coords[:, 2]
    top_z = z.max()
    bottom_z = z.min()
    top = sorted({str(slab.species[i].symbol) for i in range(len(slab)) if abs(z[i] - top_z) < 0.05})
    bottom = sorted({str(slab.species[i].symbol) for i in range(len(slab)) if abs(z[i] - bottom_z) < 0.05})
    return top, bottom


def _load_pmg(structure):
    if isinstance(structure, (str, Path)):
        from pymatgen.core import Structure as PmgStructure
        return PmgStructure.from_file(str(structure))
    if hasattr(structure, "lattice") and hasattr(structure, "sites"):
        return structure.copy()
    return to_pymatgen_structure(structure)


def list_slab_terminations(structure, miller_index, scan_count=12):
    from pymatgen.core.surface import SlabGenerator

    pmg = _load_pmg(structure)
    gen = SlabGenerator(
        initial_structure=pmg,
        miller_index=tuple(miller_index),
        min_slab_size=3,
        min_vacuum_size=10.0,
        in_unit_planes=True,
        center_slab=False,
        primitive=False,
    )
    results = []
    seen = set()
    shifts = [i / scan_count for i in range(scan_count)]
    for shift in shifts:
        try:
            slab = gen.get_slab(shift=shift)
        except Exception:
            continue
        top, bottom = _surface_species(slab)
        key = (tuple(top), tuple(bottom))
        if key in seen:
            continue
        seen.add(key)
        label = f"{'/'.join(top) or '?'}-termination (bottom: {'+'.join(bottom) or '?'}) [shift={shift:.3f}]"
        results.append(SlabTermination(len(results), label, top, bottom, shift))
    if not results:
        slabs = gen.get_slabs(symmetrize=False)
        for slab in slabs:
            top, bottom = _surface_species(slab)
            label = f"{'/'.join(top) or '?'}-termination (bottom: {'+'.join(bottom) or '?'})"
            results.append(SlabTermination(len(results), label, top, bottom, float(getattr(slab, "shift", 0.0) or 0.0)))
    return results


def _trim_to_layers(raw_slab, n_layers):
    coords = raw_slab.cart_coords
    rounded_z = np.round(coords[:, 2], 6)
    z_values = sorted(set(rounded_z))
    if len(z_values) <= n_layers:
        return raw_slab
    keep = set(z_values[-n_layers:])
    remove = [i for i, z in enumerate(rounded_z) if z not in keep]
    slab = raw_slab.copy()
    slab.remove_sites(remove)
    return slab


def _center_with_vacuum(slab, vacuum):
    from pymatgen.core import Lattice, Structure as PmgStructure

    coords = slab.cart_coords.copy()
    z_min = float(coords[:, 2].min())
    z_max = float(coords[:, 2].max())
    a_vec = slab.lattice.matrix[0]
    b_vec = slab.lattice.matrix[1]
    c_vec = slab.lattice.matrix[2]
    c_dir = c_vec / np.linalg.norm(c_vec)
    new_c = c_dir * ((z_max - z_min) + 2 * vacuum)
    coords[:, 2] += vacuum - z_min
    return PmgStructure(Lattice([a_vec, b_vec, new_c]), slab.species, coords, coords_are_cartesian=True)


def generate_slab(structure, miller_index, n_layers=6, vacuum=15.0, termination_index=0):
    from pymatgen.core.surface import SlabGenerator

    pmg = _load_pmg(structure)
    terms = list_slab_terminations(pmg, miller_index)
    if not terms:
        raise RuntimeError('No surface terminations were found.')
    term = terms[max(0, min(int(termination_index or 0), len(terms) - 1))]
    gen = SlabGenerator(
        initial_structure=pmg,
        miller_index=tuple(miller_index),
        min_slab_size=max(1, int(n_layers)),
        min_vacuum_size=float(vacuum),
        in_unit_planes=True,
        center_slab=False,
        primitive=False,
    )
    try:
        slab = gen.get_slab(shift=term.shift)
    except Exception:
        slabs = gen.get_slabs(symmetrize=False)
        if not slabs:
            raise RuntimeError('pymatgen could not generate a slab.')
        slab = slabs[0]
    slab = _center_with_vacuum(_trim_to_layers(slab, int(n_layers)), float(vacuum))
    name = f"{Path(getattr(structure, 'name', 'structure')).stem}_slab_{miller_index[0]}{miller_index[1]}{miller_index[2]}_{term.index}"
    lightweight = from_pymatgen_structure(slab, name)
    summary = summarize_slab(slab, tuple(miller_index), term, vacuum)
    return SlabResult(slab, lightweight, term, summary)


def summarize_slab(slab, miller_index, termination, vacuum):
    coords = slab.cart_coords
    z = coords[:, 2]
    return {
        "Miller": tuple(miller_index),
        "Termination": termination.label,
        "Top surface": "+".join(termination.top_species),
        "Bottom surface": "+".join(termination.bottom_species),
        "Atoms": len(slab),
        "Layers": len(set(np.round(z, 6))),
        "Area (A^2)": f"{cross_section_area(slab.lattice):.4f}",
        "Slab thickness (A)": f"{float(z.max() - z.min()):.4f}",
        "Vacuum each side (A)": f"{float(vacuum):.2f}",
        "Cell c (A)": f"{float(np.linalg.norm(slab.lattice.matrix[2])):.4f}",
    }
