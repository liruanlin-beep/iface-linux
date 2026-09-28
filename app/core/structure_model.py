from dataclasses import dataclass
from math import cos, sin, sqrt
from pathlib import Path
import re
import shlex

from app.core.element_color_manager import DEFAULT_ELEMENT_COLORS as ELEMENT_COLORS


@dataclass
class Atom:
    element: str
    x: float
    y: float
    z: float
    fixed: bool = False
    selected: bool = False


class Structure:
    def __init__(self, name='No structure loaded', atoms=None, cell=None, source_path=None, pmg_structure=None):
        self.name = name
        self.atoms = list(atoms) if atoms is not None else []
        self.cell = cell or ((6.0, 0.0, 0.0), (0.0, 6.0, 0.0), (0.0, 0.0, 6.0))
        self.source_path = source_path
        self.pmg_structure = pmg_structure

    def copy(self, name=None):
        atoms = [Atom(atom.element, atom.x, atom.y, atom.z, atom.fixed, atom.selected) for atom in self.atoms]
        pmg = self.pmg_structure.copy() if self.pmg_structure is not None else None
        return Structure(name or self.name, atoms, tuple(tuple(v for v in row) for row in self.cell), self.source_path, pmg)

    @property
    def elements(self):
        seen = []
        for atom in self.atoms:
            if atom.element not in seen:
                seen.append(atom.element)
        return seen

    def selected_indices(self):
        return [i for i, atom in enumerate(self.atoms) if atom.selected]

    def clear_selection(self):
        for atom in self.atoms:
            atom.selected = False

    def select_nearest(self, index):
        self.clear_selection()
        if 0 <= index < len(self.atoms):
            self.atoms[index].selected = True

    def fix_selected(self):
        for atom in self.atoms:
            if atom.selected:
                atom.fixed = True

    def replace_selected(self, element):
        for atom in self.atoms:
            if atom.selected:
                atom.element = element
        self.pmg_structure = None

    def delete_selected(self):
        self.atoms = [atom for atom in self.atoms if not atom.selected]
        self.pmg_structure = None

    def make_supercell(self, nx, ny, nz):
        base = list(self.atoms)
        new_atoms = []
        a, b, c = self.cell
        for i in range(max(1, nx)):
            for j in range(max(1, ny)):
                for k in range(max(1, nz)):
                    shift = (
                        i * a[0] + j * b[0] + k * c[0],
                        i * a[1] + j * b[1] + k * c[1],
                        i * a[2] + j * b[2] + k * c[2],
                    )
                    for atom in base:
                        new_atoms.append(
                            Atom(
                                atom.element,
                                atom.x + shift[0],
                                atom.y + shift[1],
                                atom.z + shift[2],
                                atom.fixed,
                            )
                        )
        self.atoms = new_atoms
        self.cell = (
            tuple(value * max(1, nx) for value in a),
            tuple(value * max(1, ny) for value in b),
            tuple(value * max(1, nz) for value in c),
        )
        self.pmg_structure = None

    def supercell(self, nx, ny, nz, name=None):
        copied = self.copy(name or f"{Path(self.name).stem}_supercell_{nx}x{ny}x{nz}")
        copied.make_supercell(nx, ny, nz)
        copied.clear_selection()
        return copied

    def slab_preview(self, h=1, k=0, l=0, layers=6, vacuum=15.0, name=None):
        layers = max(1, int(layers))
        vacuum = max(0.0, float(vacuum))
        base = self.copy(name or f"{Path(self.name).stem}_slab_{h}{k}{l}")
        ax, by, cz = base.cell[0][0], base.cell[1][1], base.cell[2][2]
        z_scale = max(0.25, layers / 6)
        for atom in base.atoms:
            atom.z = atom.z * z_scale
            atom.selected = False
        base.cell = ((ax, 0, 0), (0, by, 0), (0, 0, cz * z_scale + vacuum))
        return base

    def combine_with(self, other, spacing=2.5, x_offset=0.0, y_offset=0.0, name="interface_model"):
        top = self.copy()
        bottom = other.copy()
        ax = max(top.cell[0][0], bottom.cell[0][0])
        by = max(top.cell[1][1], bottom.cell[1][1])
        top_z = max((atom.z for atom in top.atoms), default=0.0)
        bottom_min_z = min((atom.z for atom in bottom.atoms), default=0.0)
        shift_z = top_z - bottom_min_z + max(0.0, float(spacing))
        atoms = [Atom(atom.element, atom.x, atom.y, atom.z, atom.fixed) for atom in top.atoms]
        for atom in bottom.atoms:
            atoms.append(Atom(atom.element, atom.x + x_offset, atom.y + y_offset, atom.z + shift_z, atom.fixed))
        cz = max((atom.z for atom in atoms), default=0.0) + max(8.0, float(spacing))
        return Structure(name, atoms, ((ax, 0, 0), (0, by, 0), (0, 0, cz)))


def load_structure(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f'Structure file does not exist: {path}')
    pymatgen_error = None
    try:
        from pymatgen.core import Structure as PmgStructure
        return from_pymatgen_structure(
            PmgStructure.from_file(
                str(path),
                primitive=False,
                merge_tol=0.01,
            ),
            path.name,
            str(path),
        )
    except Exception as exc:
        pymatgen_error = exc
    # Windows drag-and-drop often supplies extensionless files such as POSCAR,
    # CONTCAR or renamed structure files. Detect supported formats by content.
    try:
        from pymatgen.core import Structure as PmgStructure

        text = path.read_text(encoding="utf-8", errors="ignore")
        for fmt in ("poscar", "cif"):
            try:
                parsed = PmgStructure.from_str(
                    text,
                    fmt=fmt,
                    primitive=False,
                    merge_tol=0.01,
                )
                return from_pymatgen_structure(parsed, path.name, str(path))
            except Exception:
                continue
    except Exception:
        pass
    suffix = path.suffix.lower()
    if suffix == ".cif":
        atoms, cell = _parse_cif_atoms(path)
    else:
        parsed = _parse_poscar_atoms(path)
        if isinstance(parsed, tuple):
            atoms, cell = parsed
        else:
            atoms, cell = parsed, None
    if not atoms:
        detail = f"；pymatgen：{pymatgen_error}" if pymatgen_error else ""
        raise ValueError(f'No atoms could be read from the structure file: {path}{detail}')
    return Structure(path.name, atoms, cell=cell, source_path=str(path))


def from_pymatgen_structure(pmg_structure, name="structure", source_path=None):
    atoms = []
    ordered_species = []
    normalized_fractional = []
    for site in pmg_structure:
        element = _site_element(site)
        fractional = [float(value) % 1.0 for value in site.frac_coords]
        coords = pmg_structure.lattice.get_cartesian_coords(fractional)
        ordered_species.append(element)
        normalized_fractional.append(fractional)
        atoms.append(
            Atom(
                element,
                float(coords[0]),
                float(coords[1]),
                float(coords[2]),
            )
        )
    matrix = pmg_structure.lattice.matrix
    cell = tuple(tuple(float(v) for v in row) for row in matrix)
    # Normalize partial-occupancy sites to the deterministic element selected
    # above. This keeps lattice metadata available for the information panel,
    # while mutation methods invalidate the cache before display/export.
    try:
        normalized_pmg = type(pmg_structure)(
            pmg_structure.lattice,
            ordered_species,
            normalized_fractional,
            coords_are_cartesian=False,
        )
    except Exception:
        normalized_pmg = None
    return Structure(name, atoms, cell, source_path, normalized_pmg)


def to_pymatgen_structure(structure):
    from pymatgen.core import Lattice, Structure as PmgStructure
    species = [atom.element for atom in structure.atoms]
    coords = [[atom.x, atom.y, atom.z] for atom in structure.atoms]
    return PmgStructure(Lattice(structure.cell), species, coords, coords_are_cartesian=True)


def _site_element(site):
    """Return a deterministic element for ordered or partially occupied sites."""
    try:
        return str(site.specie.symbol)
    except (AttributeError, ValueError):
        pass
    candidates = []
    for specie, occupancy in site.species.items():
        symbol = getattr(specie, "symbol", "")
        if symbol:
            candidates.append((float(occupancy), str(symbol)))
    if not candidates:
        raise ValueError(f'CIF site has no identifiable element: {site}')
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][1]


def _parse_cif_atoms(path):
    """Minimal standards-aware CIF fallback used when pymatgen cannot parse."""
    lines = path.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
    scalar_values = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line.startswith("_"):
            continue
        parts = _cif_tokens(line)
        if len(parts) >= 2:
            scalar_values[parts[0].lower()] = parts[1]
    try:
        lengths = tuple(
            _cif_number(scalar_values[f"_cell_length_{axis}"])
            for axis in ("a", "b", "c")
        )
        angles = tuple(
            _cif_number(scalar_values[f"_cell_angle_{axis}"])
            for axis in ("alpha", "beta", "gamma")
        )
        cell = _cell_from_parameters(*lengths, *angles)
    except (KeyError, ValueError, ZeroDivisionError) as exc:
        raise ValueError('CIF lacks valid cell lengths or angles.') from exc

    raw_sites = []
    index = 0
    while index < len(lines):
        if lines[index].strip().lower() != "loop_":
            index += 1
            continue
        index += 1
        headers = []
        while index < len(lines) and lines[index].lstrip().startswith("_"):
            tokens = _cif_tokens(lines[index])
            if tokens:
                headers.append(tokens[0].lower())
            index += 1
        header_index = {name: position for position, name in enumerate(headers)}
        coordinate_headers = (
            "_atom_site_fract_x",
            "_atom_site_fract_y",
            "_atom_site_fract_z",
        )
        is_atom_loop = all(name in header_index for name in coordinate_headers)
        while index < len(lines):
            stripped = lines[index].strip()
            if (
                not stripped
                or stripped.startswith("#")
            ):
                index += 1
                continue
            if stripped.lower() == "loop_" or stripped.startswith("_") or stripped.lower().startswith("data_"):
                break
            tokens = _cif_tokens(stripped)
            index += 1
            if not is_atom_loop or len(tokens) < len(headers):
                continue
            try:
                fractional = [
                    _cif_number(tokens[header_index[name]])
                    for name in coordinate_headers
                ]
            except (IndexError, ValueError):
                continue
            element = ""
            for name in ("_atom_site_type_symbol", "_atom_site_label"):
                position = header_index.get(name)
                if position is not None and position < len(tokens):
                    element = _element_from_cif_token(tokens[position])
                    if element:
                        break
            if not element:
                continue
            raw_sites.append((element, tuple(value % 1.0 for value in fractional)))
        if is_atom_loop and raw_sites:
            break
    symmetry_operations = _parse_cif_symmetry_operations(lines)
    expanded_sites = _expand_cif_sites(
        raw_sites,
        scalar_values,
        symmetry_operations,
    )
    atoms = [
        Atom(element, *_fractional_to_cartesian(fractional, cell))
        for element, fractional in expanded_sites
    ]
    return atoms, cell


def _cif_tokens(line):
    try:
        return shlex.split(str(line or ""), comments=True, posix=True)
    except ValueError:
        return str(line or "").split()


def _cif_number(value):
    text = str(value or "").strip().strip("'\"")
    text = re.sub(r"\(\d+\)$", "", text)
    if "/" in text and re.fullmatch(r"[+-]?\d+\s*/\s*\d+", text):
        numerator, denominator = text.split("/", 1)
        return float(numerator) / float(denominator)
    return float(text)


def _element_from_cif_token(value):
    match = re.match(r"^([A-Z][a-z]?)", str(value or "").strip())
    return match.group(1) if match else ""


def _cell_from_parameters(a, b, c, alpha, beta, gamma):
    alpha, beta, gamma = (value * 3.141592653589793 / 180.0 for value in (alpha, beta, gamma))
    sin_gamma = sin(gamma)
    if abs(sin_gamma) < 1e-12:
        raise ValueError('Invalid CIF gamma cell angle.')
    a_vector = (a, 0.0, 0.0)
    b_vector = (b * cos(gamma), b * sin_gamma, 0.0)
    cx = c * cos(beta)
    cy = c * (cos(alpha) - cos(beta) * cos(gamma)) / sin_gamma
    cz_squared = max(0.0, c * c - cx * cx - cy * cy)
    return (a_vector, b_vector, (cx, cy, sqrt(cz_squared)))


def _fractional_to_cartesian(fractional, cell):
    return tuple(
        fractional[0] * cell[0][axis]
        + fractional[1] * cell[1][axis]
        + fractional[2] * cell[2][axis]
        for axis in range(3)
    )


def _expand_cif_sites(raw_sites, scalar_values, symmetry_operations=()):
    """Expand asymmetric CIF sites with the declared space group."""
    if not raw_sites:
        return []
    if symmetry_operations:
        expanded = []
        seen = set()
        for element, fractional in raw_sites:
            for operation in symmetry_operations:
                try:
                    image = _apply_cif_symmetry_operation(operation, fractional)
                except ValueError:
                    continue
                wrapped = tuple(float(value) % 1.0 for value in image)
                key = (element, *(round(value, 7) for value in wrapped))
                if key not in seen:
                    seen.add(key)
                    expanded.append((element, wrapped))
        if expanded:
            return expanded
    group = None
    try:
        from pymatgen.symmetry.groups import SpaceGroup

        number = (
            scalar_values.get("_space_group_it_number")
            or scalar_values.get("_symmetry_int_tables_number")
        )
        symbol = (
            scalar_values.get("_space_group_name_h-m_alt")
            or scalar_values.get("_symmetry_space_group_name_h-m")
        )
        if number and str(number).strip() not in {"?", "."}:
            group = SpaceGroup.from_int_number(int(float(str(number))))
        elif symbol and str(symbol).strip() not in {"?", "."}:
            group = SpaceGroup(str(symbol).strip().strip("'\""))
    except Exception:
        group = None
    if group is None:
        return list(raw_sites)

    expanded = []
    seen = set()
    for element, fractional in raw_sites:
        try:
            orbit = group.get_orbit(fractional, tol=1e-5)
        except Exception:
            orbit = (fractional,)
        for image in orbit:
            wrapped = tuple(float(value) % 1.0 for value in image)
            key = (element, *(round(value, 7) for value in wrapped))
            if key in seen:
                continue
            seen.add(key)
            expanded.append((element, wrapped))
    return expanded


def _parse_cif_symmetry_operations(lines):
    aliases = {
        "_space_group_symop_operation_xyz",
        "_symmetry_equiv_pos_as_xyz",
    }
    operations = []
    index = 0
    while index < len(lines):
        if lines[index].strip().lower() != "loop_":
            index += 1
            continue
        index += 1
        headers = []
        while index < len(lines) and lines[index].lstrip().startswith("_"):
            tokens = _cif_tokens(lines[index])
            if tokens:
                headers.append(tokens[0].lower())
            index += 1
        operation_column = next(
            (headers.index(name) for name in aliases if name in headers),
            None,
        )
        while index < len(lines):
            stripped = lines[index].strip()
            if not stripped or stripped.startswith("#"):
                index += 1
                continue
            if stripped.lower() == "loop_" or stripped.startswith("_") or stripped.lower().startswith("data_"):
                break
            tokens = _cif_tokens(stripped)
            index += 1
            if operation_column is not None and operation_column < len(tokens):
                operation = tokens[operation_column].replace(" ", "")
                if operation.count(",") == 2:
                    operations.append(operation)
        if operations:
            break
    return tuple(operations)


def _apply_cif_symmetry_operation(operation, fractional):
    values = {"x": fractional[0], "y": fractional[1], "z": fractional[2]}
    result = []
    for expression in str(operation).lower().replace(" ", "").split(","):
        if not expression:
            raise ValueError('Empty CIF symmetry expression')
        total = 0.0
        normalized = expression if expression[0] in "+-" else "+" + expression
        for sign, term in re.findall(r"([+-])([^+-]+)", normalized):
            factor = -1.0 if sign == "-" else 1.0
            if term in values:
                total += factor * values[term]
            elif re.fullmatch(r"\d+(?:/\d+)?(?:\.\d+)?", term):
                total += factor * _cif_number(term)
            else:
                match = re.fullmatch(r"(\d+(?:\.\d+)?)\*?([xyz])", term)
                if not match:
                    raise ValueError(f'Cannot parse CIF symmetry operation: {operation}')
                total += factor * float(match.group(1)) * values[match.group(2)]
        result.append(total)
    if len(result) != 3:
        raise ValueError(f'Invalid CIF symmetry operation: {operation}')
    return tuple(result)


def _parse_poscar_atoms(path):
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
    if len(lines) < 8:
        return []
    try:
        scale = float(lines[1])
        lattice = []
        for line in lines[2:5]:
            lattice.append(tuple(float(value) * scale for value in line.split()[:3]))
        elements = lines[5].split()
        counts = [int(x) for x in lines[6].split()]
    except (ValueError, IndexError):
        return []
    has_selective = lines[7].lower().startswith("s")
    coord_type_line = 8 if has_selective else 7
    coord_start = coord_type_line + 1
    direct = lines[coord_type_line].lower().startswith("d")
    atoms = []
    element_list = []
    for element, count in zip(elements, counts):
        element_list.extend([element] * count)
    for element, line in zip(element_list, lines[coord_start:]):
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            values = [float(v) for v in parts[:3]]
        except ValueError:
            continue
        if direct:
            x = values[0] * lattice[0][0] + values[1] * lattice[1][0] + values[2] * lattice[2][0]
            y = values[0] * lattice[0][1] + values[1] * lattice[1][1] + values[2] * lattice[2][1]
            z = values[0] * lattice[0][2] + values[1] * lattice[1][2] + values[2] * lattice[2][2]
        else:
            x, y, z = [value * scale for value in values]
        fixed = len(parts) >= 6 and all(flag.upper().startswith("F") for flag in parts[3:6])
        atoms.append(Atom(element, x, y, z))
        atoms[-1].fixed = fixed
    return atoms, tuple(lattice)


def sample_nacl_atoms():
    atoms = []
    for x in (0, 2, 4, 6):
        for y in (0, 2, 4, 6):
            for z in (0, 2, 4, 6):
                element = "Na" if int((x + y + z) / 2) % 2 == 0 else "Cl"
                atoms.append(Atom(element, x, y, z))
    return atoms


def project_point(atom, width, height, scale=54, rx=-0.55, rz=0.75, center=(3, 3, 3)):
    x = atom.x - center[0]
    y = atom.y - center[1]
    z = atom.z - center[2]
    cy, sy = cos(rz), sin(rz)
    cx, sx = cos(rx), sin(rx)
    x, y = x * cy - y * sy, x * sy + y * cy
    y, z = y * cx - z * sx, y * sx + z * cx
    return width / 2 + x * scale, height / 2 + y * scale, z
