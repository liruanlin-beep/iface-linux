import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SAFE_PATCH_KEYS = {
    "ALGO",
    "NELM",
    "AMIX",
    "BMIX",
    "AMIX_MAG",
    "BMIX_MAG",
    "IBRION",
    "POTIM",
    "LREAL",
}


@dataclass(frozen=True)
class RecoveryPlan:
    error_codes: tuple
    title: str
    explanation: str
    incar_patch: dict = field(default_factory=dict)
    restart_from_contcar: bool = True
    remove_remote_files: tuple = ()
    risk: str = "write"
    automatic: bool = False

    def to_dict(self):
        return {
            "error_codes": list(self.error_codes),
            "title": self.title,
            "explanation": self.explanation,
            "incar_patch": dict(self.incar_patch),
            "restart_from_contcar": self.restart_from_contcar,
            "remove_remote_files": list(self.remove_remote_files),
            "risk": self.risk,
            "automatic": self.automatic,
        }


def suggest_recovery(progress, incar_text=""):
    errors = {
        item.get("code")
        for item in getattr(progress, "errors", []) or []
        if item.get("code")
    }
    current = parse_incar_text(incar_text or "")
    if "BRMIX" in errors:
        return RecoveryPlan(
            ("BRMIX",),
            'Charge-density mixing recovery',
            'Use a more robust electronic algorithm and conservative mixing; deleting CHGCAR still requires user confirmation.',
            {
                "ALGO": "Normal",
                "AMIX": "0.20",
                "BMIX": "0.0001",
                "AMIX_MAG": "0.80",
                "BMIX_MAG": "0.0001",
            },
            remove_remote_files=("CHGCAR",),
        )
    if errors & {"EDDDAV", "ZHEGV"}:
        code = sorted(errors & {"EDDDAV", "ZHEGV"})[0]
        return RecoveryPlan(
            (code,),
            'Electronic diagonalization recovery',
            'Use ALGO=Normal and disable real-space projection.',
            {"ALGO": "Normal", "LREAL": ".FALSE."},
        )
    if "ZBRENT" in errors:
        return RecoveryPlan(
            ("ZBRENT",),
            'Ionic line-search recovery',
            'Reduce the ionic step and use a more robust damped update.',
            {"IBRION": "1", "POTIM": "0.20"},
        )
    if "TIME_LIMIT" in errors:
        return RecoveryPlan(
            ("TIME_LIMIT",),
            'Resume after walltime limit',
            'Resume from CONTCAR without changing physical parameters; confirm a longer walltime in Slurm settings.',
            {},
        )
    if "TOO_FEW_BANDS" in errors:
        return RecoveryPlan(
            ("TOO_FEW_BANDS",),
            'NBANDS requires user review',
            'NBANDS depends on electron count, parallel resources and calculation type; it is not guessed automatically.',
            {},
            risk="manual",
        )
    if errors & {"OUT_OF_MEMORY", "INTERNAL_ERROR"}:
        code = sorted(errors & {"OUT_OF_MEMORY", "INTERNAL_ERROR"})[0]
        return RecoveryPlan(
            (code,),
            'Review resources and the environment',
            'This error cannot be resolved by automatically changing INCAR alone. Check node memory, core counts and the VASP environment.',
            {},
            restart_from_contcar=False,
            risk="manual",
        )
    max_steps = int(getattr(progress, "max_electronic_steps", 0) or 0)
    step = int(getattr(progress, "electronic_step", 0) or 0)
    if max_steps and step >= max_steps and not getattr(progress, "electronic_converged", False):
        new_nelm = min(400, max(120, int(current.get("NELM", max_steps) or max_steps) + 60))
        return RecoveryPlan(
            ("ELECTRONIC_NOT_CONVERGED",),
            'Electronic steps have not converged',
            f'Electronic steps reached NELM={max_steps}; suggested increase to {new_nelm} and use ALGO=Normal.',
            {"NELM": str(new_nelm), "ALGO": "Normal"},
        )
    return None


def create_recovery_attempt(
    task_dir,
    plan,
    attempt_number,
    contcar_path=None,
    apply_patch=True,
):
    root = Path(task_dir)
    attempt_number = int(attempt_number)
    attempt = root / "attempts" / f"attempt_{attempt_number:02d}"
    while attempt.exists():
        attempt_number += 1
        attempt = root / "attempts" / f"attempt_{attempt_number:02d}"
    before = attempt / "before"
    before.mkdir(parents=True, exist_ok=False)
    for name in (
        "POSCAR",
        "INCAR",
        "KPOINTS",
        "POTCAR",
        "Svasp.sh",
        "OUTCAR",
        "OSZICAR",
        "CONTCAR",
    ):
        source = root / name
        if source.is_file():
            shutil.copy2(source, before / name)
    patch = {
        str(key).upper(): str(value)
        for key, value in (plan.incar_patch or {}).items()
    }
    unknown = sorted(set(patch) - SAFE_PATCH_KEYS)
    if unknown:
        raise ValueError('Recovery plan contains a parameter outside the permitted list: ' + ", ".join(unknown))
    changes = {}
    if apply_patch and patch:
        incar_path = root / "INCAR"
        text = incar_path.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        index_by_key = {}
        for index, line in enumerate(lines):
            clean = line.split("#", 1)[0].split("!", 1)[0].strip()
            if "=" in clean:
                index_by_key[clean.split("=", 1)[0].strip().upper()] = index
        current = parse_incar_text(text)
        for key, value in patch.items():
            changes[key] = {"before": current.get(key), "after": value}
            if key in index_by_key:
                lines[index_by_key[key]] = f"{key} = {value}"
            else:
                lines.append(f"{key} = {value}")
        incar_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")
    if plan.restart_from_contcar and contcar_path and Path(contcar_path).is_file():
        shutil.copy2(contcar_path, root / "POSCAR")
        changes["POSCAR"] = {"before": "previous POSCAR", "after": "CONTCAR"}
    record = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "attempt": attempt_number,
        "plan": plan.to_dict(),
        "changes": changes,
    }
    (attempt / "recovery.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return attempt, changes


def parse_incar_text(text):
    values = {}
    for line in str(text or "").splitlines():
        clean = line.split("#", 1)[0].split("!", 1)[0].strip()
        if "=" not in clean:
            continue
        key, value = clean.split("=", 1)
        values[key.strip().upper()] = value.strip()
    return values
