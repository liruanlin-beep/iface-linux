from dataclasses import dataclass

from app.core.slab_builder import cross_section_area, generate_slab, list_slab_terminations


@dataclass
class SurfaceCandidate:
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

    def table_row(self):
        return (
            self.index + 1,
            self.label,
            f"{self.gap:.2f}",
            f"{self.area:.2f}",
            self.atoms,
            "—",
            "—",
            f"{self.compatibility_percent:.1f}",
        )


def search_surface_candidates(
    structure,
    miller=(1, 0, 0),
    layers=6,
    vacuum=15.0,
    max_atoms=1000,
    limit=12,
):
    max_atoms = int(max_atoms)
    if max_atoms <= 0 or max_atoms > 1000:
        raise ValueError('The maximum atom count must be between 1 and 1000.')
    terminations = list_slab_terminations(structure, tuple(miller))
    candidates = []
    for termination in terminations[: max(1, int(limit))]:
        result = generate_slab(
            structure,
            tuple(miller),
            n_layers=int(layers),
            vacuum=float(vacuum),
            termination_index=termination.index,
        )
        atoms = len(result.lightweight.atoms)
        if atoms > max_atoms:
            continue
        area = cross_section_area(result.structure.lattice)
        penalty = 20.0 * atoms / max_atoms
        candidates.append(
            SurfaceCandidate(
                index=len(candidates),
                structure=result.structure,
                lightweight=result.lightweight,
                termination=termination,
                gap=float(vacuum),
                area=area,
                atoms=atoms,
                strain=None,
                score=penalty,
                label=termination.label,
                compatibility_percent=round(max(0.0, 100.0 - penalty), 2),
            )
        )
    candidates.sort(key=lambda item: (item.score, item.atoms, item.area))
    for index, item in enumerate(candidates):
        item.index = index
    return candidates
