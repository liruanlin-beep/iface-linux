"""Deterministic identities and atomic manifests for high-throughput workflows."""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


WORKFLOW_SCHEMA_VERSION = 2


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_json(data):
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def fingerprint_payload(data):
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def file_sha256(path):
    source = Path(str(path or ""))
    if not source.is_file():
        return ""
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def structure_payload(structure):
    return {
        "cell": [
            [round(float(value), 10) for value in row]
            for row in structure.cell
        ],
        "atoms": [
            {
                "element": atom.element,
                "xyz": [
                    round(float(atom.x), 10),
                    round(float(atom.y), 10),
                    round(float(atom.z), 10),
                ],
                "fixed": bool(getattr(atom, "fixed", False)),
            }
            for atom in structure.atoms
        ],
    }


def candidate_workflow_identity(
    candidate,
    project_name,
    include_pdos,
    include_charge,
    magnetic,
    dft_u,
    vdw,
):
    payload = {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "mode": "candidate",
        "project": str(project_name),
        "structure": structure_payload(candidate.lightweight),
        "scan": {
            "source_a": getattr(candidate, "source_a", ""),
            "source_b": getattr(candidate, "source_b", ""),
            "source_a_sha256": file_sha256(
                getattr(candidate, "source_a_path", "")
            ),
            "source_b_sha256": file_sha256(
                getattr(candidate, "source_b_path", "")
            ),
            "pair_id": getattr(candidate, "scan_pair_id", ""),
            "substrate_layers": getattr(candidate, "substrate_layers", None),
            "film_layers": getattr(candidate, "film_layers", None),
            "gap_a": getattr(candidate, "gap", None),
            "termination": getattr(candidate, "label", ""),
            "offset": list(getattr(candidate, "offset", ()) or ()),
        },
        "calculation": {
            "include_pdos": bool(include_pdos),
            "include_charge": bool(include_charge),
            "magnetic": bool(magnetic),
            "dft_u": dft_u or {},
            "vdw": str(vdw or "none"),
        },
    }
    return fingerprint_payload(payload), payload


def adaptive_workflow_identity(
    substrate_path,
    film_path,
    project_name,
    search_parameters,
    include_pdos,
    include_charge,
    magnetic,
    dft_u,
    vdw,
):
    ignored = {"substrate", "film", "substrates", "films"}
    payload = {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "mode": "adaptive_interface",
        "project": str(project_name),
        "sources": {
            "substrate": str(substrate_path),
            "substrate_sha256": file_sha256(substrate_path),
            "film": str(film_path),
            "film_sha256": file_sha256(film_path),
        },
        "search": {
            key: value
            for key, value in search_parameters.items()
            if key not in ignored
        },
        "calculation": {
            "include_pdos": bool(include_pdos),
            "include_charge": bool(include_charge),
            "magnetic": bool(magnetic),
            "dft_u": dft_u or {},
            "vdw": str(vdw or "none"),
        },
    }
    return fingerprint_payload(payload), payload


def stage_fingerprint(workflow_fingerprint, stage_name):
    return fingerprint_payload(
        {"workflow": workflow_fingerprint, "stage": str(stage_name)}
    )


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def atomic_write_json(path, data):
    """Replace a JSON file atomically so interruption cannot leave half a manifest."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, target)


def existing_workflow_result(manifest_path, expected_fingerprint, database):
    manifest = read_json(manifest_path)
    if not manifest:
        return None
    actual = str(manifest.get("workflow_fingerprint") or "")
    if not actual:
        raise FileExistsError(
            f'The output directory contains an older workflow whose input fingerprint cannot be verified: {Path(manifest_path).parent}\nKeep the existing project and use a new project name.'
        )
    if actual and actual != expected_fingerprint:
        raise FileExistsError(
            f'The output directory contains a workflow with different inputs: {Path(manifest_path).parent}\nChoose a new project name to preserve existing calculations.'
        )
    task_ids = tuple(str(item) for item in manifest.get("tasks", []) if item)
    if task_ids and all(database.get_task(task_id) for task_id in task_ids):
        return manifest
    return None


def write_batch_manifest(project_root, project_name, mode, results, parameters=None):
    """Write one auditable summary for a generated batch."""
    root = Path(project_root)
    workflows = []
    task_ids = []
    warning_count = 0
    for result in results:
        manifest_path = result.root / (
            "adaptive_workflow.json"
            if mode == "adaptive_interface"
            else "workflow.json"
        )
        manifest = read_json(manifest_path)
        workflows.append(
            {
                "root": str(result.root),
                "manifest": str(manifest_path),
                "workflow_fingerprint": manifest.get("workflow_fingerprint", ""),
                "task_count": len(result.task_ids),
                "warnings": len(result.warnings),
            }
        )
        task_ids.extend(result.task_ids)
        warning_count += len(result.warnings)
    identity = {
        "project": str(project_name),
        "mode": str(mode),
        "workflow_fingerprints": sorted(
            item["workflow_fingerprint"] for item in workflows
        ),
        "parameters": parameters or {},
    }
    manifest = {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "batch_id": fingerprint_payload(identity)[:20],
        "created_at": utc_now(),
        "project": str(project_name),
        "mode": str(mode),
        "workflow_count": len(workflows),
        "task_count": len(task_ids),
        "warning_count": warning_count,
        "parameters": parameters or {},
        "workflows": workflows,
        "tasks": task_ids,
    }
    atomic_write_json(root / "batches" / f"{manifest['batch_id']}.json", manifest)
    atomic_write_json(root / "batch_manifest.json", manifest)
    return manifest
