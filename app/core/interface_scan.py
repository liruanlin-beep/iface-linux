import csv
import json
import shutil
from collections import defaultdict
from pathlib import Path

from app.core.result_analysis import parse_vasp_results


MAX_SCAN_MODELS = 300


def inclusive_integer_range(start, stop, step):
    """Return a validated inclusive integer scan axis."""
    start = int(start)
    stop = int(stop)
    step = int(step)
    if start < 1 or stop < 1:
        raise ValueError('Layer counts must be at least 1.')
    if stop < start:
        raise ValueError('Maximum layers cannot be less than minimum layers.')
    if step < 1:
        raise ValueError('Layer increment must be at least 1.')
    return list(range(start, stop + 1, step))


def inclusive_float_range(start, stop, step, minimum=0.5, maximum=10.0):
    """Return an inclusive float scan axis without cumulative rounding drift."""
    start = float(start)
    stop = float(stop)
    step = float(step)
    if stop < start:
        raise ValueError('Maximum spacing cannot be less than minimum spacing.')
    if step <= 0:
        raise ValueError('Spacing increment must be positive.')
    if start < minimum or stop > maximum:
        raise ValueError(f'Interface spacing must be within {minimum:g}–{maximum:g} A.')
    count = int((stop - start) / step + 1e-9)
    values = [round(start + index * step, 10) for index in range(count + 1)]
    if not values or values[-1] < stop - 1e-9:
        values.append(round(stop, 10))
    return values


def estimate_scan_models(
    substrate_count,
    film_count,
    substrate_layers,
    film_layers,
    gaps,
    candidates_per_combination=1,
):
    film_count = max(1, int(film_count))
    return (
        int(substrate_count)
        * film_count
        * len(substrate_layers)
        * len(film_layers)
        * len(gaps)
        * max(1, int(candidates_per_combination))
    )


def analyze_interface_project(project_root, copy_best=True):
    """Analyze all candidate static energies in one high-throughput project.

    Total energies are compared only within a structure pair/layer/atom-count
    group. Different layer counts are screened using energy per atom and are
    deliberately labelled as a preliminary comparison.
    """
    project_root = Path(project_root)
    if not project_root.is_dir():
        raise FileNotFoundError(f'Project directory does not exist: {project_root}')

    rows = []
    for manifest_path in sorted(project_root.rglob("workflow.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        candidate_root = manifest_path.parent
        static_result = parse_vasp_results(candidate_root / "02_static")
        atoms = _integer_or_none(manifest.get("atoms"))
        if atoms is None:
            atoms = _integer_or_none(static_result.get("atom_count"))
        energy = _number_or_none(static_result.get("energy_ev"))
        energy_per_atom = energy / atoms if energy is not None and atoms else None
        source_a = str(manifest.get("source_a") or 'Structure A')
        source_b = str(manifest.get("source_b") or 'Structure B')
        pair_id = str(manifest.get("scan_pair_id") or f"{source_a} × {source_b}")
        a_layers = _integer_or_none(manifest.get("substrate_layers"))
        b_layers = _integer_or_none(manifest.get("film_layers"))
        gap = _number_or_none(manifest.get("gap_a"))
        rows.append(
            {
                "candidate": str(manifest.get("candidate") or candidate_root.name),
                "candidate_root": str(candidate_root),
                "pair_id": pair_id,
                "source_a": source_a,
                "source_b": source_b,
                "substrate_layers": a_layers,
                "film_layers": b_layers,
                "gap_a": gap,
                "atoms": atoms,
                "energy_ev": energy,
                "energy_per_atom_ev": energy_per_atom,
                "relative_energy_ev": None,
                "adjacent_delta_ev": None,
                "best_spacing": False,
                "best_layer_screening": False,
                "result_stage": "02_static",
                "geometry_path": _result_geometry(candidate_root),
            }
        )

    if not rows:
        raise RuntimeError('No workflow.json was found. Create candidate calculation tasks first.')

    _rank_spacing_groups(rows)
    _rank_layer_screening(rows)
    rows.sort(
        key=lambda row: (
            row["pair_id"],
            row["substrate_layers"] or 0,
            row["film_layers"] or 0,
            row["gap_a"] if row["gap_a"] is not None else float("inf"),
            row["energy_ev"] if row["energy_ev"] is not None else float("inf"),
        )
    )

    analysis_dir = project_root / "_scan_analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    csv_path = analysis_dir / "interface_scan_results.csv"
    json_path = analysis_dir / "interface_scan_results.json"
    _write_csv(csv_path, rows)
    json_path.write_text(
        json.dumps(
            {
                "comparison_note": (
                    'Compare total energies for spacing only within the same A/B structures, layers and atom count. Energy per atom provides only preliminary screening across layer counts; rigorous interface stability requires interface formation energies.'
                ),
                "completed": sum(row["energy_ev"] is not None for row in rows),
                "total": len(rows),
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    copied = _copy_best_structures(rows, analysis_dir) if copy_best else []
    return {
        "project_root": str(project_root),
        "analysis_dir": str(analysis_dir),
        "csv": str(csv_path),
        "json": str(json_path),
        "rows": rows,
        "completed": sum(row["energy_ev"] is not None for row in rows),
        "total": len(rows),
        "best_structures": copied,
    }


def _rank_spacing_groups(rows):
    groups = defaultdict(list)
    for row in rows:
        key = (
            row["pair_id"],
            row["substrate_layers"],
            row["film_layers"],
            row["atoms"],
        )
        if row["energy_ev"] is not None and row["gap_a"] is not None:
            groups[key].append(row)

    for group_rows in groups.values():
        minimum = min(row["energy_ev"] for row in group_rows)
        for row in group_rows:
            row["relative_energy_ev"] = row["energy_ev"] - minimum

        best_by_gap = {}
        for row in group_rows:
            gap = row["gap_a"]
            current = best_by_gap.get(gap)
            if current is None or row["energy_ev"] < current["energy_ev"]:
                best_by_gap[gap] = row
        ordered = [best_by_gap[gap] for gap in sorted(best_by_gap)]
        for index, row in enumerate(ordered):
            if index:
                row["adjacent_delta_ev"] = row["energy_ev"] - ordered[index - 1]["energy_ev"]
        best = min(group_rows, key=lambda row: row["energy_ev"])
        best["best_spacing"] = True


def _rank_layer_screening(rows):
    pairs = defaultdict(list)
    for row in rows:
        if row["energy_per_atom_ev"] is not None:
            pairs[row["pair_id"]].append(row)
    for pair_rows in pairs.values():
        min(pair_rows, key=lambda row: row["energy_per_atom_ev"])[
            "best_layer_screening"
        ] = True


def _copy_best_structures(rows, analysis_dir):
    best_dir = analysis_dir / "best_structures"
    copied = []
    selected = [
        row
        for row in rows
        if (row["best_spacing"] or row["best_layer_screening"])
        and row.get("geometry_path")
    ]
    if not selected:
        return copied
    best_dir.mkdir(parents=True, exist_ok=True)
    for row in selected:
        source = Path(row["geometry_path"])
        label = "layer_screen" if row["best_layer_screening"] else "best_gap"
        name = _safe_name(
            f"{row['pair_id']}_{label}_A{row['substrate_layers']}"
            f"_B{row['film_layers']}_d{row['gap_a']}.vasp"
        )
        target = best_dir / name
        shutil.copy2(source, target)
        copied.append(str(target))
    return copied


def _result_geometry(candidate_root):
    for path in (
        candidate_root / "02_static" / "CONTCAR",
        candidate_root / "01_relax" / "CONTCAR",
        candidate_root / "02_static" / "POSCAR",
    ):
        if path.is_file():
            return str(path)
    return ""


def _write_csv(path, rows):
    fields = [
        "candidate",
        "pair_id",
        "source_a",
        "source_b",
        "substrate_layers",
        "film_layers",
        "gap_a",
        "atoms",
        "energy_ev",
        "energy_per_atom_ev",
        "relative_energy_ev",
        "adjacent_delta_ev",
        "best_spacing",
        "best_layer_screening",
        "candidate_root",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _number_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_name(value):
    text = "".join(
        character if character.isalnum() or character in "-_." else "_"
        for character in str(value)
    )
    return text[:180] or "best_structure.vasp"
