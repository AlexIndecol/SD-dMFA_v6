from __future__ import annotations

from typing import Any, Tuple

from flodym import Dimension, DimensionSet


def _subset_dims(dims: DimensionSet, letters: Tuple[str, ...]) -> DimensionSet:
    """Return a DimensionSet subset in a way that works across flodym versions."""
    if hasattr(dims, "get_subset"):
        return dims.get_subset(letters)

    key: Any
    if len(letters) == 1:
        key = letters[0]
    else:
        key = letters
    sub = dims[key]
    if isinstance(sub, DimensionSet):
        return sub
    if isinstance(sub, Dimension):
        return DimensionSet(dim_list=[sub])
    return DimensionSet(dim_list=list(sub))


__all__ = ["_subset_dims"]
