from collections import Counter
import math
from pathlib import Path

from app.core.path_utils import normalize_local_path
from app.core.potcar_manager import PotcarManager
from app.core.incar_presets import get_incar_preset


DEFAULT_INCAR = get_incar_preset("surface_interface_relax")


def write_incar(path, params=None):
    if isinstance(params, str):
        text = params.rstrip() + "\n"
    else:
        params = params or DEFAULT_INCAR
        text = "\n".join(f"{key} = {value}" for key, value in params.items()) + "\n"
    Path(path).write_text(text, encoding="utf-8")


def write_kpoints(path, mesh=(7, 7, 1), mode="Gamma", shift=(0, 0, 0)):
    text = "\n".join(
        [
            "Automatic mesh",
            "0",
            mode,
            f"{mesh[0]} {mesh[1]} {mesh[2]}",
            f"{shift[0]} {shift[1]} {shift[2]}",
            "",
        ]
    )
    Path(path).write_text(text, encoding="utf-8")


def write_poscar(path, structure, coordinate_mode="Direct", selective_dynamics=True):
    direct = str(coordinate_mode).lower().startswith("d")
    try:
        from pymatgen.io.vasp import Poscar

        from app.core.structure_model import to_pymatgen_structure

        pmg = to_pymatgen_structure(structure)
        # POSCAR groups must match the unique first-seen element order used by
        # POTCAR. Layered structures often interleave species in site order.
        element_order = {element: index for index, element in enumerate(structure.elements)}
        order = sorted(range(len(structure.atoms)), key=lambda i: element_order[structure.atoms[i].element])
        pmg = type(pmg).from_sites([pmg[i] for i in order])
        selective = [[not structure.atoms[i].fixed] * 3 for i in order] if selective_dynamics else None
        text = Poscar(pmg, selective_dynamics=selective).get_str(direct=direct)
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if line.strip().lower() in ("direct", "cartesian"):
                lines[index] = "Direct" if direct else "Cartesian"
                break
        text = "\n".join(lines)
        Path(path).write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")
        return
    except Exception:
        pass
    text = _render_poscar_fallback(structure, direct, selective_dynamics)
    Path(path).write_text(text, encoding="utf-8", newline="\n")


def _render_poscar_fallback(structure, direct=True, selective_dynamics=True):
    """Render a POSCAR without discarding non-orthogonal lattice vectors."""
    elements = structure.elements
    counts = Counter(atom.element for atom in structure.atoms)
    lines = [
        structure.name,
        "1.0",
        *(
            " ".join(f"{float(value):.8f}" for value in vector)
            for vector in structure.cell
        ),
        " ".join(elements),
        " ".join(str(counts[e]) for e in elements),
    ]
    if selective_dynamics:
        lines.append("Selective Dynamics")
    lines.append("Direct" if direct else "Cartesian")
    for element in elements:
        for atom in structure.atoms:
            if atom.element != element:
                continue
            flag = (" F F F" if atom.fixed else " T T T") if selective_dynamics else ""
            if direct:
                coords = _cartesian_to_fractional(
                    structure.cell, (atom.x, atom.y, atom.z)
                )
            else:
                coords = (atom.x, atom.y, atom.z)
            lines.append(f"{coords[0]:.8f} {coords[1]:.8f} {coords[2]:.8f}{flag}")
    return "\n".join(lines) + "\n"


def write_cif(path, structure):
    if getattr(structure, "pmg_structure", None) is not None:
        structure.pmg_structure.to(fmt="cif", filename=str(path))
        return
    a_length, b_length, c_length, alpha, beta, gamma = _cell_metrics(
        structure.cell
    )
    lines = [
        f"data_{Path(structure.name).stem}",
        "_symmetry_space_group_name_H-M 'P 1'",
        f"_cell_length_a {a_length:.8f}",
        f"_cell_length_b {b_length:.8f}",
        f"_cell_length_c {c_length:.8f}",
        f"_cell_angle_alpha {alpha:.8f}",
        f"_cell_angle_beta {beta:.8f}",
        f"_cell_angle_gamma {gamma:.8f}",
        "loop_",
        "_atom_site_label",
        "_atom_site_type_symbol",
        "_atom_site_fract_x",
        "_atom_site_fract_y",
        "_atom_site_fract_z",
    ]
    for i, atom in enumerate(structure.atoms, 1):
        x, y, z = _cartesian_to_fractional(
            structure.cell, (atom.x, atom.y, atom.z)
        )
        lines.append(
            f"{atom.element}{i} {atom.element} {x:.6f} {y:.6f} {z:.6f}"
        )
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _cartesian_to_fractional(cell, coordinates):
    a, b, c = (tuple(float(value) for value in vector) for vector in cell)
    r = tuple(float(value) for value in coordinates)
    b_cross_c = _cross(b, c)
    c_cross_a = _cross(c, a)
    a_cross_b = _cross(a, b)
    volume = _dot(a, b_cross_c)
    if abs(volume) < 1e-12:
        raise ValueError('The cell volume is zero; fractional coordinates cannot be exported.')
    return (
        _dot(r, b_cross_c) / volume,
        _dot(r, c_cross_a) / volume,
        _dot(r, a_cross_b) / volume,
    )


def _cell_metrics(cell):
    a, b, c = (tuple(float(value) for value in vector) for vector in cell)
    lengths = tuple(math.sqrt(_dot(vector, vector)) for vector in (a, b, c))
    if min(lengths) < 1e-12:
        raise ValueError('A lattice vector has zero length; the structure cannot be exported.')
    alpha = _vector_angle(b, c)
    beta = _vector_angle(a, c)
    gamma = _vector_angle(a, b)
    return (*lengths, alpha, beta, gamma)


def _vector_angle(first, second):
    denominator = math.sqrt(_dot(first, first) * _dot(second, second))
    cosine = max(-1.0, min(1.0, _dot(first, second) / denominator))
    return math.degrees(math.acos(cosine))


def _dot(first, second):
    return sum(first[index] * second[index] for index in range(3))


def _cross(first, second):
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def find_potcar_for_element(potcar_root, element):
    return PotcarManager(potcar_root).find_for_element(element)


def scan_potcar_root(potcar_root):
    root = Path(normalize_local_path(potcar_root))
    if not root.is_dir():
        return False, [], f'Directory does not exist: {root}'
    root = PotcarManager(root)._resolve_library_root(root)
    found = []
    for item in root.iterdir():
        if item.is_dir() and (item / "POTCAR").is_file():
            found.append(item.name)
        elif item.is_file() and item.name.startswith("POTCAR_"):
            found.append(item.name.replace("POTCAR_", "", 1))
    return True, sorted(found), 'Directory exists'


def write_potcar(path, structure, potcar_root, manual_mapping=None):
    potcar_root = normalize_local_path(potcar_root or "")
    manual_mapping = manual_mapping or {}
    if manual_mapping:
        chunks = []
        missing = []
        for element in structure.elements:
            mapped = normalize_local_path(manual_mapping.get(element, ""))
            found = Path(mapped) if mapped and Path(mapped).is_file() else find_potcar_for_element(potcar_root, element)
            if not found:
                missing.append(element)
                continue
            chunks.append(Path(found).read_bytes().rstrip())
        if missing:
            raise FileNotFoundError(
                'POTCAR not found for these elements: '
                + ", ".join(missing)
                + f'\nCurrent POTCAR root: {potcar_root}'
            )
        Path(path).write_bytes(b"\n".join(chunks) + b"\n")
        return
    PotcarManager(potcar_root).build_potcar(structure.elements, path)


def get_elements_from_poscar(poscar_path):
    poscar_path = Path(poscar_path)
    try:
        from pymatgen.io.vasp import Poscar

        poscar = Poscar.from_file(str(poscar_path), check_for_potcar=False)
        return [str(element) for element in poscar.site_symbols]
    except Exception:
        pass
    lines = [line.strip() for line in poscar_path.read_text(encoding="utf-8", errors="ignore").splitlines()]
    if len(lines) < 6:
        raise ValueError(f'Incomplete POSCAR; cannot read element order: {poscar_path}')
    return lines[5].split()
