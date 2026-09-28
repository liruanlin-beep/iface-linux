from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class ChargeGridReport:
    grid: tuple
    lattice_max_abs_diff: float
    volume_a3: float
    electron_difference: float
    accumulated_electrons: float
    depleted_electrons: float


@dataclass
class ChargeDifferenceResult:
    difference_path: Path
    raw_total: np.ndarray
    density_total: np.ndarray
    lattice: np.ndarray
    volume_a3: float
    grid: tuple
    z_a: np.ndarray
    planar_density: np.ndarray
    xz_density: np.ndarray
    report: ChargeGridReport


def calculate_charge_difference(
    interface_chgcar,
    substrate_chgcar,
    film_chgcar,
    output_path,
    lattice_tolerance=1e-5,
):
    """Calculate Δρ = ρ(interface) - ρ(substrate) - ρ(film)."""
    from pymatgen.io.vasp.outputs import Chgcar

    paths = [Path(interface_chgcar), Path(substrate_chgcar), Path(film_chgcar)]
    labels = ['Interface', 'Isolated substrate', 'Isolated film']
    for label, path in zip(labels, paths):
        if not path.is_file():
            raise FileNotFoundError(f'{label} CHGCAR does not exist: {path}')
    interface, substrate, film = [Chgcar.from_file(path) for path in paths]
    grid = tuple(int(value) for value in interface.dim)
    for label, item in (('Isolated substrate', substrate), ('Isolated film', film)):
        if tuple(item.dim) != grid:
            raise ValueError(
                f'CHGCAR FFT grid mismatch: interface grid {grid}，{label}is {tuple(item.dim)}. All three systems must use the same cell and NGXF/NGYF/NGZF.'
            )

    reference_lattice = np.asarray(interface.structure.lattice.matrix, dtype=float)
    lattice_max_diff = 0.0
    for label, item in (('Isolated substrate', substrate), ('Isolated film', film)):
        matrix = np.asarray(item.structure.lattice.matrix, dtype=float)
        difference = float(np.max(np.abs(reference_lattice - matrix)))
        lattice_max_diff = max(lattice_max_diff, difference)
        if not np.allclose(reference_lattice, matrix, rtol=lattice_tolerance, atol=lattice_tolerance):
            raise ValueError(
                f'CHGCAR cell mismatch: {label}maximum lattice difference from the interface is {difference:.6g} Å。'
            )

    raw_total = (
        np.asarray(interface.data["total"], dtype=float)
        - np.asarray(substrate.data["total"], dtype=float)
        - np.asarray(film.data["total"], dtype=float)
    )
    data = {"total": raw_total}
    if all("diff" in item.data for item in (interface, substrate, film)):
        data["diff"] = (
            np.asarray(interface.data["diff"], dtype=float)
            - np.asarray(substrate.data["diff"], dtype=float)
            - np.asarray(film.data["diff"], dtype=float)
        )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Chgcar(interface.structure, data).write_file(output_path)

    volume = float(interface.structure.volume)
    density = raw_total / volume
    ngrid = int(np.prod(grid))
    electron_difference = float(np.sum(raw_total) / ngrid)
    accumulated = float(np.sum(raw_total[raw_total > 0]) / ngrid)
    depleted = float(np.sum(raw_total[raw_total < 0]) / ngrid)
    planar = np.mean(density, axis=(0, 1))
    z_axis = np.arange(grid[2], dtype=float) / grid[2] * interface.structure.lattice.c
    xz_density = np.mean(density, axis=1).T
    report = ChargeGridReport(
        grid=grid,
        lattice_max_abs_diff=lattice_max_diff,
        volume_a3=volume,
        electron_difference=electron_difference,
        accumulated_electrons=accumulated,
        depleted_electrons=depleted,
    )
    return ChargeDifferenceResult(
        difference_path=output_path,
        raw_total=raw_total,
        density_total=density,
        lattice=reference_lattice,
        volume_a3=volume,
        grid=grid,
        z_a=z_axis,
        planar_density=planar,
        xz_density=xz_density,
        report=report,
    )
