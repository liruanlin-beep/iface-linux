import re
from math import sqrt
from pathlib import Path

EV_PER_A2_TO_J_PER_M2 = 16.02176634


def parse_vasp_results(result_dir):
    root = Path(result_dir)
    outcar = root / "OUTCAR"
    oszicar = root / "OSZICAR"
    contcar = root / "CONTCAR"
    poscar = root / "POSCAR"
    text = outcar.read_text(encoding="utf-8", errors="ignore") if outcar.is_file() else ""
    osz_text = oszicar.read_text(encoding="utf-8", errors="ignore") if oszicar.is_file() else ""
    structure_file = contcar if contcar.is_file() else poscar if poscar.is_file() else None
    structure_text = structure_file.read_text(encoding="utf-8", errors="ignore") if structure_file else ""
    result = parse_vasp_text(text, osz_text, structure_text)
    result.update({
        "directory": str(root),
        "has_outcar": outcar.is_file(),
        "has_oszicar": oszicar.is_file(),
        "has_contcar": contcar.is_file(),
        "geometry_source": structure_file.name if structure_file else "",
        "source": "local",
    })
    return result


def parse_vasp_text(outcar_text="", oszicar_text="", structure_text=""):
    text = outcar_text or ""
    energies = [float(value) for value in re.findall(r"free\s+energy\s+TOTEN\s*=\s*([-+0-9.Ee]+)", text)]
    forces = [float(value) for value in re.findall(r"FORCES:\s+max atom, RMS\s*=\s*([-+0-9.Ee]+)", text)]
    converged = "reached required accuracy" in text.lower()
    ionic_steps = len(energies)
    if not energies and oszicar_text:
        energies = [float(value) for value in re.findall(r"F=\s*([-+0-9.Ee]+)", oszicar_text)]
        ionic_steps = len(energies)
    result = {
        "energy_ev": energies[-1] if energies else None,
        "max_force_ev_a": forces[-1] if forces else None,
        "ionic_steps": ionic_steps,
        "converged": converged,
    }
    if structure_text:
        result.update(parse_poscar_geometry(structure_text))
    else:
        result.update({"atom_count": None, "area_a2": None, "surface_normal": None})
    return result


def parse_poscar_geometry(text):
    """Return atom count and the oriented slab area |a x b| from POSCAR/CONTCAR text."""
    if not (text or "").strip():
        raise ValueError('CONTCAR is empty; cannot read area or atom count')
    try:
        from pymatgen.io.vasp import Poscar

        structure = Poscar.from_str(text).structure
        matrix = structure.lattice.matrix
        area, normal = _oriented_area(matrix[0], matrix[1])
        return {"atom_count": len(structure), "area_a2": area, "surface_normal": normal}
    except Exception:
        return _parse_poscar_geometry_fallback(text)


def _parse_poscar_geometry_fallback(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 7:
        raise ValueError('Incomplete CONTCAR; cannot read lattice vectors')
    try:
        scale_values = [float(value) for value in lines[1].split()]
        raw = [[float(value) for value in lines[index].split()[:3]] for index in range(2, 5)]
        if len(scale_values) == 1:
            scale = scale_values[0]
            if scale < 0:
                volume = abs(_determinant(raw))
                if volume <= 0:
                    raise ValueError('Invalid CONTCAR cell volume')
                scale = (abs(scale) / volume) ** (1.0 / 3.0)
            lattice = [[value * scale for value in vector] for vector in raw]
        elif len(scale_values) == 3:
            lattice = [[vector[i] * scale_values[i] for i in range(3)] for vector in raw]
        else:
            raise ValueError('Invalid CONTCAR scale factor')

        count_line = 5 if all(_is_integer(value) for value in lines[5].split()) else 6
        counts = [int(value) for value in lines[count_line].split()]
        area, normal = _oriented_area(lattice[0], lattice[1])
    except (IndexError, ValueError) as exc:
        raise ValueError(f'Failed to read CONTCAR geometry: {exc}') from exc
    return {"atom_count": sum(counts), "area_a2": area, "surface_normal": normal}


def _is_integer(value):
    try:
        int(value)
        return True
    except ValueError:
        return False


def _determinant(matrix):
    a, b, c = matrix
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )


def _oriented_area(a, b):
    cross = (
        float(a[1]) * float(b[2]) - float(a[2]) * float(b[1]),
        float(a[2]) * float(b[0]) - float(a[0]) * float(b[2]),
        float(a[0]) * float(b[1]) - float(a[1]) * float(b[0]),
    )
    area = sqrt(sum(value * value for value in cross))
    if area <= 0:
        raise ValueError('CONTCAR lattice vectors a and b do not define a valid surface area')
    return area, tuple(value / area for value in cross)


def calculate_surface_energy(slab_energy_ev, bulk_energy_per_atom_ev, atom_count, area_a2, surfaces=2):
    slab_energy_ev = _required_number(slab_energy_ev, 'Slab total energy (first read OUTCAR containing TOTEN in the current directory)')
    bulk_energy_per_atom_ev = _required_number(bulk_energy_per_atom_ev, 'Bulk energy per atom')
    atom_count = _required_integer(atom_count, 'Slab atom count (check CONTCAR in the current directory)')
    area_a2 = _required_number(area_a2, 'Single-face area (check CONTCAR in the current directory)')
    surfaces = _required_integer(surfaces, 'Surface count')
    if atom_count <= 0:
        raise ValueError('Slab atom count must be positive')
    if area_a2 <= 0:
        raise ValueError('Surface area must be positive')
    if surfaces <= 0:
        raise ValueError('Surface count must be positive')
    gamma_ev_a2 = (slab_energy_ev - atom_count * bulk_energy_per_atom_ev) / (surfaces * area_a2)
    return gamma_ev_a2, gamma_ev_a2 * EV_PER_A2_TO_J_PER_M2


def _required_number(value, label):
    text = str(value).strip()
    if not text:
        raise ValueError(f'{label} cannot be empty')
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f'{label} must be numeric; current value: {text}') from exc


def _required_integer(value, label):
    number = _required_number(value, label)
    if not number.is_integer():
        raise ValueError(f'{label} must be an integer; current value: {value}')
    return int(number)
