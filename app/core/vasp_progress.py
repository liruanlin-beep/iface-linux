import re
from dataclasses import dataclass, field
from pathlib import Path


FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?"
ELECTRONIC_RE = re.compile(
    rf"^\s*(DAV|RMM|CG|DMP|RMM-DIIS):\s*(\d+)\s+({FLOAT})\s+({FLOAT})"
    rf"(?:\s+({FLOAT}))?(?:\s+(\d+))?(?:\s+({FLOAT}))?",
    re.MULTILINE,
)
IONIC_RE = re.compile(
    rf"^\s*(\d+)\s+F=\s*({FLOAT})\s+E0=\s*({FLOAT})\s+d\s*E\s*=\s*({FLOAT})",
    re.MULTILINE,
)
TOTEN_RE = re.compile(rf"free\s+energy\s+TOTEN\s*=\s*({FLOAT})")
FORCE_RE = re.compile(rf"FORCES:\s+max atom,\s*RMS\s*=\s*({FLOAT})")


ERROR_PATTERNS = (
    ("BRMIX", re.compile(r"BRMIX", re.I), 'Charge-density mixing failed'),
    ("ZBRENT", re.compile(r"ZBRENT", re.I), 'Ionic line search failed'),
    ("EDDDAV", re.compile(r"EDDDAV", re.I), 'Electronic diagonalization failed'),
    ("ZHEGV", re.compile(r"ZHEGV|ZPOTRF", re.I), 'Linear algebra solver failed'),
    ("TOO_FEW_BANDS", re.compile(r"TOO FEW BANDS|NBANDS.*too small", re.I), 'Insufficient bands'),
    ("OUT_OF_MEMORY", re.compile(r"out of memory|oom-kill|oom_kill", re.I), 'Out of memory'),
    ("TIME_LIMIT", re.compile(r"time limit|DUE TO TIME LIMIT", re.I), 'Slurm time limit reached'),
    ("INTERNAL_ERROR", re.compile(r"internal error in subroutine", re.I), 'Internal VASP error'),
)


@dataclass
class VaspProgress:
    ionic_step: int = 0
    max_ionic_steps: int = 0
    electronic_step: int = 0
    max_electronic_steps: int = 0
    electronic_algorithm: str = ""
    energy_ev: float = None
    delta_e_ev: float = None
    rms: float = None
    max_force_ev_a: float = None
    electronic_converged: bool = False
    ionic_converged: bool = False
    finished: bool = False
    errors: list = field(default_factory=list)
    ionic_history: list = field(default_factory=list)
    electronic_history: list = field(default_factory=list)

    def to_dict(self):
        return {
            "ionic_step": self.ionic_step,
            "max_ionic_steps": self.max_ionic_steps,
            "electronic_step": self.electronic_step,
            "max_electronic_steps": self.max_electronic_steps,
            "electronic_algorithm": self.electronic_algorithm,
            "energy_ev": self.energy_ev,
            "delta_e_ev": self.delta_e_ev,
            "rms": self.rms,
            "max_force_ev_a": self.max_force_ev_a,
            "electronic_converged": self.electronic_converged,
            "ionic_converged": self.ionic_converged,
            "finished": self.finished,
            "errors": list(self.errors),
            "ionic_history": list(self.ionic_history),
            "electronic_history": list(self.electronic_history),
        }


def parse_incar_limits(text):
    values = {}
    for raw_line in (text or "").splitlines():
        line = raw_line.split("#", 1)[0].split("!", 1)[0].strip()
        if "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        values[key.upper()] = value
    return {
        "NELM": _as_int(values.get("NELM"), 60),
        "NSW": _as_int(values.get("NSW"), 0),
        "EDIFF": _as_float(values.get("EDIFF"), 1e-4),
        "EDIFFG": _as_float(values.get("EDIFFG"), 0.0),
    }


def parse_vasp_progress(oszicar_text="", outcar_text="", incar_text=""):
    limits = parse_incar_limits(incar_text)
    progress = VaspProgress(
        max_ionic_steps=limits["NSW"],
        max_electronic_steps=limits["NELM"],
    )

    electronic_matches = list(ELECTRONIC_RE.finditer(oszicar_text or ""))
    for match in electronic_matches:
        item = {
            "algorithm": match.group(1),
            "step": int(match.group(2)),
            "energy_ev": float(match.group(3)),
            "delta_e_ev": float(match.group(4)),
            "rms": float(match.group(7)) if match.group(7) else None,
        }
        progress.electronic_history.append(item)
    if progress.electronic_history:
        current = progress.electronic_history[-1]
        progress.electronic_step = current["step"]
        progress.electronic_algorithm = current["algorithm"]
        progress.delta_e_ev = current["delta_e_ev"]
        progress.rms = current["rms"]
        progress.electronic_converged = abs(current["delta_e_ev"]) <= limits["EDIFF"]

    for match in IONIC_RE.finditer(oszicar_text or ""):
        progress.ionic_history.append(
            {
                "step": int(match.group(1)),
                "free_energy_ev": float(match.group(2)),
                "energy_zero_ev": float(match.group(3)),
                "delta_e_ev": float(match.group(4)),
            }
        )
    if progress.ionic_history:
        current = progress.ionic_history[-1]
        progress.ionic_step = current["step"]
        progress.energy_ev = current["energy_zero_ev"]

    outcar_text = outcar_text or ""
    toten = TOTEN_RE.findall(outcar_text)
    if toten:
        progress.energy_ev = float(toten[-1])
    forces = FORCE_RE.findall(outcar_text)
    if forces:
        progress.max_force_ev_a = float(forces[-1])

    lowered = outcar_text.lower()
    progress.ionic_converged = "reached required accuracy" in lowered
    progress.finished = "general timing and accounting informations" in lowered
    progress.errors = detect_vasp_errors(oszicar_text + "\n" + outcar_text)
    return progress


def parse_vasp_progress_directory(directory, max_bytes=8 * 1024 * 1024):
    """Read a calculation directory without loading an arbitrarily large OUTCAR."""
    directory = Path(directory)
    return parse_vasp_progress(
        oszicar_text=_read_recent_text(directory / "OSZICAR", max_bytes),
        outcar_text=_read_recent_text(directory / "OUTCAR", max_bytes),
        incar_text=_read_recent_text(directory / "INCAR", 256 * 1024),
    )


def calculate_progress_percent(progress):
    """Return a stable 0..100 percentage for a VASP progress object or dict."""
    getter = progress.get if isinstance(progress, dict) else lambda key, default=None: getattr(progress, key, default)
    if getter("finished", False):
        return 100.0
    ionic = max(0, int(getter("ionic_step", 0) or 0))
    max_ionic = max(0, int(getter("max_ionic_steps", 0) or 0))
    electronic = max(0, int(getter("electronic_step", 0) or 0))
    max_electronic = max(0, int(getter("max_electronic_steps", 0) or 0))
    if max_ionic:
        within_step = min(1.0, electronic / max(1, max_electronic))
        return min(99.0, 100.0 * (ionic + within_step) / max_ionic)
    if max_electronic:
        return min(99.0, 100.0 * electronic / max_electronic)
    return 0.0


def _read_recent_text(path, max_bytes):
    path = Path(path)
    if not path.is_file():
        return ""
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(-max_bytes, 2)
            handle.readline()
        raw = handle.read(max_bytes)
    return raw.decode("utf-8", errors="ignore")


def detect_vasp_errors(text):
    findings = []
    for code, pattern, message in ERROR_PATTERNS:
        if pattern.search(text or ""):
            findings.append({"code": code, "message": message})
    return findings


def _as_int(value, default):
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _as_float(value, default):
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default
