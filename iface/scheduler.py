"""Local Linux Slurm/PBS commands with preflight and durable submission records."""

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

from iface.calculations import potcar_elements
from iface.files import fingerprint, write_json
from iface.formats import Poscar, read_incar, number


def script_text(scheduler="slurm", name="iface", partition="", nodes=1, tasks=1,
                walltime="01:00:00", executable="vasp_std"):
    if scheduler not in ("slurm", "pbs"):
        raise ValueError("Scheduler must be slurm or pbs.")
    for label, value in (("job name", name), ("partition", partition)):
        if value and not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            raise ValueError(f"The {label} may contain only letters, digits, dots, underscores and hyphens.")
    if not name or int(nodes) != nodes or int(tasks) != tasks or nodes < 1 or tasks < 1:
        raise ValueError("A job name and positive integer node/task counts are required.")
    if not re.fullmatch(r"\d{1,4}:[0-5]\d:[0-5]\d", walltime):
        raise ValueError("Wall time must have the form HH:MM:SS.")
    if not executable or any(c in executable for c in "\n\r\0"):
        raise ValueError("Specify the VASP executable path, without a command or arguments.")
    if scheduler == "slurm":
        lines = ["#!/bin/bash", f"#SBATCH --job-name={name}", f"#SBATCH --nodes={nodes}",
                 f"#SBATCH --ntasks-per-node={tasks}", f"#SBATCH --time={walltime}",
                 "#SBATCH --output=slurm-%j.out"]
        if partition:
            lines.append(f"#SBATCH --partition={partition}")
        lines += ["set -euo pipefail", 'cd -- "${SLURM_SUBMIT_DIR:?Missing submission directory}"',
                  "# Add your cluster's module/environment setup here.", f"srun {shlex.quote(executable)}"]
    else:
        lines = ["#!/bin/bash", f"#PBS -N {name}", f"#PBS -l select={nodes}:ncpus={tasks}:mpiprocs={tasks}",
                 f"#PBS -l walltime={walltime}", "#PBS -j oe"]
        if partition:
            lines.append(f"#PBS -q {partition}")
        lines += ["set -euo pipefail", 'cd -- "${PBS_O_WORKDIR:?Missing submission directory}"',
                  "# PBS Professional/OpenPBS syntax. Review site-specific resource settings.",
                  "# Add your cluster's module/environment setup here.",
                  f'mpirun -np {nodes * tasks} {shlex.quote(executable)}']
    return "\n".join(lines) + "\n"


def preflight(directory, scheduler="slurm"):
    root = Path(directory).resolve()
    errors, warnings = [], []
    if scheduler not in ("slurm", "pbs"):
        raise ValueError("Scheduler must be slurm or pbs.")
    for name in ("POSCAR", "INCAR", "KPOINTS", "POTCAR", "job.sh"):
        if not (root / name).is_file() or (root / name).stat().st_size == 0:
            errors.append(f"Missing or empty input: {name}")
    if errors:
        return {"directory": str(root), "ok": False, "errors": errors, "warnings": warnings}
    try:
        structure = Poscar.read(root / "POSCAR")
        params = read_incar(root / "INCAR")
        if number(params.get("ENCUT", "0")) <= 0:
            errors.append("INCAR requires an explicit positive ENCUT.")
        pot = (root / "POTCAR").read_text(encoding="utf-8", errors="replace")
        if potcar_elements(pot) != structure.species:
            errors.append("POTCAR element order does not match POSCAR species groups.")
        if pot.count("End of Dataset") != len(structure.species):
            errors.append("POTCAR is incomplete or contains an unexpected number of datasets.")
        limits = [number(v) for v in re.findall(r"ENMAX\s*=\s*([0-9.Ee+-]+)", pot)]
        if limits and number(params.get("ENCUT", "0")) < max(limits):
            warnings.append("ENCUT is below the largest POTCAR ENMAX; review convergence requirements.")
        lines = (root / "KPOINTS").read_text(encoding="utf-8").splitlines()
        if len(lines) < 4 or int(lines[1].strip()) != 0 or lines[2].strip()[:1].lower() not in ("g", "m"):
            errors.append("Preflight supports automatic Gamma/Monkhorst-Pack KPOINTS only.")
        else:
            mesh = [int(v) for v in lines[3].split()]
            if len(mesh) != 3 or min(mesh) < 1:
                errors.append("Invalid KPOINTS grid.")
        script = (root / "job.sh").read_bytes().decode("utf-8")
        directive = "#SBATCH" if scheduler == "slurm" else "#PBS"
        if directive not in script or "\r" in script or not script.startswith("#!/"):
            errors.append(f"job.sh must use LF line endings, a shebang, and {directive} directives.")
        images = int(params.get("IMAGES", "0"))
        if images:
            if not 1 <= images <= 32:
                errors.append("NEB IMAGES must be between 1 and 32.")
            else:
                for i in range(images + 2):
                    image = Poscar.read(root / f"{i:02d}" / "POSCAR")
                    from iface.neb import compatible_endpoints
                    compatible_endpoints(structure, image)
        warnings.append("Input validation does not establish physical convergence or cluster compatibility.")
    except (ValueError, OSError, IndexError) as exc:
        errors.append(str(exc))
    return {"directory": str(root), "ok": not errors, "errors": errors, "warnings": warnings,
            "input_sha256": fingerprint(root)}


def _run(argv, cwd=None, timeout=45):
    if not shutil.which(argv[0]):
        raise OSError(f"Required scheduler command is unavailable: {argv[0]}")
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                                env=dict(os.environ, LC_ALL="C"), check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{argv[0]} timed out. Check the scheduler before retrying; acceptance may be unknown.") from exc
    if result.returncode:
        raise RuntimeError(f"{argv[0]} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def submit(directory, scheduler="slurm", confirmed=False):
    if not confirmed:
        raise ValueError("Submission requires explicit confirmation (--yes).")
    root = Path(directory).resolve()
    report = preflight(root, scheduler)
    if not report["ok"]:
        raise ValueError("Preflight failed: " + "; ".join(report["errors"]))
    command = "sbatch" if scheduler == "slurm" else "qsub"
    if not shutil.which(command):
        raise OSError(f"Required scheduler command is unavailable: {command}")
    record_path = root / ".iface-submission.json"
    record = {"state": "unknown", "scheduler": scheduler, "input_sha256": report["input_sha256"],
              "directory": str(root), "note": "Reconcile with the scheduler before any retry."}
    # Exclusive creation prevents concurrent or repeated submissions. Persist
    # unknown BEFORE invoking the scheduler: a timeout may still mean accepted.
    try:
        with record_path.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ValueError("A submission record already exists. No job was submitted. Reconcile it first.") from exc
    argv = ["sbatch", "--parsable", "job.sh"] if scheduler == "slurm" else ["qsub", "job.sh"]
    output = _run(argv, cwd=root)
    job_id = output.split(";")[0].strip()
    pattern = r"\d+" if scheduler == "slurm" else r"\d+(?:\.[A-Za-z0-9_.-]+)?"
    if not re.fullmatch(pattern, job_id):
        raise RuntimeError("Unexpected scheduler response. Submission state is unknown; do not retry blindly.")
    record.update(state="submitted", job_id=job_id)
    temporary = root / ".iface-submission.tmp"
    write_json(temporary, record)
    os.replace(temporary, record_path)
    return record


def queue_status(scheduler="slurm"):
    import getpass
    if scheduler == "slurm":
        return _run(["squeue", "--user", getpass.getuser(), "--format=%.18i %.30j %.12T %.10M %.6D %R"])
    if scheduler == "pbs":
        return _run(["qstat", "-u", getpass.getuser()])
    raise ValueError("Scheduler must be slurm or pbs.")


def cancel(job_id, scheduler="slurm", confirmed=False):
    if not confirmed:
        raise ValueError("Cancellation requires explicit confirmation (--yes).")
    if scheduler not in ("slurm", "pbs") or not re.fullmatch(r"\d+(?:\.[A-Za-z0-9_.-]+)?", str(job_id)):
        raise ValueError("Invalid scheduler or job identifier.")
    output = _run(["scancel" if scheduler == "slurm" else "qdel", str(job_id)])
    return {"job_id": str(job_id), "cancellation_requested": True, "response": output}
