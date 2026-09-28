import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.core.input_generators import write_incar, write_kpoints, write_poscar, write_potcar
from app.core.slurm_manager import SlurmManager, sanitize_job_name
from app.core.structure_model import from_pymatgen_structure, load_structure
from app.core.task_database import TaskDatabase, TaskState
from app.core.workflow_integrity import (
    WORKFLOW_SCHEMA_VERSION,
    adaptive_workflow_identity,
    atomic_write_json,
    candidate_workflow_identity,
    existing_workflow_result,
    stage_fingerprint,
    utc_now,
)


MAGNETIC_MOMENT_GUESSES = {
    "Cr": 5.0,
    "Mn": 5.0,
    "Fe": 5.0,
    "Co": 3.0,
    "Ni": 2.0,
    "V": 3.0,
    "Ti": 2.0,
    "Cu": 1.0,
    "Gd": 7.0,
}


@dataclass
class WorkflowResult:
    root: Path
    task_ids: tuple
    stage_directories: tuple
    warnings: tuple


@dataclass
class AdaptiveWorkflowResult:
    root: Path
    task_ids: tuple
    warnings: tuple


def build_adaptive_interface_workflow(
    substrate_path,
    film_path,
    output_root,
    project_name,
    config,
    search_parameters,
    database=None,
    include_pdos=True,
    include_charge=True,
    magnetic=True,
    dft_u=None,
    vdw="none",
):
    """Create bulk-A/bulk-B relaxation followed by local interface reconstruction."""
    database = database or TaskDatabase()
    project_name = sanitize_job_name(project_name)
    root = Path(output_root) / project_name / "_adaptive_bulk"
    workflow_fingerprint, identity_payload = adaptive_workflow_identity(
        substrate_path,
        film_path,
        project_name,
        search_parameters,
        include_pdos,
        include_charge,
        magnetic,
        dft_u,
        vdw,
    )
    workflow_id = workflow_fingerprint[:20]
    manifest_path = root / "adaptive_workflow.json"
    if manifest_path.is_file():
        existing = existing_workflow_result(
            manifest_path, workflow_fingerprint, database
        )
        if existing:
            return AdaptiveWorkflowResult(
                root,
                tuple(existing.get("tasks", ())),
                tuple(existing.get("warnings", ())),
            )
    root.mkdir(parents=True, exist_ok=True)
    potcar_root = config.get("potcar_root", "")
    remote_base = str(
        config.get("default_remote_root", "/home/user/vasp_projects")
    ).rstrip("/")
    remote_root = f"{remote_base}/{project_name}/_adaptive_bulk"
    warnings = []
    task_ids = []

    def add_bulk(label, source):
        structure = load_structure(source)
        stage_dir = root / f"0{len(task_ids) + 1}_bulk_{label}_relax"
        stage_dir.mkdir(parents=True, exist_ok=True)
        write_poscar(stage_dir / "POSCAR", structure, "Direct", False)
        write_incar(
            stage_dir / "INCAR",
            _bulk_relax_incar(structure, magnetic, dft_u, vdw),
        )
        write_kpoints(stage_dir / "KPOINTS", _automatic_bulk_kmesh(structure), "Gamma")
        potcar_ready = True
        try:
            write_potcar(stage_dir / "POTCAR", structure, potcar_root)
        except (FileNotFoundError, OSError) as exc:
            potcar_ready = False
            warnings.append(f"bulk {label}: {exc}")
        slurm_settings = dict(config.get("slurm", {}))
        slurm_settings["submit_script"] = config.get("submit_script", "Svasp.sh")
        SlurmManager(
            slurm_settings,
            job_name=f"{project_name}-bulk-{label}-relax",
            script_name=config.get("submit_script", "Svasp.sh"),
        ).write(stage_dir)
        remote_path = f"{remote_root}/{stage_dir.name}"
        task_id = database.add_task(
            name=f"{project_name}-bulk-{label}-relax",
            project_id=project_name,
            task_type="vasp:bulk_relax",
            local_path=stage_dir,
            remote_path=remote_path,
            config={
                "stage": "bulk_relax",
                "source_structure": str(source),
                "magnetic": bool(magnetic),
                "dft_u": dft_u or {},
                "vdw": vdw,
                "input_ready": potcar_ready,
            },
            max_retries=config.get("high_throughput", {}).get(
                "max_automatic_retries", 3
            ),
            state=(
                TaskState.PAUSED.value
                if not potcar_ready
                else TaskState.LOCAL_WAITING.value
            ),
            workflow_id=workflow_id,
            fingerprint=stage_fingerprint(
                workflow_fingerprint, f"bulk_{label}_relax"
            ),
        )
        task_ids.append(task_id)
        return task_id, stage_dir, remote_path

    sub_id, sub_dir, sub_remote = add_bulk("A", substrate_path)
    film_id, film_dir, film_remote = add_bulk("B", film_path)
    rebuild_dir = root / "03_rebuild_interface"
    rebuild_dir.mkdir(parents=True, exist_ok=True)
    adaptive_limit = max(
        1,
        min(
            int(search_parameters.get("limit", 12)),
            int(
                config.get("high_throughput", {}).get(
                    "adaptive_candidate_limit", 3
                )
            ),
        ),
    )
    rebuild_id = database.add_task(
        name=f"{project_name}-rebuild-interface",
        project_id=project_name,
        task_type="local:interface_rebuild",
        local_path=rebuild_dir,
        dependencies=[sub_id, film_id],
        config={
            "substrate_contcar": str(sub_dir / "CONTCAR"),
            "substrate_remote_path": sub_remote,
            "film_contcar": str(film_dir / "CONTCAR"),
            "film_remote_path": film_remote,
            "output_root": str(output_root),
            "project_name": project_name,
            "search_parameters": {
                key: value
                for key, value in search_parameters.items()
                if key not in {"substrate", "film"}
            },
            "candidate_limit": adaptive_limit,
            "include_pdos": bool(include_pdos),
            "include_charge": bool(include_charge),
            "magnetic": bool(magnetic),
            "dft_u": dft_u or {},
            "vdw": vdw,
        },
        state=TaskState.BLOCKED.value,
        workflow_id=workflow_id,
        fingerprint=stage_fingerprint(
            workflow_fingerprint, "rebuild_interface"
        ),
    )
    task_ids.append(rebuild_id)
    manifest = {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "workflow_id": workflow_id,
        "workflow_fingerprint": workflow_fingerprint,
        "created_at": utc_now(),
        "mode": "adaptive_interface",
        "project": project_name,
        "substrate_source": str(substrate_path),
        "film_source": str(film_path),
        "candidate_limit": adaptive_limit,
        "include_pdos": bool(include_pdos),
        "include_charge": bool(include_charge),
        "tasks": task_ids,
        "warnings": warnings,
        "provenance": identity_payload.get("sources", {}),
    }
    atomic_write_json(manifest_path, manifest)
    return AdaptiveWorkflowResult(root, tuple(task_ids), tuple(warnings))


def build_candidate_workflow(
    candidate,
    output_root,
    project_name,
    config,
    database=None,
    include_pdos=True,
    include_charge=False,
    magnetic=True,
    dft_u=None,
    vdw="none",
):
    """Create a dependency-aware relax → static → PDOS/charge workflow."""
    structure = candidate.lightweight
    atom_count = len(structure.atoms)
    hard_limit = int(config.get("high_throughput", {}).get("hard_max_atoms", 1000))
    if atom_count > min(1000, hard_limit):
        raise ValueError(f'Candidate structure contains {atom_count} atoms; exceeds the hard limit of {min(1000, hard_limit)}。')

    project_name = sanitize_job_name(project_name)
    candidate_name = sanitize_job_name(structure.name)
    root = Path(output_root) / project_name / candidate_name
    database = database or TaskDatabase()
    workflow_fingerprint, identity_payload = candidate_workflow_identity(
        candidate,
        project_name,
        include_pdos,
        include_charge,
        magnetic,
        dft_u,
        vdw,
    )
    workflow_id = workflow_fingerprint[:20]
    manifest_path = root / "workflow.json"
    if manifest_path.is_file():
        existing = existing_workflow_result(
            manifest_path, workflow_fingerprint, database
        )
        if existing:
            return WorkflowResult(
                root,
                tuple(existing.get("tasks", ())),
                tuple(Path(item) for item in existing.get("stage_directories", ())),
                tuple(existing.get("warnings", ())),
            )
    root.mkdir(parents=True, exist_ok=True)
    potcar_root = config.get("potcar_root", "")
    remote_base = str(config.get("default_remote_root", "/home/user/vasp_projects")).rstrip("/")
    remote_candidate_root = f"{remote_base}/{project_name}/{candidate_name}"

    task_ids = []
    directories = []
    warnings = []

    def add_vasp_stage(
        folder_name,
        stage_name,
        stage_structure,
        incar,
        dependencies=None,
        parent_remote_path="",
        copy_parent_restart=False,
    ):
        stage_dir = root / folder_name
        stage_dir.mkdir(parents=True, exist_ok=True)
        write_poscar(stage_dir / "POSCAR", stage_structure, "Direct", True)
        write_incar(stage_dir / "INCAR", incar)
        write_kpoints(stage_dir / "KPOINTS", _automatic_kmesh(stage_structure), "Gamma")
        potcar_ready = True
        try:
            write_potcar(stage_dir / "POTCAR", stage_structure, potcar_root)
        except (FileNotFoundError, OSError) as exc:
            potcar_ready = False
            warnings.append(f"{folder_name}: {exc}")
        slurm_settings = dict(config.get("slurm", {}))
        slurm_settings["submit_script"] = config.get("submit_script", "Svasp.sh")
        SlurmManager(
            slurm_settings,
            job_name=f"{project_name}-{candidate_name}-{stage_name}",
            script_name=config.get("submit_script", "Svasp.sh"),
        ).write(stage_dir)

        remote_path = f"{remote_candidate_root}/{folder_name}"
        stage_config = {
            "stage": stage_name,
            "parent_remote_path": parent_remote_path,
            "copy_parent_restart": bool(copy_parent_restart and parent_remote_path),
            "magnetic": bool(magnetic),
            "dft_u": dft_u or {},
            "vdw": vdw,
            "input_ready": potcar_ready,
        }
        task_id = database.add_task(
            name=f"{candidate_name}-{stage_name}",
            project_id=project_name,
            task_type=f"vasp:{stage_name}",
            local_path=stage_dir,
            remote_path=remote_path,
            dependencies=list(dependencies or []),
            config=stage_config,
            max_retries=config.get("high_throughput", {}).get("max_automatic_retries", 3),
            state=(
                TaskState.PAUSED.value
                if not potcar_ready
                else TaskState.LOCAL_WAITING.value
                if not dependencies
                else TaskState.BLOCKED.value
            ),
            workflow_id=workflow_id,
            fingerprint=stage_fingerprint(
                workflow_fingerprint, stage_name
            ),
        )
        task_ids.append(task_id)
        directories.append(stage_dir)
        return task_id, stage_dir, remote_path

    relax_id, relax_dir, relax_remote = add_vasp_stage(
        "01_relax",
        "relax",
        structure,
        _relax_incar(structure, magnetic, dft_u, vdw),
    )
    static_id, static_dir, static_remote = add_vasp_stage(
        "02_static",
        "static",
        structure,
        _static_incar(structure, magnetic, dft_u, vdw),
        dependencies=[relax_id],
        parent_remote_path=relax_remote,
        copy_parent_restart=True,
    )
    if include_pdos:
        add_vasp_stage(
            "03_pdos",
            "pdos",
            structure,
            _pdos_incar(structure, magnetic, dft_u, vdw),
            dependencies=[static_id],
            parent_remote_path=static_remote,
            copy_parent_restart=True,
        )

    charge_enabled = False
    iface = getattr(candidate, "structure", None)
    if include_charge and hasattr(iface, "substrate_indices") and hasattr(iface, "film_indices"):
        charge_enabled = True
        substrate_structure = from_pymatgen_structure(
            iface.substrate, f"{candidate_name}_substrate"
        )
        film_structure = from_pymatgen_structure(iface.film, f"{candidate_name}_film")
        prepare_dir = root / "04_charge_prepare"
        prepare_dir.mkdir(parents=True, exist_ok=True)
        prepare_id = database.add_task(
            name=f"{candidate_name}-charge-prepare",
            project_id=project_name,
            task_type="local:charge_prepare",
            local_path=prepare_dir,
            dependencies=[relax_id],
            config={
                "relax_local_path": str(relax_dir),
                "relax_remote_path": relax_remote,
                "substrate_indices": list(iface.substrate_indices),
                "film_indices": list(iface.film_indices),
                "substrate_poscar": str(root / "05_charge_substrate" / "POSCAR"),
                "film_poscar": str(root / "06_charge_film" / "POSCAR"),
            },
            state=TaskState.BLOCKED.value,
            workflow_id=workflow_id,
            fingerprint=stage_fingerprint(
                workflow_fingerprint, "charge_prepare"
            ),
        )
        task_ids.append(prepare_id)
        directories.append(prepare_dir)
        charge_sub_id, charge_sub_dir, charge_sub_remote = add_vasp_stage(
            "05_charge_substrate",
            "charge_substrate",
            substrate_structure,
            _charge_incar(substrate_structure, magnetic, dft_u, vdw),
            dependencies=[prepare_id],
        )
        charge_film_id, charge_film_dir, charge_film_remote = add_vasp_stage(
            "06_charge_film",
            "charge_film",
            film_structure,
            _charge_incar(film_structure, magnetic, dft_u, vdw),
            dependencies=[prepare_id],
        )
        difference_dir = root / "07_charge_difference"
        difference_dir.mkdir(parents=True, exist_ok=True)
        difference_id = database.add_task(
            name=f"{candidate_name}-charge-difference",
            project_id=project_name,
            task_type="local:charge_difference",
            local_path=difference_dir,
            dependencies=[static_id, charge_sub_id, charge_film_id],
            config={
                "interface_chgcar": str(static_dir / "CHGCAR"),
                "interface_remote_path": static_remote,
                "substrate_chgcar": str(charge_sub_dir / "CHGCAR"),
                "substrate_remote_path": charge_sub_remote,
                "film_chgcar": str(charge_film_dir / "CHGCAR"),
                "film_remote_path": charge_film_remote,
                "output_dir": str(difference_dir),
            },
            state=TaskState.BLOCKED.value,
            workflow_id=workflow_id,
            fingerprint=stage_fingerprint(
                workflow_fingerprint, "charge_difference"
            ),
        )
        task_ids.append(difference_id)
        directories.append(difference_dir)
    elif include_charge:
        warnings.append('This candidate is not a two-material interface; no three-system charge-difference tasks were created.')

    manifest = {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "workflow_id": workflow_id,
        "workflow_fingerprint": workflow_fingerprint,
        "created_at": utc_now(),
        "project": project_name,
        "candidate": candidate_name,
        "atoms": atom_count,
        "area_a2": getattr(candidate, "area", None),
        "gap_a": getattr(candidate, "gap", None),
        "source_a": getattr(candidate, "source_a", ""),
        "source_b": getattr(candidate, "source_b", ""),
        "scan_pair_id": getattr(candidate, "scan_pair_id", ""),
        "substrate_layers": getattr(candidate, "substrate_layers", None),
        "film_layers": getattr(candidate, "film_layers", None),
        "termination": getattr(candidate, "label", ""),
        "lateral_offset": list(getattr(candidate, "offset", ()) or ()),
        "strain": getattr(candidate, "strain", None),
        "compatibility_percent": getattr(candidate, "compatibility_percent", None),
        "magnetic": bool(magnetic),
        "dft_u": dft_u or {},
        "vdw": vdw,
        "include_pdos": bool(include_pdos),
        "include_charge": charge_enabled,
        "tasks": task_ids,
        "stage_directories": [str(path) for path in directories],
        "warnings": warnings,
        "provenance": identity_payload.get("scan", {}),
    }
    atomic_write_json(manifest_path, manifest)
    return WorkflowResult(root, tuple(task_ids), tuple(directories), tuple(warnings))


def _common_incar(structure, magnetic, dft_u, vdw):
    params = {
        "ENCUT": "520",
        "PREC": "Accurate",
        "EDIFF": "1E-6",
        "LASPH": ".TRUE.",
        "LREAL": "Auto" if len(structure.atoms) > 80 else ".FALSE.",
        "ISPIN": "2" if magnetic else "1",
    }
    if magnetic:
        params["MAGMOM"] = _magmom_line(structure)
    if dft_u:
        params.update(_dft_u_parameters(structure, dft_u))
    vdw_key = str(vdw or "none").lower()
    if vdw_key in {"d3", "ivdw11"}:
        params["IVDW"] = "11"
    elif vdw_key in {"d3bj", "d3(bj)", "ivdw12"}:
        params["IVDW"] = "12"
    elif vdw_key in {"optb86b", "optb86b-vdw"}:
        params.update(
            {
                "GGA": "MK",
                "LUSE_VDW": ".TRUE.",
                "AGGAC": "0.0000",
                "PARAM1": "0.1234",
                "PARAM2": "1.0000",
            }
        )
    return params


def _relax_incar(structure, magnetic, dft_u, vdw):
    params = _common_incar(structure, magnetic, dft_u, vdw)
    params.update(
        {
            "IBRION": "2",
            "NSW": "160",
            "ISIF": "2",
            "EDIFFG": "-0.02",
            "ISMEAR": "1",
            "SIGMA": "0.20",
            "LWAVE": ".FALSE.",
            "LCHARG": ".TRUE.",
        }
    )
    return params


def _bulk_relax_incar(structure, magnetic, dft_u, vdw):
    params = _relax_incar(structure, magnetic, dft_u, vdw)
    params.update(
        {
            "ISIF": "3",
            "NSW": "200",
            "ISMEAR": "1",
            "SIGMA": "0.20",
        }
    )
    return params


def _static_incar(structure, magnetic, dft_u, vdw):
    params = _common_incar(structure, magnetic, dft_u, vdw)
    params.update(
        {
            "IBRION": "-1",
            "NSW": "0",
            "ISMEAR": "-5",
            "SIGMA": "0.05",
            "LORBIT": "11",
            "LWAVE": ".TRUE.",
            "LCHARG": ".TRUE.",
            "LAECHG": ".TRUE.",
            "ADDGRID": ".TRUE.",
            "ISYM": "0",
            "LREAL": ".FALSE.",
        }
    )
    return params


def _charge_incar(structure, magnetic, dft_u, vdw):
    """Single-point settings shared by all three charge-density systems."""
    params = _static_incar(structure, magnetic, dft_u, vdw)
    params.update(
        {
            "ICHARG": "2",
            "LWAVE": ".FALSE.",
            "LCHARG": ".TRUE.",
            "LAECHG": ".TRUE.",
            "ADDGRID": ".TRUE.",
            "ISYM": "0",
            "LREAL": ".FALSE.",
        }
    )
    return params


def _pdos_incar(structure, magnetic, dft_u, vdw):
    params = _static_incar(structure, magnetic, dft_u, vdw)
    params.update(
        {
            "ICHARG": "11",
            "NEDOS": "3000",
            "EMIN": "-15",
            "EMAX": "10",
            "LORBIT": "11",
        }
    )
    return params


def _magmom_line(structure):
    counts = Counter(atom.element for atom in structure.atoms)
    tokens = []
    for element in structure.elements:
        moment = MAGNETIC_MOMENT_GUESSES.get(element, 0.6)
        tokens.append(f"{counts[element]}*{moment:g}")
    return " ".join(tokens)


def _dft_u_parameters(structure, dft_u):
    if not isinstance(dft_u, dict):
        raise ValueError('DFT+U settings must map elements to U values.')
    values = []
    orbitals = []
    for element in structure.elements:
        value = dft_u.get(element)
        if value is None:
            values.append(0.0)
            orbitals.append(-1)
        else:
            values.append(float(value))
            orbitals.append(3 if element in {"Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "U"} else 2)
    if not any(value > 0 for value in values):
        raise ValueError('DFT+U requires a positive U value for at least one element.')
    return {
        "LDAU": ".TRUE.",
        "LDAUTYPE": "2",
        "LDAUL": " ".join(str(value) for value in orbitals),
        "LDAUU": " ".join(f"{value:g}" for value in values),
        "LDAUJ": " ".join("0" for _ in values),
        "LMAXMIX": "6" if any(value == 3 for value in orbitals) else "4",
    }


def _automatic_kmesh(structure, spacing=0.25):
    matrix = np.asarray(structure.cell, dtype=float)
    lengths = np.linalg.norm(matrix, axis=1)
    mesh = []
    for index, length in enumerate(lengths):
        if index == 2:
            mesh.append(1)
        else:
            mesh.append(max(1, int(math.ceil((2 * math.pi / max(length, 1e-9)) / spacing))))
    return tuple(mesh)


def _automatic_bulk_kmesh(structure, spacing=0.25):
    matrix = np.asarray(structure.cell, dtype=float)
    lengths = np.linalg.norm(matrix, axis=1)
    return tuple(
        max(1, int(math.ceil((2 * math.pi / max(length, 1e-9)) / spacing)))
        for length in lengths
    )
