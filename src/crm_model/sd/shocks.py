from __future__ import annotations

from typing import Sequence

import numpy as np


def shock_multiplier_series(years: Sequence[int], *, start_year: int, duration_years: int, multiplier: float) -> np.ndarray:
    """Build a piecewise-constant shock multiplier series over years."""
    if duration_years < 0:
        raise ValueError(f"duration_years must be >= 0; got {duration_years}")
    mult = np.ones(len(years), dtype=float)
    end_year = int(start_year) + int(duration_years)
    for i, y in enumerate(years):
        if int(start_year) <= int(y) < end_year:
            mult[i] = float(multiplier)
    return mult


__all__ = ["shock_multiplier_series"]
