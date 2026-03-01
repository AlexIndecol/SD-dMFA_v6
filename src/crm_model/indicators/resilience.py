from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class IndicatorResult:
    name: str
    series: pd.Series
    meta: Dict[str, str]


@dataclass
class ResilienceResult:
    name: str
    value: float
    meta: Dict[str, str]


def unmet_service(demand: pd.Series, delivered: pd.Series) -> IndicatorResult:
    s = (demand - delivered).clip(lower=0.0)
    return IndicatorResult(
        name="Unmet_service",
        series=s,
        meta={"category": "Resilience / service indicators", "definition": "Demand - delivered service (>=0)"},
    )


def service_level(demand: pd.Series, delivered: pd.Series) -> IndicatorResult:
    s = (delivered / demand.replace(0, np.nan)).fillna(1.0).clip(lower=0.0, upper=1.0)
    return IndicatorResult(
        name="Service_level",
        series=s,
        meta={"category": "Resilience / service indicators", "definition": "Delivered / demand (clipped to [0,1])"},
    )


def service_deficit(service_level_series: pd.Series, baseline: float = 1.0) -> IndicatorResult:
    """Service deficit relative to a baseline (default 1.0).

    Often used in resilience-curve / "resilience triangle" style metrics as the performance shortfall.
    """
    s = (baseline - service_level_series).clip(lower=0.0)
    return IndicatorResult(
        name="Service_deficit",
        series=s,
        meta={
            "category": "Resilience / service indicators",
            "definition": "max(baseline - service_level, 0)",
            "baseline": str(baseline),
        },
    )


def time_to_recover(
    metric: pd.Series,
    baseline: float,
    start_index: int = 0,
    tolerance: float = 0.01,
) -> ResilienceResult:
    """Time to recover to within tolerance of baseline after a shock.

    Parameters
    ----------
    metric:
        time series (e.g. service level) sampled annually.
    baseline:
        target baseline value.
    start_index:
        first index (0-based) to start checking recovery from (e.g. shock end year).
    """
    target_low = baseline * (1 - tolerance)
    target_high = baseline * (1 + tolerance)
    for i, v in enumerate(metric.values[start_index:], start=start_index):
        if target_low <= v <= target_high:
            return ResilienceResult(
                name="TimeToRecover",
                value=float(i - start_index),
                meta={"baseline": str(baseline), "tolerance": str(tolerance), "start_index": str(start_index)},
            )
    return ResilienceResult(
        name="TimeToRecover",
        value=float("nan"),
        meta={"note": "Not recovered in horizon", "baseline": str(baseline), "tolerance": str(tolerance)},
    )


def peak_unmet(unmet: pd.Series) -> ResilienceResult:
    return ResilienceResult(
        name="PeakUnmet",
        value=float(unmet.max()),
        meta={"definition": "Maximum unmet service"},
    )


def cumulative_unmet(unmet: pd.Series) -> ResilienceResult:
    return ResilienceResult(
        name="CumulativeUnmet",
        value=float(unmet.sum()),
        meta={"definition": "Sum of unmet service over the horizon"},
    )


def resilience_triangle_area(service_level_series: pd.Series, baseline: float = 1.0) -> ResilienceResult:
    """Area of service-level shortfall over time (discrete sum).

    Units: "year-equivalents" of lost functionality when baseline=1.
    """
    deficit = (baseline - service_level_series).clip(lower=0.0)
    return ResilienceResult(
        name="ResilienceTriangleArea",
        value=float(deficit.sum()),
        meta={"baseline": str(baseline), "definition": "Sum of (baseline - service_level)+"},
    )


def years_below_service_threshold(service_level_series: pd.Series, threshold: float = 0.95) -> ResilienceResult:
    """Count of years where service level falls below a threshold."""
    n = int((service_level_series < float(threshold)).sum())
    return ResilienceResult(
        name="YearsBelowServiceThreshold",
        value=float(n),
        meta={"threshold": str(threshold), "definition": "Count(years where service_level < threshold)"},
    )


def max_consecutive_years_below_threshold(service_level_series: pd.Series, threshold: float = 0.95) -> ResilienceResult:
    """Maximum consecutive years with service level below a threshold."""
    below = (service_level_series < float(threshold)).to_numpy(dtype=bool)
    max_run = 0
    run = 0
    for b in below:
        if b:
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0
    return ResilienceResult(
        name="MaxConsecutiveYearsBelowThreshold",
        value=float(max_run),
        meta={"threshold": str(threshold), "definition": "Max run length where service_level < threshold"},
    )
