"""Resilience metric compatibility exports."""

from crm_model.indicators.resilience import (
    IndicatorResult,
    ResilienceResult,
    cumulative_unmet,
    max_consecutive_years_below_threshold,
    peak_unmet,
    resilience_triangle_area,
    service_deficit,
    service_level,
    time_to_recover,
    unmet_service,
    years_below_service_threshold,
)

__all__ = [
    "IndicatorResult",
    "ResilienceResult",
    "unmet_service",
    "service_level",
    "service_deficit",
    "time_to_recover",
    "peak_unmet",
    "cumulative_unmet",
    "resilience_triangle_area",
    "years_below_service_threshold",
    "max_consecutive_years_below_threshold",
]
