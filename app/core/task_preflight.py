import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.input_generators import get_elements_from_poscar
from app.core.structure_model import load_structure
from app.core.task_files import standard_vasp_files, validate_task_files


@dataclass
class PreflightReport:
    task_dir: Path
    atom_count: int = 0
    elements: tuple = ()
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    checks: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.errors

    def raise_for_errors(self):
        if self.errors:
            raise ValueError('Preflight validation failed:\n- ' + "\n- ".join(self.errors))

    def to_dict(self):
        return {
            "ok": self.ok,
            "atom_count": self.atom_count,
            "elements": list(self.elements),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "checks": list(self.checks),
        }


def parse_potcar_elements(path):
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    values = re.findall(r"VRHFIN\s*=\s*([A-Z][a-z]?)\s*:", text)
    if not values:
        for line in text.splitlines():
            if "TITEL" not in line.upper():
                continue
            match = re.search(
                r"\b(?:PAW|US)(?:_PBE|_LDA|_GGA)?\s+([A-Z][a-z]?)(?:[_\s]|$)",
                line,
                flags=re.IGNORECASE,
            )
            if match:
                value = match.group(1)
                values.append(value[0].upper() + value[1:].lower())
    return values


def validate_task_preflight(task_dir, script_name="Svasp.sh", max_atoms=1000):
    root = Path(task_dir)
    report = PreflightReport(root)
    required = standard_vasp_files(script_name)
    missing, empty = validate_task_files(root, required)
    if missing:
        report.errors.append('Missing files: ' + ", ".join(missing))
    if empty:
        report.errors.append('Empty file: ' + ", ".join(empty))
    if report.errors:
        return report

    try:
        structure = load_structure(root / "POSCAR")
        report.atom_count = len(structure.atoms)
        report.elements = tuple(get_elements_from_poscar(root / "POSCAR"))
        if report.atom_count <= 0:
            report.errors.append('POSCAR has no atoms')
        elif report.atom_count > min(1000, int(max_atoms)):
            report.errors.append(
                f'POSCAR contains {report.atom_count} atoms; exceeds the limit of {min(1000, int(max_atoms))}'
            )
        else:
            report.checks.append(
                f"POSCAR readable: {report.atom_count} atoms; element order {' '.join(report.elements)}"
            )
    except Exception as exc:
        report.errors.append(f'Cannot read POSCAR: {exc}')

    potcar_elements = parse_potcar_elements(root / "POTCAR")
    if not potcar_elements:
        report.errors.append('Cannot identify elements from POTCAR VRHFIN/TITEL')
    elif tuple(potcar_elements) != report.elements:
        report.errors.append(
            'POTCAR element order mismatch: POSCAR='
            + " ".join(report.elements)
            + "，POTCAR="
            + " ".join(potcar_elements)
        )
    else:
        report.checks.append('POTCAR element order matches POSCAR')

    _validate_incar(root / "INCAR", report)
    _validate_kpoints(root / "KPOINTS", report)
    _validate_slurm_script(root / script_name, report)
    return report


def _validate_incar(path, report):
    params = {}
    invalid = []
    duplicates = []
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        stripped = line.split("#", 1)[0].split("!", 1)[0].strip()
        if not stripped:
            continue
        if "=" not in stripped:
            invalid.append(str(number))
            continue
        key, value = (part.strip() for part in stripped.split("=", 1))
        key = key.upper()
        if key in params:
            duplicates.append(key)
        params[key] = value
        if any(token in value for token in ("请填写", "自动填写", 'Enter a value', 'Auto-fill', "TODO", "<", ">")):
            report.errors.append(f'INCAR parameter {key} still contains placeholder values: {value}')
    if invalid:
        report.errors.append('These INCAR lines lack =: ' + ", ".join(invalid))
    if duplicates:
        report.warnings.append('Duplicate INCAR parameters; the last entry takes effect: ' + ", ".join(sorted(set(duplicates))))
    if params.get("LDAU", "").upper() in {".TRUE.", "TRUE", "T"}:
        missing = [key for key in ("LDAUL", "LDAUU", "LDAUJ") if not params.get(key)]
        if missing:
            report.errors.append('DFT+U enabled but missing: ' + ", ".join(missing))
    if params.get("ISPIN") == "2" and not params.get("MAGMOM"):
        report.warnings.append('ISPIN=2 without MAGMOM; confirm use of the VASP default initial magnetic moments')
    if not invalid:
        report.checks.append(f'INCAR basic format passed; {len(params)} parameters')


def _validate_kpoints(path, report):
    lines = [line.strip() for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()]
    try:
        mesh = tuple(int(value) for value in lines[3].split()[:3])
        if len(mesh) != 3 or any(value < 1 for value in mesh):
            raise ValueError
    except (IndexError, ValueError):
        report.errors.append('Invalid automatic KPOINTS mesh format')
        return
    report.checks.append(f'KPOINTS mesh: {mesh[0]}×{mesh[1]}×{mesh[2]}')


def _validate_slurm_script(path, report):
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "#SBATCH" not in text:
        report.errors.append('Submission script lacks #SBATCH resource directives')
    if not re.search(r"\b(?:srun|mpirun|mpiexec)\b.*\bvasp(?:_std|_gam|_ncl)?\b", text):
        report.errors.append('No srun/mpirun VASP launch command found in the submission script')
    if "\r" in text:
        report.errors.append('Submission script contains Windows CR line endings')
    if not any(message.startswith('Submission script') for message in report.errors):
        report.checks.append('Slurm script format and VASP run command passed')
