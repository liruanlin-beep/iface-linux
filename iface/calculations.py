"""Optimization/static inputs, exact POTCAR selection, and convergence sweeps."""

from pathlib import Path
import re
import shutil

from iface.files import new_directory, write_new, write_json, fingerprint
from iface.formats import Poscar, read_incar, incar_text, kpoints_text, number


PRESETS = {
    "relax": {"PREC": "Accurate", "EDIFF": "1E-6", "EDIFFG": "-0.02", "IBRION": "2",
              "ISIF": "3", "NSW": "200", "ISMEAR": "0", "SIGMA": "0.05", "LREAL": "Auto"},
    "surface": {"PREC": "Accurate", "EDIFF": "1E-6", "EDIFFG": "-0.02", "IBRION": "2",
                "ISIF": "2", "NSW": "200", "ISMEAR": "0", "SIGMA": "0.05", "LREAL": "Auto"},
    "static": {"PREC": "Accurate", "EDIFF": "1E-7", "IBRION": "-1", "NSW": "0",
               "ISMEAR": "0", "SIGMA": "0.05", "LCHARG": ".TRUE.", "LWAVE": ".FALSE."},
    "pdos": {"PREC": "Accurate", "EDIFF": "1E-7", "IBRION": "-1", "NSW": "0",
             "ISMEAR": "0", "SIGMA": "0.05", "LORBIT": "11", "NEDOS": "2001",
             "LCHARG": ".TRUE.", "LWAVE": ".FALSE."},
    "charge": {"PREC": "Accurate", "EDIFF": "1E-7", "IBRION": "-1", "NSW": "0",
               "ISMEAR": "0", "SIGMA": "0.05", "LCHARG": ".TRUE.", "LAECHG": ".TRUE."},
}


def potcar_bytes(poscar, library, variants=None):
    """Use exact variant names; never silently substitute a different potential."""
    root = Path(library).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"POTCAR library directory is unavailable: {root}")
    choices = list(variants) if variants else list(poscar.species)
    if len(choices) != len(poscar.species):
        raise ValueError("Provide one potential name per POSCAR species group, in order.")
    chunks = []
    for element, variant in zip(poscar.species, choices):
        if not re.fullmatch(re.escape(element) + r"(?:_[A-Za-z0-9]+)*", variant):
            raise ValueError(f"Potential {variant!r} does not match element {element}.")
        path = root / variant / "POTCAR"
        if not path.is_file():
            raise FileNotFoundError(f"Potential not found: {path}. Select its exact variant explicitly.")
        payload = path.read_bytes()
        found = potcar_elements(payload.decode("utf-8", errors="replace"))
        if found != [element] or "End of Dataset" not in payload.decode("utf-8", errors="replace"):
            raise ValueError(f"Potential has invalid element metadata or is incomplete: {path}")
        chunks.append(payload.rstrip() + b"\n")
    return b"".join(chunks)


def potcar_elements(text):
    result = re.findall(r"VRHFIN\s*=\s*([A-Z][a-z]?)\s*:", text)
    if result:
        return result
    return re.findall(r"TITEL\s*=\s*\S+\s+([A-Z][a-z]?)(?:_[A-Za-z0-9]+)*\b", text)


def prepare(structure, output, preset="relax", encut=520, mesh=(7, 7, 1),
            potcar_root=None, variants=None, scheduler="slurm", partition="",
            nodes=1, tasks=1, walltime="01:00:00", executable="vasp_std", name="iface"):
    from iface.scheduler import script_text

    poscar = Poscar.read(structure)
    if preset not in PRESETS or number(encut) <= 0:
        raise ValueError("Select a supported preset and a positive ENCUT value.")
    params = dict(PRESETS[preset], ENCUT=f"{number(encut):g}")
    potentials = potcar_bytes(poscar, potcar_root, variants) if potcar_root else None
    script = script_text(scheduler, name, partition, nodes, tasks, walltime, executable)
    with new_directory(output) as stage:
        write_new(stage / "POSCAR", poscar.text())
        write_new(stage / "INCAR", incar_text(params))
        write_new(stage / "KPOINTS", kpoints_text(mesh))
        write_new(stage / "job.sh", script)
        if potentials:
            write_new(stage / "POTCAR", potentials)
        manifest = {"kind": preset, "scheduler": scheduler, "source": str(Path(structure).resolve()),
                    "atom_count": poscar.atom_count, "ready_for_preflight": bool(potentials),
                    "input_sha256": fingerprint(stage), "note": "Review physical settings before submission."}
        write_json(stage / "manifest.json", manifest)
    return dict(manifest, directory=str(Path(output).resolve()))


def to_static(source, output):
    root = Path(source)
    poscar = Poscar.read(root / "CONTCAR")
    params = read_incar(root / "INCAR")
    params.update(IBRION="-1", NSW="0", LCHARG=".TRUE.", LWAVE=".FALSE.")
    for key in ("IMAGES", "LCLIMB", "SPRING", "IOPT", "ICHAIN"):
        params.pop(key, None)
    # Do not silently change XC, spin, smearing, or pseudopotentials.
    with new_directory(output) as stage:
        write_new(stage / "POSCAR", poscar.text())
        write_new(stage / "INCAR", incar_text(params))
        for name in ("KPOINTS", "POTCAR", "job.sh"):
            if not (root / name).is_file():
                raise FileNotFoundError(f"Required source file is missing: {root / name}")
            shutil.copyfile(root / name, stage / name)
        write_json(stage / "manifest.json", {"kind": "static", "source": str(root.resolve()),
                                             "input_sha256": fingerprint(stage)})
    return {"directory": str(Path(output).resolve()), "kind": "static"}


def convergence_sweep(source, output, parameter, values):
    root = Path(source)
    Poscar.read(root / "POSCAR")
    params = read_incar(root / "INCAR")
    if int(params.get("NSW", "0")) != 0:
        raise ValueError("Convergence tests require a static INCAR (NSW = 0) and a fixed geometry.")
    if parameter not in ("encut", "kpoints"):
        raise ValueError("Sweep parameter must be encut or kpoints.")
    if not values or len(values) > 300:
        raise ValueError("A sweep must contain 1 to 300 values.")
    normalized = []
    for value in values:
        if parameter == "encut":
            value = number(value)
            if value <= 0:
                raise ValueError("ENCUT values must be positive.")
        else:
            kpoints_text(value)
            value = tuple(int(v) for v in value)
        if value in normalized:
            raise ValueError("Sweep values must be unique.")
        normalized.append(value)
    for name in ("POSCAR", "INCAR", "KPOINTS", "POTCAR", "job.sh"):
        if not (root / name).is_file():
            raise FileNotFoundError(f"Required input is missing: {root / name}")
    cases = []
    with new_directory(output) as stage:
        for i, value in enumerate(normalized):
            case_name = f"{parameter}_{i + 1:03d}"
            destination = stage / case_name
            destination.mkdir()
            for name in ("POSCAR", "POTCAR", "job.sh"):
                shutil.copyfile(root / name, destination / name)
            current = dict(params)
            if parameter == "encut":
                current["ENCUT"] = f"{value:g}"
                shutil.copyfile(root / "KPOINTS", destination / "KPOINTS")
            else:
                write_new(destination / "KPOINTS", kpoints_text(value))
            write_new(destination / "INCAR", incar_text(current))
            cases.append({"directory": case_name, "value": value, "input_sha256": fingerprint(destination)})
        write_json(stage / "manifest.json", {"kind": "convergence", "parameter": parameter, "cases": cases})
    return {"directory": str(Path(output).resolve()), "parameter": parameter, "cases": cases}
