from dataclasses import dataclass
from math import acos, degrees
from pathlib import Path

import numpy as np

from iface.core.slab_builder import cross_section_area
from iface.core.structure_model import from_pymatgen_structure, to_pymatgen_structure


HARD_MAX_ATOMS = 1000


@dataclass
class InterfaceCandidate:
    index: int
    structure: object
    lightweight: object
    termination: object
    gap: float
    area: float
    atoms: int
    strain: float | None
    score: float
    label: str
    mismatch_a: float | None = None
    mismatch_b: float | None = None
    angle_mismatch_deg: float | None = None
    offset: tuple = (0.0, 0.0)
    compatibility_percent: float = 0.0
    source_a: str = ""
    source_b: str = ""
    scan_pair_id: str = ""
    substrate_layers: int | None = None
    film_layers: int | None = None

    def table_row(self):
        strain = "N/A" if self.strain is None else f"{self.strain * 100:.2f}%"
        mismatch = max(
            value for value in (self.mismatch_a, self.mismatch_b) if value is not None
        ) if any(value is not None for value in (self.mismatch_a, self.mismatch_b)) else None
        mismatch_text = "N/A" if mismatch is None else f"{mismatch * 100:.2f}%"
        return (
            self.index + 1,
            self.label,
            f"{self.gap:.2f}",
            f"{self.area:.2f}",
            self.atoms,
            strain,
            mismatch_text,
            f"{self.compatibility_percent:.1f}",
        )


def _load_pmg(structure):
    if isinstance(structure, (str, Path)):
        from pymatgen.core import Structure as PmgStructure

        return PmgStructure.from_file(str(structure))
    if hasattr(structure, "lattice") and hasattr(structure, "sites"):
        return structure.copy()
    return to_pymatgen_structure(structure)


def calculate_2d_mismatch(film_vectors, substrate_vectors):
    """Return length and angle mismatch of two in-plane vector pairs."""
    film = np.asarray(film_vectors, dtype=float)[:2]
    substrate = np.asarray(substrate_vectors, dtype=float)[:2]
    if film.shape != (2, 3) or substrate.shape != (2, 3):
        raise ValueError("In-plane lattice vectors must have shape 2 by 3.")
    film_lengths = np.linalg.norm(film, axis=1)
    substrate_lengths = np.linalg.norm(substrate, axis=1)
    denominator = np.maximum(substrate_lengths, 1e-12)
    mismatches = np.abs(film_lengths - substrate_lengths) / denominator
    film_angle = _angle_degrees(film[0], film[1])
    substrate_angle = _angle_degrees(substrate[0], substrate[1])
    return float(mismatches[0]), float(mismatches[1]), abs(film_angle - substrate_angle)


def _angle_degrees(first, second):
    denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
    if denominator <= 1e-12:
        raise ValueError("Lattice vectors must have nonzero length.")
    cosine = float(np.dot(first, second) / denominator)
    return degrees(acos(max(-1.0, min(1.0, cosine))))


def _matching_metrics(iface):
    properties = getattr(iface, "interface_properties", {}) or {}
    strain = properties.get("von_mises_strain")
    try:
        strain = abs(float(strain))
    except (TypeError, ValueError):
        strain = None
    film_vectors = properties.get("film_sl_vectors")
    substrate_vectors = properties.get("substrate_sl_vectors")
    if film_vectors is None or substrate_vectors is None:
        return strain, None, None, None
    try:
        mismatch_a, mismatch_b, angle = calculate_2d_mismatch(
            film_vectors, substrate_vectors
        )
    except (TypeError, ValueError):
        return strain, None, None, None
    return strain, mismatch_a, mismatch_b, angle


def interface_score(
    strain,
    mismatch_a,
    mismatch_b,
    angle_mismatch_deg,
    atoms,
    area,
    max_strain,
    max_atoms,
    max_area,
):
    """Normalized pre-DFT geometry penalty; lower is better."""
    strain_ratio = abs(float(strain or 0.0)) / max(float(max_strain), 1e-12)
    mismatch_ratio = max(float(mismatch_a or 0.0), float(mismatch_b or 0.0)) / max(
        float(max_strain), 1e-12
    )
    angle_ratio = abs(float(angle_mismatch_deg or 0.0)) / 2.0
    atom_ratio = int(atoms) / max(int(max_atoms), 1)
    area_ratio = float(area) / max(float(max_area), 1e-12)
    penalty = 45 * strain_ratio + 20 * mismatch_ratio + 10 * angle_ratio
    penalty += 15 * atom_ratio + 10 * area_ratio
    return round(max(0.0, penalty), 6)


def search_interface_candidates(
    substrate,
    film,
    substrate_miller=(1, 0, 0),
    film_miller=(1, 0, 0),
    substrate_layers=6,
    film_layers=6,
    gap=2.5,
    gap_values=None,
    max_strain=0.05,
    max_area=500.0,
    max_atoms=HARD_MAX_ATOMS,
    lateral_offsets=((0.0, 0.0), (0.5, 0.0), (0.0, 0.5), (0.5, 0.5)),
    limit=24,
):
    from pymatgen.analysis.interfaces import CoherentInterfaceBuilder
    from pymatgen.analysis.interfaces.zsl import ZSLGenerator

    max_atoms = int(max_atoms)
    if max_atoms <= 0:
        raise ValueError("The maximum atom count must be positive.")
    if max_atoms > HARD_MAX_ATOMS:
        raise ValueError(f"The maximum atom count cannot exceed {HARD_MAX_ATOMS}.")
    max_strain = float(max_strain)
    if not 0 < max_strain <= 0.25:
        raise ValueError("The maximum strain must be greater than zero and at most 25%.")
    max_area = float(max_area)
    if max_area <= 0:
        raise ValueError("The maximum matching area must be positive.")

    gaps = [float(value) for value in (gap_values or [gap])]
    gaps = sorted({value for value in gaps if 0.5 <= value <= 10.0})
    if not gaps:
        raise ValueError("Interface gaps must be between 0.5 and 10 angstrom.")
    offsets = []
    for offset in lateral_offsets or ((0.0, 0.0),):
        if len(offset) != 2:
            continue
        offsets.append((float(offset[0]) % 1.0, float(offset[1]) % 1.0))
    offsets = tuple(dict.fromkeys(offsets)) or ((0.0, 0.0),)

    sub = _load_pmg(substrate)
    film_struct = _load_pmg(film)
    zsl = ZSLGenerator(
        max_area=max_area,
        max_length_tol=max_strain,
        max_angle_tol=min(0.08, max_strain),
        bidirectional=True,
    )
    builder = CoherentInterfaceBuilder(
        substrate_structure=sub,
        film_structure=film_struct,
        substrate_miller=tuple(substrate_miller),
        film_miller=tuple(film_miller),
        zslgen=zsl,
    )
    terminations = list(builder.terminations)
    if not terminations:
        raise RuntimeError("No usable interface termination pairs were found.")

    candidates = []
    seen = set()
    base_limit = max(1, int(np.ceil(int(limit) / max(1, len(gaps) * len(offsets)))))
    for term in terminations:
        for gap_value in gaps:
            try:
                interfaces = builder.get_interfaces(
                    termination=term,
                    gap=gap_value,
                    vacuum_over_film=15.0,
                    film_thickness=int(film_layers),
                    substrate_thickness=int(substrate_layers),
                    in_layers=True,
                )
            except Exception:
                continue
            accepted_for_group = 0
            for raw_iface in interfaces:
                area = cross_section_area(raw_iface.lattice)
                atoms = len(raw_iface)
                if area > max_area or atoms > max_atoms:
                    continue
                strain, mismatch_a, mismatch_b, angle_mismatch = _matching_metrics(raw_iface)
                if strain is not None and strain > max_strain:
                    continue
                if max(value or 0.0 for value in (mismatch_a, mismatch_b)) > max_strain:
                    continue
                for offset in offsets:
                    iface = raw_iface.copy()
                    iface.in_plane_offset = offset
                    key = (
                        str(term),
                        round(gap_value, 5),
                        round(offset[0], 5),
                        round(offset[1], 5),
                        atoms,
                        round(area, 5),
                        round(strain or 0.0, 8),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    penalty = interface_score(
                        strain,
                        mismatch_a,
                        mismatch_b,
                        angle_mismatch,
                        atoms,
                        area,
                        max_strain,
                        max_atoms,
                        max_area,
                    )
                    label = f"{term[0]} / {term[1]}" if len(term) == 2 else str(term)
                    name = f"interface_{len(candidates) + 1:03d}"
                    lightweight = from_pymatgen_structure(iface, name)
                    candidates.append(
                        InterfaceCandidate(
                            index=len(candidates),
                            structure=iface,
                            lightweight=lightweight,
                            termination=term,
                            gap=gap_value,
                            area=area,
                            atoms=atoms,
                            strain=strain,
                            score=penalty,
                            label=label,
                            mismatch_a=mismatch_a,
                            mismatch_b=mismatch_b,
                            angle_mismatch_deg=angle_mismatch,
                            offset=offset,
                            compatibility_percent=round(max(0.0, 100.0 - penalty), 2),
                        )
                    )
                    if len(candidates) >= int(limit):
                        break
                accepted_for_group += 1
                if len(candidates) >= int(limit) or accepted_for_group >= base_limit:
                    break
            if len(candidates) >= int(limit):
                break
        if len(candidates) >= int(limit):
            break

    candidates.sort(key=lambda item: (item.score, item.atoms, item.area))
    for index, item in enumerate(candidates):
        item.index = index
        item.lightweight.name = f"interface_{index + 1:03d}"
    return candidates
