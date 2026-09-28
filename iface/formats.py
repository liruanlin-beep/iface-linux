"""Validated VASP structure and input formats shared by the CLI and API."""

from dataclasses import dataclass
from pathlib import Path
import re

import numpy as np


FLOAT = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?"
# Current IUPAC symbols, kept local so basic input validation needs only NumPy.
ELEMENT_SYMBOLS = frozenset("""
H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni
Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe
Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au
Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf
Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og
""".split())


def number(value):
    result = float(str(value).replace("D", "E").replace("d", "e"))
    if not np.isfinite(result):
        raise ValueError("Numeric values must be finite.")
    return result


@dataclass
class Poscar:
    title: str
    cell: np.ndarray
    species: list
    counts: list
    fractional: np.ndarray
    flags: list | None = None

    @property
    def atom_count(self):
        return sum(self.counts)

    @classmethod
    def read(cls, path):
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
        try:
            raw = np.array([[number(v) for v in line.split()[:3]] for line in lines[2:5]])
            scales = [number(v) for v in lines[1].split()]
            if raw.shape != (3, 3) or abs(np.linalg.det(raw)) < 1e-12:
                raise ValueError("The lattice must be a nonsingular 3 by 3 matrix.")
            if len(scales) == 1 and scales[0] != 0:
                scale = scales[0]
                if scale < 0:
                    scale = (-scale / abs(np.linalg.det(raw))) ** (1 / 3)
                cart_scale = np.full(3, scale)
            elif len(scales) == 3 and min(scales) > 0:
                cart_scale = np.array(scales)
            else:
                raise ValueError("Use one nonzero scale or three positive Cartesian scales.")
            cell = raw * cart_scale
            species = lines[5].split()
            if not species or any(s not in ELEMENT_SYMBOLS for s in species):
                raise ValueError("A VASP 5 POSCAR with valid chemical element symbols is required.")
            counts = [int(v) for v in lines[6].split()]
            if len(species) != len(counts) or min(counts) <= 0:
                raise ValueError("Element symbols and positive atom counts must match.")
            n = sum(counts)
            if n > 1000:
                raise ValueError("The structure exceeds the 1000-atom limit.")
            index = 7
            selective = lines[index].strip().lower().startswith("s")
            index += int(selective)
            mode = lines[index].strip().lower()
            if not mode or mode[0] not in "dck":
                raise ValueError("Coordinates must be Direct or Cartesian.")
            rows = [line.split() for line in lines[index + 1:index + 1 + n]]
            coordinates = np.array([[number(v) for v in row[:3]] for row in rows])
            if coordinates.shape != (n, 3):
                raise ValueError("The coordinate count does not match the atom count.")
            if mode[0] != "d":
                coordinates = (coordinates * cart_scale) @ np.linalg.inv(cell)
            flags = None
            if selective:
                flags = [[v.upper() for v in row[3:6]] for row in rows]
                if any(len(row) != 3 or any(v not in ("T", "F") for v in row) for row in flags):
                    raise ValueError("Selective-dynamics flags must contain three T/F values per atom.")
            return cls(lines[0], cell, species, counts, coordinates, flags)
        except (IndexError, TypeError, np.linalg.LinAlgError) as exc:
            raise ValueError(f"Invalid or incomplete POSCAR: {path}") from exc

    def text(self):
        lines = [self.title, "1.0"]
        lines.extend(" ".join(f"{v:.14f}" for v in row) for row in self.cell)
        lines.extend([" ".join(self.species), " ".join(map(str, self.counts))])
        if self.flags is not None:
            lines.append("Selective dynamics")
        lines.append("Direct")
        for i, row in enumerate(self.fractional):
            text = " ".join(f"{v:.14f}" for v in row)
            if self.flags is not None:
                text += " " + " ".join(self.flags[i])
            lines.append(text)
        return "\n".join(lines) + "\n"


def read_incar(path):
    params = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = re.split(r"[!#]", line, maxsplit=1)[0]
        for statement in line.split(";"):
            if "=" in statement:
                key, value = statement.split("=", 1)
                key = key.strip().upper()
                if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or not value.strip():
                    raise ValueError("Invalid INCAR assignment.")
                params[key] = value.strip()
    return params


def incar_text(params):
    return "\n".join(f"{key} = {value}" for key, value in params.items()) + "\n"


def kpoints_text(mesh=(7, 7, 1), mode="Gamma"):
    if len(mesh) != 3 or any(int(v) != v or v <= 0 for v in mesh):
        raise ValueError("The k-point mesh must contain three positive integers.")
    if mode not in ("Gamma", "Monkhorst-Pack"):
        raise ValueError("Use Gamma or Monkhorst-Pack centering.")
    return f"Automatic mesh\n0\n{mode}\n{' '.join(map(str, mesh))}\n0 0 0\n"
