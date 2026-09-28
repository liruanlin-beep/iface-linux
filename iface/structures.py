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
               max_area=500, max_atoms=1000, limit=24):
    _miller(substrate_miller)
    _miller(film_miller)
    for value, name in ((substrate_layers, "Substrate layers"), (film_layers, "Film layers"),
                        (max_area, "Maximum area"), (max_strain, "Maximum strain")):
        _positive(value, name)
    if not gaps or any(not math.isfinite(v) or not 0.5 <= v <= 10 for v in gaps):
        raise ValueError("Every gap must be finite and between 0.5 and 10 angstrom.")
    if not 1 <= limit <= 300 or not 1 <= max_atoms <= 1000:
        raise ValueError("Use 1 to 300 candidates and at most 1000 atoms per structure.")
    from iface.core.interface_builder import search_interface_candidates
    substrate_structure, film_structure = _load_ordered(substrate), _load_ordered(film)
    candidates = search_interface_candidates(
        substrate_structure, film_structure, substrate_miller=substrate_miller,
        film_miller=film_miller, substrate_layers=substrate_layers, film_layers=film_layers,
        gap_values=list(gaps), max_strain=max_strain, max_area=max_area, max_atoms=max_atoms, limit=limit)
    if not candidates:
        raise ValueError("No interface candidates meet the requested bounds. Review strain, area and atom limits.")
    from pymatgen.io.vasp import Poscar
    rows = []
    with new_directory(output) as stage:
        for candidate in candidates:
            name = f"interface_{candidate.index + 1:03d}"
            write_new(stage / name / "POSCAR", Poscar(candidate.structure.get_sorted_structure()).get_str())
            rows.append({"directory": name, "atoms": candidate.atoms, "gap_a": candidate.gap,
                         "area_a2": candidate.area, "strain": candidate.strain,
                         "score": candidate.score, "termination": candidate.label,
                         "offset": candidate.offset})
        write_json(stage / "manifest.json", {"kind": "interface_scan", "candidates": rows,
                    "note": "Geometric matching scores are not formation energies or stability predictions."})
    return {"directory": str(Path(output).resolve()), "candidates": rows}
