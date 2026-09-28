"""The original iface A/B, layer and spacing scan, available without a GUI."""

from collections import defaultdict
import csv
import io
import itertools
import json
import math
from pathlib import Path
import re

from iface.files import new_directory, write_json, write_new
from iface.formats import Poscar
from iface.results import inspect_calculation
from iface.structures import _interface_metadata, _load_ordered, _miller


MAX_SCAN_MODELS = 300


def _layers(values, label):
    values = tuple(values)
    if not values or any(not math.isfinite(float(value)) or int(value) != value or value < 1
                         for value in values):
        raise ValueError(f"{label} must contain positive integer layer counts.")
    return tuple(dict.fromkeys(int(value) for value in values))


def interface_scan(substrates, films, output, substrate_layer_values=(6,), film_layer_values=(6,),
                   gaps=(2.5,), substrate_miller=(1, 0, 0), film_miller=(1, 0, 0),
                   max_strain=0.05, max_area=500, max_atoms=1000, limit_per_gap=1,
                   lateral_offsets=((0.0, 0.0),)):
    """Build every requested A/B x layer x gap combination using the original engine.

    The candidate limit applies separately to each gap, so early matches cannot
    consume the allocation for later spacings. A failed combination aborts the
    staged export instead of silently publishing an incomplete scan.
    """
    substrates = [Path(value).expanduser().resolve() for value in substrates]
    films = [Path(value).expanduser().resolve() for value in films]
    if not substrates or not films:
        raise ValueError("Choose at least one substrate A and one film B.")
    a_layers = _layers(substrate_layer_values, "Substrate layers")
    b_layers = _layers(film_layer_values, "Film layers")
    gaps = tuple(dict.fromkeys(float(value) for value in gaps))
    if not gaps or any(not math.isfinite(value) or not 0.5 <= value <= 10 for value in gaps):
        raise ValueError("Every gap must be finite and between 0.5 and 10 angstrom.")
    _miller(substrate_miller)
    _miller(film_miller)
    if not math.isfinite(float(max_strain)) or not 0 < max_strain <= 0.25:
        raise ValueError("Maximum strain must be finite, positive and at most 25%.")
    if not math.isfinite(float(max_area)) or max_area <= 0:
        raise ValueError("Maximum area must be finite and positive.")
    if not math.isfinite(float(max_atoms)) or int(max_atoms) != max_atoms or not 1 <= max_atoms <= 1000:
        raise ValueError("Maximum atoms must be an integer between 1 and 1000.")
    if (not math.isfinite(float(limit_per_gap)) or int(limit_per_gap) != limit_per_gap
            or not 1 <= limit_per_gap <= MAX_SCAN_MODELS):
        raise ValueError("The candidate limit per gap must be an integer between 1 and 300.")
    lateral_offsets = tuple(tuple(float(value) for value in offset) for offset in lateral_offsets)
    if not lateral_offsets or any(len(offset) != 2 or not all(math.isfinite(v) for v in offset)
                                  for offset in lateral_offsets):
        raise ValueError("Every lateral offset must contain two finite fractional coordinates.")
    combinations = len(substrates) * len(films) * len(a_layers) * len(b_layers) * len(gaps)
    estimate = combinations * int(limit_per_gap)
    if estimate > MAX_SCAN_MODELS:
        raise ValueError(f"The scan could produce {estimate} models; the maximum is {MAX_SCAN_MODELS}.")
    structures = {path: _load_ordered(path) for path in dict.fromkeys(substrates + films)}
    from iface.core.interface_builder import search_interface_candidates
    from pymatgen.io.vasp import Poscar as PmgPoscar

    rows = []
    with new_directory(output) as stage:
        for (a_index, substrate), (b_index, film), a_count, b_count, gap in itertools.product(
                enumerate(substrates, 1), enumerate(films, 1), a_layers, b_layers, gaps):
            pair_id = f"A{a_index:02d}_B{b_index:02d}"
            candidates = search_interface_candidates(
                structures[substrate], structures[film], substrate_miller=substrate_miller,
                film_miller=film_miller, substrate_layers=a_count, film_layers=b_count,
                gap_values=[gap], max_strain=max_strain, max_area=max_area, max_atoms=max_atoms,
                limit=int(limit_per_gap), lateral_offsets=lateral_offsets)
            if not candidates:
                raise ValueError(f"No interface matches for {pair_id}, layers {a_count}/{b_count}, "
                                 f"gap {gap:g} A. No partial scan was published.")
            for index, candidate in enumerate(candidates, 1):
                if len(rows) >= MAX_SCAN_MODELS:
                    raise ValueError("The geometry engine exceeded the 300-model scan limit.")
                gap_label = f"{gap:.10g}".replace(".", "p")
                name = f"{pair_id}_L{a_count:02d}-{b_count:02d}_D{gap_label}_{index:03d}"
                write_new(stage / name / "POSCAR",
                          PmgPoscar(candidate.structure.get_sorted_structure()).get_str())
                row = _interface_metadata(candidate, name, substrate, film, a_count, b_count, pair_id)
                row.update(substrate_miller=list(substrate_miller), film_miller=list(film_miller))
                rows.append(row)
                write_json(stage / name / "model.json", row)
        manifest = {"kind": "interface_scan", "schema_version": 2,
                    "requested_gaps_a": list(gaps), "substrate_layer_values": list(a_layers),
                    "film_layer_values": list(b_layers), "combinations": combinations,
                    "limit_per_gap": int(limit_per_gap), "candidates": rows,
                    "note": "Geometric scores rank matching quality, not physical stability. "
                            "Run consistent VASP static calculations before comparing spacings."}
        write_json(stage / "manifest.json", manifest)
    return {"directory": str(Path(output).resolve()), "models": len(rows),
            "combinations": combinations, "candidates": rows}


def _comparison_key(row, geometry):
    required = ("pair_id", "source_a", "source_b", "substrate_layers", "film_layers", "termination", "offset")
    if any(row.get(name) is None for name in required) or geometry is None:
        return None
    composition = defaultdict(int)
    for element, count in zip(geometry.species, geometry.counts):
        composition[element] += count
    # Compare the in-plane metric, independent of rigid rotation and vacuum/gap.
    a, b = geometry.cell[:2]
    metric = [round(float(a @ a), 6), round(float(a @ b), 6), round(float(b @ b), 6)]
    payload = {name: row[name] for name in required}
    payload.update(atoms=geometry.atom_count, composition=dict(composition), in_plane_metric=metric,
                   substrate_miller=row.get("substrate_miller"), film_miller=row.get("film_miller"))
    return json.dumps(payload, sort_keys=True, allow_nan=False)


def _composition(geometry):
    result = defaultdict(int)
    for element, count in zip(geometry.species, geometry.counts):
        result[element] += count
    return dict(result)


def _result_geometry(case, result_dir, expected_atoms, result_atoms):
    """Check result identity against the exported input before using an energy."""
    geometry, initial = None, None
    warnings, errors = [], []
    parsed = []
    paths = dict.fromkeys((result_dir / "CONTCAR", result_dir / "POSCAR", case / "POSCAR"))
    for path in paths:
        if path.is_file() and path.stat().st_size:
            try:
                current = Poscar.read(path)
            except (OSError, ValueError) as exc:
                warnings.append(f"Invalid geometry in {path}: {exc}")
                continue
            parsed.append((path, current))
            if geometry is None:
                geometry = current
            if path == case / "POSCAR":
                initial = current
    reference = initial or geometry
    if reference is not None:
        if expected_atoms is not None and reference.atom_count != expected_atoms:
            errors.append("The scan manifest atom count differs from the exported POSCAR.")
        for path, current in parsed:
            if _composition(current) != _composition(reference):
                errors.append(f"Atom counts/species in {path} differ from the exported POSCAR.")
        if result_atoms is not None and result_atoms != reference.atom_count:
            errors.append("The reported result atom count differs from the exported POSCAR.")
        outcar = result_dir / "OUTCAR"
        if outcar.is_file():
            with outcar.open(encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    match = re.search(r"\bNIONS\s*=\s*(\d+)", line)
                    if match and int(match.group(1)) != reference.atom_count:
                        errors.append("OUTCAR NIONS differs from the exported POSCAR atom count.")
                        break
    return geometry, warnings, errors


def inspect_interface_scan(output):
    """Inspect spacing energies without changing inputs or reporting unrun models as results."""
    root = Path(output).expanduser().resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    candidates = manifest.get("candidates", [])
    if manifest.get("kind") != "interface_scan" or not candidates or len(candidates) > MAX_SCAN_MODELS:
        raise ValueError("Choose an iface interface scan containing 1 to 300 models.")
    requested_gaps = set(manifest.get("requested_gaps_a", []))
    rows, groups = [], defaultdict(list)
    for candidate in candidates:
        case = (root / candidate["directory"]).resolve()
        if not case.is_relative_to(root) or case == root:
            raise ValueError("A candidate directory escapes the scan output directory.")
        result_dir = case / "02_static" if (case / "02_static").is_dir() else case
        result = inspect_calculation(result_dir)
        geometry, geometry_warnings, geometry_errors = _result_geometry(
            case, result_dir, candidate.get("atoms"), result["atom_count"])
        errors = result["errors"] + geometry_errors
        ranking_valid = geometry is not None and not errors and not geometry_warnings
        completed = bool(result["finished"] and ranking_valid and result["energy_ev"] is not None)
        row = dict(candidate, energy_ev=result["energy_ev"], energy_source=result["energy_source"],
                   result_directory=str(result_dir), finished=result["finished"],
                   energy_status="completed_unverified_convergence" if completed else "provisional",
                   errors=errors, warnings=result["warnings"] + geometry_warnings,
                   ranking_valid=ranking_valid,
                   energy_per_atom_ev=None, relative_energy_ev=None, adjacent_delta_ev=None,
                   provisional_relative_energy_ev=None, best_spacing=False,
                   provisional_minimum=False, comparison_group=None, group_complete=False)
        if row["energy_ev"] is not None and geometry is not None:
            row["energy_per_atom_ev"] = row["energy_ev"] / geometry.atom_count
        key = _comparison_key(row, geometry)
        if key is None:
            row["warnings"].append("Missing scan identity or valid geometry; spacing ranking was omitted.")
        else:
            groups[key].append(row)
        rows.append(row)
    group_reports = []
    for index, members in enumerate(groups.values(), 1):
        group_id = f"group_{index:03d}"
        observed = [row for row in members if row["energy_ev"] is not None and row["ranking_valid"]]
        complete = (all(row["energy_status"] == "completed_unverified_convergence" for row in members)
                    and (not requested_gaps or requested_gaps.issubset({row["gap_a"] for row in members})))
        for row in members:
            row.update(comparison_group=group_id, group_complete=complete)
        if observed:
            minimum = min(row["energy_ev"] for row in observed)
            for row in observed:
                row["provisional_relative_energy_ev"] = row["energy_ev"] - minimum
                row["provisional_minimum"] = math.isclose(row["energy_ev"], minimum, abs_tol=1e-10, rel_tol=0)
            if complete:
                ordered = sorted(observed, key=lambda row: row["gap_a"])
                for position, row in enumerate(ordered):
                    row["relative_energy_ev"] = row["energy_ev"] - minimum
                    row["best_spacing"] = row["provisional_minimum"]
                    if position:
                        row["adjacent_delta_ev"] = row["energy_ev"] - ordered[position - 1]["energy_ev"]
        group_reports.append({"group": group_id, "models": len(members), "complete": complete,
                              "observed_energies": len(observed),
                              "best_gap_a": [row["gap_a"] for row in members if row["best_spacing"]]})
    buffer = io.StringIO(newline="")
    fields = ["directory", "pair_id", "substrate_layers", "film_layers", "gap_a", "atoms",
              "energy_ev", "energy_status", "comparison_group", "relative_energy_ev", "adjacent_delta_ev",
              "provisional_relative_energy_ev", "best_spacing", "group_complete"]
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return {"directory": str(root), "models": len(rows), "rows": rows, "groups": group_reports,
            "csv": buffer.getvalue(),
            "note": "Compare total energies only within the same A/B pair, layers, composition, "
                    "termination, offset and in-plane matching geometry. Finished means normal VASP exit; "
                    "electronic convergence and consistent INCAR/KPOINTS/POTCAR still require verification. "
                    "Incomplete scans have provisional minima only. Geometric scores are not energies, "
                    "and energy per atom is not an interface formation energy. gap_a and best_gap_a refer "
                    "to requested initial spacings, not remeasured relaxed CONTCAR gaps. A fixed-gap "
                    "energy curve requires unrelaxed, fixed-geometry static calculations (NSW=0) with "
                    "consistent physical settings."}
