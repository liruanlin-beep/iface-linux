"""Streaming result inspection; absent values remain unknown, never zero."""

import csv
import io
import json
from pathlib import Path
import re

import numpy as np

from iface.formats import FLOAT, Poscar, read_incar, number
from iface.geometry import minimum_image


def inspect_calculation(directory):
    root = Path(directory)
    result = {"directory": str(root.resolve()), "energy_ev": None, "energy_source": None, "ionic_steps": 0,
              "electronic_step": None, "max_force_ev_a": None, "magnetization": None,
              "finished": False, "ionic_converged": False, "status": "not_started",
              "atom_count": None, "errors": [], "warnings": [],
              "force_table_rows": None, "force_table_complete": None}
    initial = None
    if (root / "POSCAR").is_file():
        try:
            initial = Poscar.read(root / "POSCAR")
            result["atom_count"] = initial.atom_count
        except (ValueError, OSError) as exc:
            result["warnings"].append(str(exc))
    outcar = root / "OUTCAR"
    force_rows = None
    last_force_rows = None
    nions = None
    if outcar.is_file():
        result["status"] = "incomplete"
        with outcar.open(encoding="utf-8", errors="replace") as stream:
            for line_number, line in enumerate(stream, 1):
                match = re.search(r"\bNIONS\s*=\s*(\d+)", line)
                if match:
                    nions = int(match.group(1))
                match = re.search(r"free\s+energy\s+TOTEN\s*=\s*(" + FLOAT + ")", line)
                if match:
                    result["energy_ev"] = number(match.group(1))
                    result["energy_source"] = "OUTCAR:TOTEN"
                    result["ionic_steps"] += 1
                if "reached required accuracy" in line.lower():
                    result["ionic_converged"] = True
                if "General timing and accounting" in line:
                    result["finished"] = True
                match = re.search(r"FORCES:\s+max atom, RMS\s*=\s*(" + FLOAT + ")", line)
                if match:
                    result["max_force_ev_a"] = number(match.group(1))
                if "TOTAL-FORCE (eV/Angst)" in line:
                    force_rows = []
                    continue
                if force_rows is not None:
                    fields = line.split()
                    if len(fields) == 6:
                        try:
                            values = [number(v) for v in fields]
                            force_rows.append(values[3:6])
                            continue
                        except ValueError:
                            pass
                    if force_rows or (fields and set(line.strip()) != {"-"}):
                        last_force_rows = force_rows
                        force_rows = None
                upper = line.upper()
                key = "errors" if any(x in upper for x in ("ERROR", "VERY BAD NEWS", "ZBRENT: FATAL")) else "warnings"
                if key == "errors" or "WARNING" in upper:
                    if len(result[key]) < 30:
                        result[key].append(f"OUTCAR:{line_number}: {line.strip()[:240]}")
        # EOF is a valid terminator when all known atom rows are present.
        if force_rows is not None:
            last_force_rows = force_rows
    if result["atom_count"] is None and nions is not None and nions > 0:
        result["atom_count"] = nions
    count_conflict = initial is not None and nions is not None and nions != initial.atom_count
    if count_conflict:
        result["warnings"].append(
            f"OUTCAR NIONS ({nions}) differs from the POSCAR atom count ({initial.atom_count}).")
    if last_force_rows is not None:
        rows = len(last_force_rows)
        expected = result["atom_count"]
        result["force_table_rows"] = rows
        result["force_table_complete"] = bool(expected and rows == expected and not count_conflict)
        # Never retain an older force or a summary when the latest table is incomplete.
        result["max_force_ev_a"] = None
        if result["force_table_complete"]:
            result["max_force_ev_a"] = float(np.max(np.linalg.norm(last_force_rows, axis=1)))
        elif expected is None:
            result["warnings"].append(
                "Cannot verify the final force table: no valid POSCAR atom count or OUTCAR NIONS is available.")
        else:
            result["warnings"].append(
                f"The final force table is incomplete or inconsistent: {rows} rows for {expected} expected atoms; maximum force is unknown.")
    oszicar = root / "OSZICAR"
    oszicar_energy = None
    if oszicar.is_file():
        with oszicar.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                step = re.match(r"\s*(?:DAV|RMM|CG):\s*(\d+)", line)
                if step:
                    result["electronic_step"] = int(step.group(1))
                energy = re.match(r"\s*(\d+)\s+F=\s*(" + FLOAT + ")", line)
                if energy:
                    oszicar_energy = number(energy.group(2))
                    result["ionic_steps"] = max(result["ionic_steps"], int(energy.group(1)))
                mag = re.search(r"mag=\s*(" + FLOAT + ")", line)
                if mag:
                    result["magnetization"] = number(mag.group(1))
    if result["energy_ev"] is None and oszicar_energy is not None:
        result["energy_ev"] = oszicar_energy
        result["energy_source"] = "OSZICAR:F"
    if result["errors"]:
        result["status"] = "error"
    elif result["finished"]:
        result["status"] = "finished"
    elif oszicar.is_file():
        result["status"] = "incomplete"
    # A normal program exit does not prove electronic or ionic convergence.
    result["electronic_convergence"] = "not_assessed"
    if initial is not None:
        try:
            if (root / "CONTCAR").is_file() and (root / "CONTCAR").stat().st_size:
                final = Poscar.read(root / "CONTCAR")
                if initial.species == final.species and initial.counts == final.counts:
                    if np.allclose(initial.cell, final.cell, atol=1e-7, rtol=1e-7):
                        displacement = minimum_image(final.fractional - initial.fractional, initial.cell)
                        result["max_displacement_a"] = float(np.max(np.linalg.norm(displacement @ initial.cell, axis=1)))
                    else:
                        result["warnings"].append("Cell changed; a fixed-cell displacement comparison was omitted.")
        except (ValueError, OSError) as exc:
            result["warnings"].append(str(exc))
    return result


def inspect_tree(directory, recursive=False, limit=1000):
    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"Calculation directory does not exist: {root}")
    if not recursive:
        return [inspect_calculation(root)]
    import os
    directories = []
    for current, children, files in os.walk(root, followlinks=False):
        children[:] = sorted(c for c in children if not c.startswith("."))
        if any(name in files for name in ("OUTCAR", "OSZICAR", "POSCAR")):
            directories.append(Path(current))
            if len(directories) > limit:
                raise ValueError(f"The scan exceeds {limit} calculations. Select a smaller directory.")
    return [inspect_calculation(path) for path in directories]


def convergence_report(directory, tolerance_mev_atom=1.0):
    root = Path(directory)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("kind") != "convergence":
        raise ValueError("The directory is not an iface convergence sweep.")
    if number(tolerance_mev_atom) <= 0:
        raise ValueError("The convergence tolerance must be positive.")
    rows = []
    for case in manifest["cases"]:
        path = (root / case["directory"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("The sweep manifest contains a path outside its root.")
        report = inspect_calculation(path)
        rows.append(dict(value=case["value"], **report))
    parameter = manifest["parameter"]
    def density(row):
        return row["value"] if parameter == "encut" else int(np.prod(row["value"]))
    rows.sort(key=density)
    reference = rows[-1] if rows else None
    usable = lambda row: row is not None and row["finished"] and not row["errors"] and row["energy_ev"] is not None and row["atom_count"]
    for row in rows:
        delta = None
        if usable(reference) and usable(row) and row["atom_count"] == reference["atom_count"]:
            delta = 1000 * (row["energy_ev"] - reference["energy_ev"]) / row["atom_count"]
        row["delta_mev_atom"] = delta
        row["within_tolerance"] = delta is not None and abs(delta) <= tolerance_mev_atom
    return {"parameter": parameter, "reference": reference["value"] if usable(reference) else None,
            "tolerance_mev_atom": tolerance_mev_atom, "cases": rows,
            "note": "Energy differences are a screening aid. Verify electronic convergence; test denser settings independently."}


def results_csv(rows):
    fields = ["directory", "status", "energy_ev", "energy_source", "atom_count", "ionic_steps", "electronic_step",
              "max_force_ev_a", "magnetization", "finished", "ionic_converged"]
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()
