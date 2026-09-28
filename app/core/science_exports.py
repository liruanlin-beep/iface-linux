import itertools
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.core.xlsx_writer import write_xlsx


PALETTE = (
    "#2563EB",
    "#D97706",
    "#168653",
    "#7C3AED",
    "#DC3545",
    "#0891B2",
    "#6B7280",
    "#BE185D",
)


@dataclass
class PdosDataset:
    energies_ev: np.ndarray
    fermi_ev: float
    channels: dict
    source: str


def load_pdos_from_vasprun(vasprun_path):
    from pymatgen.electronic_structure.core import Spin
    from pymatgen.io.vasp.outputs import Vasprun

    path = Path(vasprun_path)
    if not path.is_file():
        raise FileNotFoundError(f'vasprun.xml does not exist: {path}')
    run = Vasprun(
        path,
        parse_dos=True,
        parse_eigen=False,
        parse_projected_eigen=False,
        parse_potcar_file=False,
        exception_on_bad_xml=True,
    )
    complete = run.complete_dos
    energies = np.asarray(complete.energies, dtype=float) - float(complete.efermi)
    channels = {}

    def add_dos(label, dos):
        channels[label] = {
            "up": np.asarray(dos.densities.get(Spin.up, np.zeros_like(energies)), dtype=float),
            "down": np.asarray(
                dos.densities.get(Spin.down, np.zeros_like(energies)), dtype=float
            ),
        }

    add_dos("Total DOS", complete)
    for element, dos in complete.get_element_dos().items():
        add_dos(str(element), dos)
    for orbital, dos in complete.get_spd_dos().items():
        add_dos(f"Orbital {str(orbital)}", dos)
    return PdosDataset(energies, float(complete.efermi), channels, str(path))


def export_pdos_publication(dataset, output_dir, stem="PDOS"):
    plt, mpl = _publication_matplotlib()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(3.35, 2.65), constrained_layout=True)
    energies = dataset.energies_ev
    for index, (label, densities) in enumerate(dataset.channels.items()):
        color = "#202936" if index == 0 else PALETTE[(index - 1) % len(PALETTE)]
        width = 1.15 if index == 0 else 0.85
        axis.plot(energies, densities["up"], color=color, lw=width, label=label)
        if np.any(np.abs(densities["down"]) > 0):
            axis.plot(energies, -densities["down"], color=color, lw=width, alpha=0.9)
    axis.axvline(0, color="#4b5563", lw=0.7, ls="--")
    axis.axhline(0, color="#6b7280", lw=0.55)
    axis.set_xlabel(r"$E-E_\mathrm{F}$ (eV)")
    axis.set_ylabel("Density of states (states eV$^{-1}$)")
    axis.set_xlim(-8, 5)
    axis.legend(loc="upper right", fontsize=5.5, ncol=1)
    paths = _save_publication_figure(figure, output_dir / stem)
    plt.close(figure)

    headers = ["Energy_E_minus_Ef_eV"]
    for label in dataset.channels:
        headers.extend([f"{label}_up", f"{label}_down"])

    def data_rows():
        yield headers
        for row_index, energy in enumerate(energies):
            row = [float(energy)]
            for densities in dataset.channels.values():
                row.extend(
                    [float(densities["up"][row_index]), float(densities["down"][row_index])]
                )
            yield row

    metadata = [
        ["Field", "Value"],
        ["Source", dataset.source],
        ["Fermi_energy_eV", dataset.fermi_ev],
        ["Energy_reference", "All energies are reported as E - E_F"],
        ["Spin_convention", "Spin-down values are stored positive in Excel and plotted negative"],
    ]
    excel_path = write_xlsx(
        output_dir / f"{stem}_source_data.xlsx",
        [("Metadata", metadata), ("PDOS", data_rows())],
    )
    return {**paths, "excel": excel_path}


def export_charge_difference_publication(
    result,
    output_dir,
    stem="ChargeDifference",
    include_full_grid_excel=True,
):
    plt, mpl = _publication_matplotlib()
    from matplotlib.colors import TwoSlopeNorm

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    figure, (heat_axis, planar_axis) = plt.subplots(
        1,
        2,
        figsize=(7.2, 3.0),
        gridspec_kw={"width_ratios": [1.65, 1.0]},
        constrained_layout=True,
    )
    finite = np.abs(result.xz_density[np.isfinite(result.xz_density)])
    limit = float(np.percentile(finite, 99.5)) if finite.size else 1.0
    limit = max(limit, 1e-12)
    a_length = float(np.linalg.norm(result.lattice[0]))
    c_length = float(np.linalg.norm(result.lattice[2]))
    image = heat_axis.imshow(
        result.xz_density,
        origin="lower",
        aspect="auto",
        extent=(0, a_length, 0, c_length),
        cmap="RdBu_r",
        norm=TwoSlopeNorm(vmin=-limit, vcenter=0.0, vmax=limit),
        interpolation="nearest",
        rasterized=True,
    )
    heat_axis.set_xlabel(r"$x$ ($\AA$)")
    heat_axis.set_ylabel(r"$z$ ($\AA$)")
    colorbar = figure.colorbar(image, ax=heat_axis, pad=0.02)
    colorbar.set_label(r"$\Delta\rho$ (e $\AA^{-3}$)")
    planar_axis.plot(result.planar_density, result.z_a, color="#202936", lw=1.1)
    planar_axis.fill_betweenx(
        result.z_a,
        0,
        result.planar_density,
        where=result.planar_density >= 0,
        color="#B2182B",
        alpha=0.38,
        label="Accumulation",
    )
    planar_axis.fill_betweenx(
        result.z_a,
        0,
        result.planar_density,
        where=result.planar_density < 0,
        color="#2166AC",
        alpha=0.38,
        label="Depletion",
    )
    planar_axis.axvline(0, color="#6b7280", lw=0.6)
    planar_axis.set_xlabel(r"Planar $\Delta\rho$ (e $\AA^{-3}$)")
    planar_axis.set_ylabel(r"$z$ ($\AA$)")
    planar_axis.legend(loc="best", fontsize=6)
    paths = _save_publication_figure(figure, output_dir / stem)
    plt.close(figure)

    npz_path = output_dir / f"{stem}_full_grid.npz"
    np.savez_compressed(
        npz_path,
        density_e_a3=result.density_total,
        raw_chgcar_difference=result.raw_total,
        lattice_a=result.lattice,
    )
    sheets = [
        (
            "Metadata",
            [
                ["Field", "Value"],
                ["Difference_definition", "interface - isolated substrate - isolated film"],
                ["Grid", " x ".join(str(value) for value in result.grid)],
                ["Cell_volume_A3", result.volume_a3],
                ["Electron_difference_e", result.report.electron_difference],
                ["Accumulated_electrons_e", result.report.accumulated_electrons],
                ["Depleted_electrons_e", result.report.depleted_electrons],
                ["Full_grid_archive", npz_path.name],
            ],
        ),
        (
            "Planar_Z",
            itertools.chain(
                [["z_A", "planar_delta_rho_e_A3"]],
                (
                    [float(z), float(value)]
                    for z, value in zip(result.z_a, result.planar_density)
                ),
            ),
        ),
        (
            "XZ_Average",
            _xz_rows(result),
        ),
    ]
    if include_full_grid_excel:
        total_rows = int(np.prod(result.grid))
        rows_per_sheet = 900_000
        iterator = _full_grid_rows(result)
        for index in range(math.ceil(total_rows / rows_per_sheet)):
            sheets.append(
                (
                    f"FullGrid_{index + 1:03d}",
                    itertools.chain(
                        [["ix", "iy", "iz", "x_A", "y_A", "z_A", "delta_rho_e_A3"]],
                        itertools.islice(iterator, rows_per_sheet),
                    ),
                )
            )
    excel_path = write_xlsx(output_dir / f"{stem}_source_data.xlsx", sheets)
    return {**paths, "excel": excel_path, "npz": npz_path, "chgdiff": result.difference_path}


def _xz_rows(result):
    yield ["ix", "iz", "x_A", "z_A", "mean_delta_rho_e_A3"]
    nx, _ny, nz = result.grid
    a_length = float(np.linalg.norm(result.lattice[0]))
    c_length = float(np.linalg.norm(result.lattice[2]))
    for iz in range(nz):
        for ix in range(nx):
            yield [
                ix,
                iz,
                ix / nx * a_length,
                iz / nz * c_length,
                float(result.xz_density[iz, ix]),
            ]


def _full_grid_rows(result):
    nx, ny, nz = result.grid
    lattice = np.asarray(result.lattice, dtype=float)
    for iz in range(nz):
        fz = iz / nz
        for iy in range(ny):
            fy = iy / ny
            for ix in range(nx):
                fx = ix / nx
                cart = np.asarray([fx, fy, fz]) @ lattice
                yield [
                    ix,
                    iy,
                    iz,
                    float(cart[0]),
                    float(cart[1]),
                    float(cart[2]),
                    float(result.density_total[ix, iy, iz]),
                ]


def _publication_matplotlib():
    import matplotlib as mpl

    mpl.use("Agg")
    import matplotlib.pyplot as plt

    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "font.size": 7,
            "axes.labelsize": 7,
            "xtick.labelsize": 6.5,
            "ytick.labelsize": 6.5,
            "axes.spines.right": False,
            "axes.spines.top": False,
            "axes.linewidth": 0.8,
            "legend.frameon": False,
            "savefig.facecolor": "white",
            "figure.facecolor": "white",
        }
    )
    return plt, mpl


def _save_publication_figure(figure, base_path):
    base_path = Path(base_path)
    png = base_path.with_suffix(".png")
    tiff = base_path.with_suffix(".tiff")
    pdf = base_path.with_suffix(".pdf")
    svg = base_path.with_suffix(".svg")
    figure.savefig(png, dpi=600, bbox_inches="tight")
    figure.savefig(tiff, dpi=600, bbox_inches="tight", pil_kwargs={"compression": "tiff_lzw"})
    figure.savefig(pdf, bbox_inches="tight")
    figure.savefig(svg, bbox_inches="tight")
    return {"png": png, "tiff": tiff, "pdf": pdf, "svg": svg}
