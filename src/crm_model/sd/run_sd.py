from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from BPTK_Py.bptk import bptk

from .bptk_model import DemandModel, SDTimeseries
from .params import expand_temporal_value, normalize_and_validate_sd_parameters


def run_bptk_sd(years: List[int], params: Dict[str, Any]) -> SDTimeseries:
    report_start_year = params.get("report_start_year")
    report_start_year_i = int(report_start_year) if report_start_year is not None else None
    params = normalize_and_validate_sd_parameters(
        params,
        years=years,
        report_start_year=report_start_year_i,
        emit_warnings=True,
        context="run_bptk_sd",
    )
    horizon = len(years) - 1

    if horizon < 0:
        raise ValueError("years must be non-empty.")

    def _as_series(value: Any, *, name: str, default: float) -> np.ndarray:
        if isinstance(value, pd.Series):
            value = value.to_numpy(dtype=float)
        return expand_temporal_value(
            value,
            years=years,
            name=name,
            default=default,
            report_start_year=report_start_year_i,
            emit_warnings=True,
            context="run_bptk_sd",
        ).astype(float)

    exo = params.get("demand_exogenous")
    if exo is None:
        raise ValueError("SD params must include demand_exogenous (length = number of years)")

    exo_vals = _as_series(exo, name="demand_exogenous", default=0.0)
    scarcity_vals = _as_series(params.get("scarcity_multiplier", 1.0), name="scarcity_multiplier", default=1.0)
    service_stress_vals = _as_series(
        params.get("service_stress_signal", 0.0),
        name="service_stress_signal",
        default=0.0,
    )
    strategic_coverage_vals = _as_series(
        params.get("strategic_stock_coverage_years", 0.0),
        name="strategic_stock_coverage_years",
        default=0.0,
    )
    collection_multiplier_min_vals = _as_series(
        params.get("collection_multiplier_min", 0.0),
        name="collection_multiplier_min",
        default=0.0,
    )
    collection_multiplier_max_vals = _as_series(
        params.get("collection_multiplier_max", 1.0e6),
        name="collection_multiplier_max",
        default=1.0e6,
    )
    collection_multiplier_lag_years_vals = _as_series(
        params.get("collection_multiplier_lag_years", 0.0),
        name="collection_multiplier_lag_years",
        default=0.0,
    )
    strategic_reserve_enabled_vals = np.clip(
        _as_series(
            params.get("strategic_reserve_enabled", 0.0),
            name="strategic_reserve_enabled",
            default=0.0,
        ),
        0.0,
        1.0,
    )
    strategic_reserve_target_coverage_years_vals = _as_series(
        params.get("strategic_reserve_target_coverage_years", 0.5),
        name="strategic_reserve_target_coverage_years",
        default=0.5,
    )
    strategic_reserve_fill_gain_vals = _as_series(
        params.get("strategic_reserve_fill_gain", 0.5),
        name="strategic_reserve_fill_gain",
        default=0.5,
    )
    strategic_reserve_release_gain_vals = _as_series(
        params.get("strategic_reserve_release_gain", 1.0),
        name="strategic_reserve_release_gain",
        default=1.0,
    )
    strategic_reserve_max_fill_rate_vals = np.clip(
        _as_series(
            params.get("strategic_reserve_max_fill_rate", 0.15),
            name="strategic_reserve_max_fill_rate",
            default=0.15,
        ),
        0.0,
        1.0,
    )
    strategic_reserve_max_release_rate_vals = np.clip(
        _as_series(
            params.get("strategic_reserve_max_release_rate", 0.25),
            name="strategic_reserve_max_release_rate",
            default=0.25,
        ),
        0.0,
        1.0,
    )
    strategic_reserve_fill_price_threshold_vals = np.maximum(
        _as_series(
            params.get("strategic_reserve_fill_price_threshold", 1.0),
            name="strategic_reserve_fill_price_threshold",
            default=1.0,
        ),
        1.0e-12,
    )
    strategic_reserve_release_price_threshold_vals = np.maximum(
        _as_series(
            params.get("strategic_reserve_release_price_threshold", 1.1),
            name="strategic_reserve_release_price_threshold",
            default=1.1,
        ),
        1.0e-12,
    )
    strategic_reserve_fill_service_threshold_vals = np.clip(
        _as_series(
            params.get("strategic_reserve_fill_service_threshold", 0.05),
            name="strategic_reserve_fill_service_threshold",
            default=0.05,
        ),
        0.0,
        1.0,
    )
    strategic_reserve_release_service_threshold_vals = np.clip(
        _as_series(
            params.get("strategic_reserve_release_service_threshold", 0.15),
            name="strategic_reserve_release_service_threshold",
            default=0.15,
        ),
        0.0,
        1.0,
    )
    price_base_vals = np.maximum(
        _as_series(params.get("price_base", 1.0), name="price_base", default=1.0),
        1.0e-12,
    )
    price_scarcity_sensitivity_vals = _as_series(
        params.get("price_scarcity_sensitivity", 0.5),
        name="price_scarcity_sensitivity",
        default=0.5,
    )
    demand_price_elasticity_vals = _as_series(
        params.get("demand_price_elasticity", 0.1),
        name="demand_price_elasticity",
        default=0.1,
    )
    capacity_envelope_initial_vals = np.maximum(
        _as_series(
            params.get("capacity_envelope_initial", 1.0),
            name="capacity_envelope_initial",
            default=1.0,
        ),
        1.0e-12,
    )
    capacity_envelope_min_vals = np.maximum(
        _as_series(
            params.get("capacity_envelope_min", 0.8),
            name="capacity_envelope_min",
            default=0.8,
        ),
        1.0e-12,
    )
    capacity_envelope_max_vals = np.maximum(
        _as_series(
            params.get("capacity_envelope_max", 1.4),
            name="capacity_envelope_max",
            default=1.4,
        ),
        1.0e-12,
    )
    capacity_expansion_gain_vals = _as_series(
        params.get("capacity_expansion_gain", 0.2),
        name="capacity_expansion_gain",
        default=0.2,
    )
    capacity_retirement_gain_vals = _as_series(
        params.get("capacity_retirement_gain", 0.05),
        name="capacity_retirement_gain",
        default=0.05,
    )
    capacity_adjustment_lag_years_vals = _as_series(
        params.get("capacity_adjustment_lag_years", 5.0),
        name="capacity_adjustment_lag_years",
        default=5.0,
    )
    capacity_pressure_shortage_weight_vals = np.clip(
        _as_series(
            params.get("capacity_pressure_shortage_weight", 0.7),
            name="capacity_pressure_shortage_weight",
            default=0.7,
        ),
        0.0,
        1.0,
    )
    bottleneck_scarcity_gain_vals = _as_series(
        params.get("bottleneck_scarcity_gain", 0.0),
        name="bottleneck_scarcity_gain",
        default=0.0,
    )
    bottleneck_collection_sensitivity_vals = _as_series(
        params.get("bottleneck_collection_sensitivity", 0.0),
        name="bottleneck_collection_sensitivity",
        default=0.0,
    )
    collection_price_response_gain_vals = _as_series(
        params.get("collection_price_response_gain", 0.0),
        name="collection_price_response_gain",
        default=0.0,
    )
    scarcity_vals = np.maximum(scarcity_vals, 0.0)
    service_stress_vals = np.clip(service_stress_vals, 0.0, 1.0)
    strategic_coverage_vals = np.maximum(strategic_coverage_vals, 0.0)

    def _points(arr: np.ndarray) -> list[list[float]]:
        return [[float(t), float(arr[t])] for t in range(horizon + 1)]

    demand_points = _points(exo_vals)
    scarcity_points = _points(scarcity_vals)
    service_stress_points = _points(service_stress_vals)
    strategic_coverage_points = _points(strategic_coverage_vals)
    collection_multiplier_min_points = _points(collection_multiplier_min_vals)
    collection_multiplier_max_points = _points(collection_multiplier_max_vals)
    collection_multiplier_lag_years_points = _points(collection_multiplier_lag_years_vals)
    strategic_reserve_enabled_points = _points(strategic_reserve_enabled_vals)
    strategic_reserve_target_coverage_years_points = _points(strategic_reserve_target_coverage_years_vals)
    strategic_reserve_fill_gain_points = _points(strategic_reserve_fill_gain_vals)
    strategic_reserve_release_gain_points = _points(strategic_reserve_release_gain_vals)
    strategic_reserve_max_fill_rate_points = _points(strategic_reserve_max_fill_rate_vals)
    strategic_reserve_max_release_rate_points = _points(strategic_reserve_max_release_rate_vals)
    strategic_reserve_fill_price_threshold_points = _points(strategic_reserve_fill_price_threshold_vals)
    strategic_reserve_release_price_threshold_points = _points(strategic_reserve_release_price_threshold_vals)
    strategic_reserve_fill_service_threshold_points = _points(strategic_reserve_fill_service_threshold_vals)
    strategic_reserve_release_service_threshold_points = _points(strategic_reserve_release_service_threshold_vals)
    price_base_points = _points(price_base_vals)
    price_scarcity_sensitivity_points = _points(price_scarcity_sensitivity_vals)
    demand_price_elasticity_points = _points(demand_price_elasticity_vals)
    capacity_envelope_min_points = _points(capacity_envelope_min_vals)
    capacity_envelope_max_points = _points(capacity_envelope_max_vals)
    capacity_expansion_gain_points = _points(capacity_expansion_gain_vals)
    capacity_retirement_gain_points = _points(capacity_retirement_gain_vals)
    capacity_adjustment_lag_years_points = _points(capacity_adjustment_lag_years_vals)
    capacity_pressure_shortage_weight_points = _points(capacity_pressure_shortage_weight_vals)
    bottleneck_scarcity_gain_points = _points(bottleneck_scarcity_gain_vals)
    bottleneck_collection_sensitivity_points = _points(bottleneck_collection_sensitivity_vals)
    collection_price_response_gain_points = _points(collection_price_response_gain_vals)

    model = DemandModel()
    model.starttime = 0.0
    model.stoptime = float(horizon)
    model.dt = 1.0

    start_year = float(params.get("start_year", years[0] if years else 0))
    demand_response_start_year = float(params.get("demand_response_start_year", 2020))

    sm_name = "smDemandModel"
    scenario_manager = {
        sm_name: {
            "model": model,
            "base_constants": {
                "start_year": start_year,
                "demand_response_start_year": demand_response_start_year,
                "capacity_envelope_initial": float(capacity_envelope_initial_vals[0]),
                "demand_surge_start": float(params.get("demand_surge_start", -1.0)),
                "demand_surge_duration": float(params.get("demand_surge_duration", 0.0)),
                "demand_surge_multiplier": float(params.get("demand_surge_multiplier", 1.0)),
                "collection_shock_start": float(params.get("collection_shock_start", -1.0)),
                "collection_shock_duration": float(params.get("collection_shock_duration", 0.0)),
                "collection_shock_multiplier": float(params.get("collection_shock_multiplier", 1.0)),
            },
            "base_points": {
                "demand_exogenous": demand_points,
                "scarcity_multiplier": scarcity_points,
                "service_stress_signal": service_stress_points,
                "price_base": price_base_points,
                "price_scarcity_sensitivity": price_scarcity_sensitivity_points,
                "demand_price_elasticity": demand_price_elasticity_points,
                "capacity_envelope_min": capacity_envelope_min_points,
                "capacity_envelope_max": capacity_envelope_max_points,
                "capacity_expansion_gain": capacity_expansion_gain_points,
                "capacity_retirement_gain": capacity_retirement_gain_points,
                "capacity_adjustment_lag_years": capacity_adjustment_lag_years_points,
                "capacity_pressure_shortage_weight": capacity_pressure_shortage_weight_points,
                "bottleneck_scarcity_gain": bottleneck_scarcity_gain_points,
                "bottleneck_collection_sensitivity": bottleneck_collection_sensitivity_points,
                "collection_price_response_gain": collection_price_response_gain_points,
                "strategic_stock_coverage_years": strategic_coverage_points,
                "collection_multiplier_min": collection_multiplier_min_points,
                "collection_multiplier_max": collection_multiplier_max_points,
                "collection_multiplier_lag_years": collection_multiplier_lag_years_points,
                "strategic_reserve_enabled": strategic_reserve_enabled_points,
                "strategic_reserve_target_coverage_years": strategic_reserve_target_coverage_years_points,
                "strategic_reserve_fill_gain": strategic_reserve_fill_gain_points,
                "strategic_reserve_release_gain": strategic_reserve_release_gain_points,
                "strategic_reserve_max_fill_rate": strategic_reserve_max_fill_rate_points,
                "strategic_reserve_max_release_rate": strategic_reserve_max_release_rate_points,
                "strategic_reserve_fill_price_threshold": strategic_reserve_fill_price_threshold_points,
                "strategic_reserve_release_price_threshold": strategic_reserve_release_price_threshold_points,
                "strategic_reserve_fill_service_threshold": strategic_reserve_fill_service_threshold_points,
                "strategic_reserve_release_service_threshold": strategic_reserve_release_service_threshold_points,
            },
        }
    }

    b = bptk()
    b.register_scenario_manager(scenario_manager)
    b.register_scenarios(scenarios={"base": {"constants": {}}}, scenario_manager=sm_name)

    out = b.run_scenarios(
        scenarios="base",
        scenario_managers=sm_name,
        equations=[
            "demand",
            "price",
            "scarcity_multiplier",
            "scarcity_multiplier_effective",
            "capacity_envelope",
            "flow_utilization",
            "bottleneck_pressure",
            "collection_bottleneck_throttle",
            "collection_multiplier_target",
            "collection_multiplier",
            "strategic_fill_intent",
            "strategic_release_intent",
        ],
        return_format="dict",
    )
    try:
        eq = out[sm_name]["base"]["equations"]
    except Exception as exc:
        raise KeyError(
            "Unexpected BPTK run_scenarios(dict) output structure; expected "
            f"['{sm_name}']['base']['equations']."
        ) from exc

    required_series = {
        "demand",
        "price",
        "scarcity_multiplier",
        "scarcity_multiplier_effective",
        "capacity_envelope",
        "flow_utilization",
        "bottleneck_pressure",
        "collection_bottleneck_throttle",
        "collection_multiplier_target",
        "collection_multiplier",
        "strategic_fill_intent",
        "strategic_release_intent",
    }
    missing_series = sorted(list(required_series - set(eq.keys())))
    if missing_series:
        raise KeyError(
            "BPTK equations payload is missing required series: "
            + ", ".join(missing_series)
        )

    demand_s = pd.Series(eq["demand"])
    price_s = pd.Series(eq["price"])
    scarcity_s = pd.Series(eq["scarcity_multiplier"])
    scarcity_effective_s = pd.Series(eq["scarcity_multiplier_effective"])
    capacity_envelope_s = pd.Series(eq["capacity_envelope"])
    flow_utilization_s = pd.Series(eq["flow_utilization"])
    bottleneck_pressure_s = pd.Series(eq["bottleneck_pressure"])
    collection_bottleneck_throttle_s = pd.Series(eq["collection_bottleneck_throttle"])
    collection_target_s = pd.Series(eq["collection_multiplier_target"])
    collection_multiplier_s = pd.Series(eq["collection_multiplier"])
    strategic_fill_intent_s = pd.Series(eq["strategic_fill_intent"])
    strategic_release_intent_s = pd.Series(eq["strategic_release_intent"])
    if (
        len(demand_s) != horizon + 1
        or len(price_s) != horizon + 1
        or len(scarcity_s) != horizon + 1
        or len(scarcity_effective_s) != horizon + 1
        or len(capacity_envelope_s) != horizon + 1
        or len(flow_utilization_s) != horizon + 1
        or len(bottleneck_pressure_s) != horizon + 1
        or len(collection_bottleneck_throttle_s) != horizon + 1
        or len(collection_target_s) != horizon + 1
        or len(collection_multiplier_s) != horizon + 1
        or len(strategic_fill_intent_s) != horizon + 1
        or len(strategic_release_intent_s) != horizon + 1
    ):
        raise ValueError(
            "Unexpected BPTK output length: "
            f"demand={len(demand_s)}, price={len(price_s)}, "
            f"scarcity_multiplier={len(scarcity_s)}, "
            f"scarcity_multiplier_effective={len(scarcity_effective_s)}, "
            f"capacity_envelope={len(capacity_envelope_s)}, "
            f"flow_utilization={len(flow_utilization_s)}, "
            f"bottleneck_pressure={len(bottleneck_pressure_s)}, "
            f"collection_bottleneck_throttle={len(collection_bottleneck_throttle_s)}, "
            f"collection_multiplier_target={len(collection_target_s)}, "
            f"collection_multiplier={len(collection_multiplier_s)}, "
            f"strategic_fill_intent={len(strategic_fill_intent_s)}, "
            f"strategic_release_intent={len(strategic_release_intent_s)}, "
            f"expected={horizon + 1}."
        )

    demand = demand_s.to_numpy(dtype=float)
    price = price_s.to_numpy(dtype=float)
    scarcity_mult = scarcity_s.to_numpy(dtype=float)
    scarcity_effective = scarcity_effective_s.to_numpy(dtype=float)
    capacity_envelope = capacity_envelope_s.to_numpy(dtype=float)
    flow_utilization = flow_utilization_s.to_numpy(dtype=float)
    bottleneck_pressure = bottleneck_pressure_s.to_numpy(dtype=float)
    collection_bottleneck_throttle = collection_bottleneck_throttle_s.to_numpy(dtype=float)
    collection_target = collection_target_s.to_numpy(dtype=float)
    collection_multiplier = collection_multiplier_s.to_numpy(dtype=float)
    strategic_fill_intent = strategic_fill_intent_s.to_numpy(dtype=float)
    strategic_release_intent = strategic_release_intent_s.to_numpy(dtype=float)
    scarcity_mult = np.maximum(scarcity_mult, 0.0)
    scarcity_effective = np.maximum(scarcity_effective, 0.0)
    capacity_envelope = np.maximum(capacity_envelope, 0.0)
    flow_utilization = np.maximum(flow_utilization, 0.0)
    bottleneck_pressure = np.maximum(bottleneck_pressure, 0.0)
    collection_bottleneck_throttle = np.maximum(collection_bottleneck_throttle, 0.0)
    collection_target = np.maximum(collection_target, 0.0)
    collection_multiplier = np.maximum(collection_multiplier, 0.0)
    strategic_fill_intent = np.clip(strategic_fill_intent, 0.0, 1.0)
    strategic_release_intent = np.clip(strategic_release_intent, 0.0, 1.0)

    return SDTimeseries(
        years=years,
        demand=pd.Series(demand, index=years),
        price=pd.Series(price, index=years),
        scarcity_multiplier=pd.Series(scarcity_mult, index=years),
        scarcity_multiplier_effective=pd.Series(scarcity_effective, index=years),
        capacity_envelope=pd.Series(capacity_envelope, index=years),
        flow_utilization=pd.Series(flow_utilization, index=years),
        bottleneck_pressure=pd.Series(bottleneck_pressure, index=years),
        collection_bottleneck_throttle=pd.Series(collection_bottleneck_throttle, index=years),
        collection_multiplier_target=pd.Series(collection_target, index=years),
        collection_multiplier=pd.Series(collection_multiplier, index=years),
        strategic_fill_intent=pd.Series(strategic_fill_intent, index=years),
        strategic_release_intent=pd.Series(strategic_release_intent, index=years),
    )


__all__ = ["run_bptk_sd"]
