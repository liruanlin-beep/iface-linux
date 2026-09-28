"""Periodic geometry used by structural result comparisons."""

import itertools
import math

import numpy as np


def minimum_image(delta, cell):
    """Exact closest periodic displacement, including skewed cells.

    A singular-value bound limits the integer lattice search. Extremely skewed
    cells are rejected instead of returning an approximate distance silently.
    """
    centered = np.asarray(delta, dtype=float) - np.rint(delta)
    smallest = np.linalg.svd(cell, compute_uv=False)[-1]
    if smallest <= 1e-12:
        raise ValueError("Cannot compute periodic distances in a singular cell.")
    answer = []
    for row in centered:
        upper = np.linalg.norm(row @ cell) / smallest
        ranges = [range(math.ceil(v - upper), math.floor(v + upper) + 1) for v in row]
        if math.prod(len(r) for r in ranges) > 100000:
            raise ValueError("Cell is too skewed for a reliable periodic search. Use a reduced lattice.")
        shifts = np.array(list(itertools.product(*ranges)), dtype=float)
        candidates = row - shifts
        best = np.argmin(np.linalg.norm(candidates @ cell, axis=1))
        answer.append(candidates[best])
    return np.array(answer)
