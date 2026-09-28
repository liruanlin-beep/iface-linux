"""Run from a scratch directory after installing iface-linux."""

from pathlib import Path
from iface import api


def build_inputs(poscar, output, licensed_potcar_library):
    """Prepare only; the caller must explicitly approve any later submission."""
    result = api.prepare(poscar, output, preset="static", encut=520, mesh=(7, 7, 7),
                         potcar_root=licensed_potcar_library, scheduler="slurm")
    checks = api.preflight(output)
    if not checks["ok"]:
        raise ValueError(checks["errors"])
    api.convergence_sweep(output, Path(output).with_name("encut_scan"), "encut", [400, 450, 500, 550])
    return result
