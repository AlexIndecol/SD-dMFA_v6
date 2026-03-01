"""Minimal plotting helper for dataframe time series."""

from __future__ import annotations

from typing import Optional

import matplotlib.pyplot as plt
import pandas as pd


def line_plot(df: pd.DataFrame, x: str, y: str, *, title: Optional[str] = None):
    """Return a matplotlib figure for a simple line plot."""
    fig, ax = plt.subplots()
    ax.plot(df[x], df[y])
    ax.set_xlabel(x)
    ax.set_ylabel(y)
    if title:
        ax.set_title(title)
    fig.tight_layout()
    return fig


__all__ = ["line_plot"]
