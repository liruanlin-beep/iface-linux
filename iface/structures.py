"""Headless access to the existing iface slab and interface engines."""

import math
from pathlib import Path

from iface.files import new_directory, write_new, write_json


def _load_ordered(path):
    try:
        from pymatgen.core import Structure
    except ImportError as exc:
        raise ImportError("Install structural tools with: python -m pip install '.[structures]'") from exc
    structure = Structure.from_file(str(path))
    if not structure.is_ordered:
        raise ValueError("Disordered/partially occupied structures must be resolved explicitly before VASP export.")
    if len(structure) > 1000:
        raise ValueError("The structure exceeds the 1000-atom limit.")
    return structure


def _positive(value, name):
    if not math.isfinite(float(value)) or float(value) <= 0:
        raise ValueError(f"{name} must be finite and positive.")


def _miller(values):
    if len(values) != 3 or not any(values) or any(int(v) != v for v in values):
        raise ValueError("A Miller index needs three integers and cannot be (0, 0, 0).")


def convert_structure(source, output):
    structure = _load_ordered(source)
    from pymatgen.io.vasp import Poscar
    write_new(output, Poscar(structure.get_sorted_structure()).get_str())
    return {"file": str(Path(output).resolve()), "atoms": len(structure)}


def slab(source, output, miller=(1, 0, 0), layers=6, vacuum=15, termination=0):
    _miller(miller)
    _positive(layers, "Layer count")
    _positive(vacuum, "Vacuum thickness")
    if int(layers) != layers or termination < 0:
        raise ValueError("Layer count must be integral and the termination index nonnegative.")
    from iface.core.slab_builder import generate_slab, list_slab_terminations
    structure = _load_ordered(source)
    if termination >= len(list_slab_terminations(structure, miller)):
        raise ValueError("The requested termination index does not exist.")
    result = generate_slab(structure, miller, layers, vacuum, termination)
    if len(result.structure) > 1000:
        raise ValueError("The generated slab exceeds the 1000-atom limit.")
    from pymatgen.io.vasp import Poscar
    with new_directory(output) as stage:
        write_new(stage / "POSCAR", Poscar(result.structure.get_sorted_structure()).get_str())
        write_json(stage / "manifest.json", {"kind": "slab", "summary": result.summary})
    return {"directory": str(Path(output).resolve()), "summary": result.summary}


def interfaces(substrate, film, output, substrate_miller=(1, 0, 0), film_miller=(1, 0, 0),
               substrate_layers=6, film_layers=6, gaps=(2.5,), max_strain=0.05,
               max_area=500, max_atoms=1000, limit=24,
               lateral_offsets=((0.0, 0.0), (0.5, 0.0), (0.0, 0.5), (0.5, 0.5))):
    _miller(substrate_miller)
    _miller(film_miller)
    for value, name in ((substrate_layers, "Substrate layers"), (film_layers, "Film layers"),
                        (max_area, "Maximum area"), (max_strain, "Maximum strain")):
        _positive(value, name)
    gaps = tuple(dict.fromkeys(float(value) for value in gaps))
    if not gaps or any(not math.isfinite(v) or not 0.5 <= v <= 10 for v in gaps):
        raise ValueError("Every gap must be finite and between 0.5 and 10 angstrom.")
    if any(int(value) != value for value in (substrate_layers, film_layers, limit, max_atoms)):
        raise ValueError("Layer counts, candidate limits and maximum atoms must be integers.")
    if not len(gaps) <= limit <= 300 or not 1 <= max_atoms <= 1000:
        raise ValueError("Allow at least one candidate per requested gap, at most 300 candidates and 1000 atoms.")
    lateral_offsets = tuple(tuple(float(value) for value in offset) for offset in lateral_offsets)
    if not lateral_offsets or any(len(offset) != 2 or not all(math.isfinite(v) for v in offset)
                                  for offset in lateral_offsets):
        raise ValueError("Every lateral offset must contain two finite fractional coordinates.")
    from iface.core.interface_builder import search_interface_candidates
    substrate_structure, film_structure = _load_ordered(substrate), _load_ordered(film)
    candidates = []
    for gap_index, gap in enumerate(gaps):
        per_gap_limit = int(limit) // len(gaps) + (gap_index < int(limit) % len(gaps))
        found = search_interface_candidates(
            substrate_structure, film_structure, substrate_miller=substrate_miller,
            film_miller=film_miller, substrate_layers=substrate_layers, film_layers=film_layers,
            gap_values=[gap], max_strain=max_strain, max_area=max_area, max_atoms=max_atoms,
            limit=per_gap_limit, lateral_offsets=lateral_offsets)
        if not found:
            raise ValueError(f"No interface candidates meet the requested bounds at gap {gap:g} A. "
                             "Review strain, area and atom limits.")
        candidates.extend(found)
    from pymatgen.io.vasp import Poscar
    rows = []
    with new_directory(output) as stage:
        for index, candidate in enumerate(candidates, 1):
            name = f"interface_{index:03d}"
            write_new(stage / name / "POSCAR", Poscar(candidate.structure.get_sorted_structure()).get_str())
            rows.append(_interface_metadata(candidate, name, substrate, film,
                                            substrate_layers, film_layers, "A01_B01"))
        write_json(stage / "manifest.json", {"kind": "interface_scan", "schema_version": 2,
                    "requested_gaps_a": list(gaps), "candidates": rows,
                    "note": "Geometric matching scores are not formation energies or stability predictions."})
    return {"directory": str(Path(output).resolve()), "candidates": rows}


def _interface_metadata(candidate, directory, substrate, film, substrate_layers, film_layers, pair_id):
    """Keep the original scan identity and matching geometry beside each POSCAR."""
    structure = candidate.structure
    exported = structure.get_sorted_structure()
    labels = exported.site_properties.get("interface_label", [])
    substrate_indices = [index for index, label in enumerate(labels) if label == "substrate"]
    film_indices = [index for index, label in enumerate(labels) if label == "film"]
    metadata = {"directory": directory, "pair_id": pair_id,
            "source_a": str(Path(substrate).resolve()), "source_b": str(Path(film).resolve()),
            "substrate_layers": int(substrate_layers), "film_layers": int(film_layers),
            "atoms": candidate.atoms, "gap_a": candidate.gap,
            "area_a2": candidate.area, "strain": candidate.strain,
            "score": candidate.score, "termination": candidate.label,
            "offset": list(candidate.offset),
            "composition": {str(key): float(value) for key, value in
                            structure.composition.get_el_amt_dict().items()},
            "in_plane_vectors_a": [[round(float(value), 8) for value in vector]
                                   for vector in structure.lattice.matrix[:2]]}
    if substrate_indices and film_indices:
        import numpy as np
        normal = np.cross(exported.lattice.matrix[0], exported.lattice.matrix[1])
        normal /= np.linalg.norm(normal)
        heights = exported.cart_coords @ normal
        metadata.update(substrate_atom_indices=substrate_indices, film_atom_indices=film_indices,
                        measured_gap_a=float(min(heights[film_indices]) - max(heights[substrate_indices])),
                        atom_indices_are_zero_based=True)
    return metadata
