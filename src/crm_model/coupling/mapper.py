"""Small mapping helpers to keep SD-dMFA transformations explicit."""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def mfa_feedback_from_timeseries(service_demand: pd.Series, unmet_service: pd.Series, primary: pd.Series, secondary: pd.Series) -> Dict[str, np.ndarray]:
    """Build canonical MFA->SD feedback arrays from aggregated MFA series."""
    service_stress = (unmet_service / service_demand.replace(0, np.nan)).fillna(0.0).to_numpy(dtype=float)
    circular_stress = (1.0 - (secondary / (primary + secondary).replace(0, np.nan)).fillna(0.0)).clip(0.0, 1.0)
    return {
        "service_stress_t": service_stress,
        "circular_supply_stress_t": circular_stress.to_numpy(dtype=float),
    }


__all__ = ["mfa_feedback_from_timeseries"]
