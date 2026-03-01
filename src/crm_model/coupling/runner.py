from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from crm_model.indicators.circularity import end_of_life_recycling_rate, recycling_input_rate
from crm_model.indicators.resilience import (
    max_consecutive_years_below_threshold,
    resilience_triangle_area,
    service_deficit,
    service_level,
    unmet_service,
    years_below_service_threshold,
)
from crm_model.coupling.interface import validate_coupling_signal_registry
from crm_model.mfa.run_mfa import run_flodym_mfa
from crm_model.mfa.system import MFATimeseries
from crm_model.sd.bptk_model import SDTimeseries
from crm_model.sd.params import (
    expand_temporal_value,
    inject_gate_before,
    is_year_gate,
    migrate_legacy_strategy_sd_controls,
    normalize_and_validate_sd_parameters,
)
from crm_model.sd.run_sd import run_bptk_sd


@dataclass
class CoupledRunResult:
    sd: SDTimeseries
    mfa: MFATimeseries
    indicators_ts: Dict[str, pd.Series]
    indicators_scalar: Dict[str, float]
    coupling_signals_iter_year: pd.DataFrame
    coupling_convergence_iter: pd.DataFrame
    meta: Dict[str, Any]


def _split_end_use_demand_by_year(total: np.ndarray, shares_te: np.ndarray, end_uses: list[str]) -> np.ndarray:
    e_len = len(end_uses) if len(end_uses) else 1
    t = len(total)

    arr = np.array(shares_te, dtype=float)
    if arr.shape != (t, e_len):
        raise ValueError(f"end_use_shares_te must have shape (t,e)=({t},{e_len}); got {arr.shape}")

    row_sums = arr.sum(axis=1)
    for i in range(t):
        if row_sums[i] > 0:
            arr[i, :] = arr[i, :] / row_sums[i]
        else:
            arr[i, :] = np.ones(e_len, dtype=float) / e_len

    return total[:, None] * arr


def _shock_multiplier_series(years: list[int], start_year: int, duration: int, multiplier: float) -> np.ndarray:
    mult = np.ones(len(years), dtype=float)
    end_year = start_year + duration
    for i, y in enumerate(years):
        if start_year <= y < end_year:
            mult[i] = float(multiplier)
    return mult


def _strategy_override_with_before(strategy: Dict[str, Any], key: str, baseline: Any) -> Any:
    if key not in strategy:
        return baseline
    return inject_gate_before(strategy.get(key), baseline)


def _as_timeseries(
    value: Any,
    *,
    years: list[int],
    name: str,
    default: float,
    report_start_year: int | None = None,
    emit_warnings: bool = False,
) -> np.ndarray:
    return expand_temporal_value(
        value,
        years=years,
        name=name,
        default=default,
        report_start_year=report_start_year,
        emit_warnings=emit_warnings,
        context="run_loose_coupled",
    )


def _resolve_collection_control_series(
    sd_params: Dict[str, Any],
    strategy: Dict[str, Any],
    years: list[int],
    *,
    report_start_year: int | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    def _resolve_value(key: str, default: Any) -> Any:
        if key in sd_params:
            return sd_params.get(key)
        return _strategy_override_with_before(strategy, key, default)

    mult_min = _as_timeseries(
        _resolve_value("collection_multiplier_min", 0.0),
        years=years,
        name="collection_multiplier_min",
        default=0.0,
        report_start_year=report_start_year if "collection_multiplier_min" in sd_params else None,
        emit_warnings="collection_multiplier_min" in sd_params,
    )
    mult_max = _as_timeseries(
        _resolve_value("collection_multiplier_max", 1.0e6),
        years=years,
        name="collection_multiplier_max",
        default=1.0e6,
        report_start_year=report_start_year if "collection_multiplier_max" in sd_params else None,
        emit_warnings="collection_multiplier_max" in sd_params,
    )
    lag_years = _as_timeseries(
        _resolve_value("collection_multiplier_lag_years", 0.0),
        years=years,
        name="collection_multiplier_lag_years",
        default=0.0,
        report_start_year=report_start_year if "collection_multiplier_lag_years" in sd_params else None,
        emit_warnings="collection_multiplier_lag_years" in sd_params,
    )

    if (lag_years < 0).any():
        raise ValueError("collection_multiplier_lag_years must be >= 0.")
    if (mult_min < 0).any():
        raise ValueError("collection_multiplier_min must be >= 0.")
    if (mult_max <= 0).any():
        raise ValueError("collection_multiplier_max must be > 0.")
    if (mult_min > mult_max).any():
        raise ValueError("collection_multiplier_min must be <= collection_multiplier_max.")
    return mult_min, mult_max, lag_years


def run_loose_coupled(
    years: list[int],
    *,
    material: str,
    region: str,
    end_uses: list[str],
    final_demand_t: np.ndarray,
    end_use_shares_te: np.ndarray,
    sd_params: Dict[str, Any],
    mfa_params: Dict[str, Any],
    mfa_graph: Optional[Dict[str, Any]] = None,
    service_level_threshold: float = 0.95,
    strategy: Optional[Dict[str, Any]] = None,
    shocks: Optional[Dict[str, Any]] = None,
    coupling: Optional[Dict[str, Any]] = None,
) -> CoupledRunResult:
    """Loose iterative coupling: SD ↔ dMFA."""

    report_start_year_raw = sd_params.get("report_start_year")
    report_start_year = int(report_start_year_raw) if report_start_year_raw is not None else None
    sd_params = normalize_and_validate_sd_parameters(
        sd_params,
        years=years,
        report_start_year=report_start_year,
        emit_warnings=True,
        context="run_loose_coupled",
    )
    sd_params, strategy = migrate_legacy_strategy_sd_controls(
        sd_parameters=sd_params,
        strategy=strategy or {},
        emit_warnings=False,
        context="run_loose_coupled",
    )
    sd_params = normalize_and_validate_sd_parameters(
        sd_params,
        years=years,
        report_start_year=report_start_year,
        emit_warnings=True,
        context="run_loose_coupled",
    )
    shocks = shocks or {}
    coupling = coupling or {}
    validate_coupling_signal_registry(coupling)

    max_iter = int(coupling.get("max_iter", 3))
    tol = float(coupling.get("convergence_tol", 1e-3))
    feedback_signal_mode = str(coupling.get("feedback_signal_mode", "time_series")).strip().lower()
    feedback_on_report_years_only = bool(coupling.get("feedback_on_report_years_only", True))
    if feedback_signal_mode not in {"time_series", "scalar_mean"}:
        raise ValueError(
            "coupling.feedback_signal_mode must be one of {'time_series', 'scalar_mean'}; "
            f"got {feedback_signal_mode!r}."
        )

    coupling_signal_smoothing_ts = np.clip(
        _as_timeseries(
            sd_params.get("coupling_signal_smoothing", 0.5),
            years=years,
            name="coupling_signal_smoothing",
            default=0.5,
            report_start_year=report_start_year,
            emit_warnings=True,
        ),
        0.0,
        1.0,
    )
    coupling_signal_smoothing_strategic_ts = np.clip(
        _as_timeseries(
            sd_params.get("coupling_signal_smoothing_strategic", sd_params.get("coupling_signal_smoothing", 0.5)),
            years=years,
            name="coupling_signal_smoothing_strategic",
            default=0.5,
            report_start_year=report_start_year,
            emit_warnings=True,
        ),
        0.0,
        1.0,
    )
    coupling_service_stress_gain_ts = _as_timeseries(
        sd_params.get("coupling_service_stress_gain", 5.0),
        years=years,
        name="coupling_service_stress_gain",
        default=5.0,
        report_start_year=report_start_year,
        emit_warnings=True,
    )
    service_stress_signal_cap_ts = np.clip(
        _as_timeseries(
            sd_params.get("service_stress_signal_cap", 1.0),
            years=years,
            name="service_stress_signal_cap",
            default=1.0,
            report_start_year=report_start_year,
            emit_warnings=True,
        ),
        0.0,
        1.0,
    )
    coupling_stress_multiplier_cap_ts = _as_timeseries(
        sd_params.get("coupling_stress_multiplier_cap", 1.0e6),
        years=years,
        name="coupling_stress_multiplier_cap",
        default=1.0e6,
        report_start_year=report_start_year,
        emit_warnings=True,
    )
    if (coupling_stress_multiplier_cap_ts < 1.0).any():
        raise ValueError("sd_parameters.coupling_stress_multiplier_cap must be >= 1.0.")
    coupling_circular_supply_stress_gain_ts = _as_timeseries(
        sd_params.get("coupling_circular_supply_stress_gain", 1.0),
        years=years,
        name="coupling_circular_supply_stress_gain",
        default=1.0,
        report_start_year=report_start_year,
        emit_warnings=True,
    )
    strategic_reserve_enabled_ts = np.clip(
        _as_timeseries(
            _strategy_override_with_before(strategy, "strategic_reserve_enabled", False),
            years=years,
            name="strategic_reserve_enabled",
            default=0.0,
        ),
        0.0,
        1.0,
    )
    strategic_reserve_target_coverage_years_ts = _as_timeseries(
        _strategy_override_with_before(strategy, "strategic_reserve_target_coverage_years", 0.5),
        years=years,
        name="strategic_reserve_target_coverage_years",
        default=0.5,
    )
    strategic_reserve_fill_gain_ts = _as_timeseries(
        _strategy_override_with_before(strategy, "strategic_reserve_fill_gain", 0.5),
        years=years,
        name="strategic_reserve_fill_gain",
        default=0.5,
    )
    strategic_reserve_release_gain_ts = _as_timeseries(
        _strategy_override_with_before(strategy, "strategic_reserve_release_gain", 1.0),
        years=years,
        name="strategic_reserve_release_gain",
        default=1.0,
    )
    strategic_reserve_max_fill_rate_ts = _as_timeseries(
        _strategy_override_with_before(strategy, "strategic_reserve_max_fill_rate", 0.15),
        years=years,
        name="strategic_reserve_max_fill_rate",
        default=0.15,
    )
    strategic_reserve_max_release_rate_ts = _as_timeseries(
        _strategy_override_with_before(strategy, "strategic_reserve_max_release_rate", 0.25),
        years=years,
        name="strategic_reserve_max_release_rate",
        default=0.25,
    )
    strategic_reserve_fill_price_threshold_ts = _as_timeseries(
        _strategy_override_with_before(strategy, "strategic_reserve_fill_price_threshold", 1.0),
        years=years,
        name="strategic_reserve_fill_price_threshold",
        default=1.0,
    )
    strategic_reserve_release_price_threshold_ts = _as_timeseries(
        _strategy_override_with_before(strategy, "strategic_reserve_release_price_threshold", 1.1),
        years=years,
        name="strategic_reserve_release_price_threshold",
        default=1.1,
    )
    strategic_reserve_fill_service_threshold_ts = _as_timeseries(
        _strategy_override_with_before(strategy, "strategic_reserve_fill_service_threshold", 0.05),
        years=years,
        name="strategic_reserve_fill_service_threshold",
        default=0.05,
    )
    strategic_reserve_release_service_threshold_ts = _as_timeseries(
        _strategy_override_with_before(strategy, "strategic_reserve_release_service_threshold", 0.15),
        years=years,
        name="strategic_reserve_release_service_threshold",
        default=0.15,
    )

    if (strategic_reserve_target_coverage_years_ts < 0).any():
        raise ValueError("strategy.strategic_reserve_target_coverage_years must be >= 0.")
    if (strategic_reserve_fill_gain_ts < 0).any() or (strategic_reserve_release_gain_ts < 0).any():
        raise ValueError("strategy strategic_reserve_fill_gain/release_gain must be >= 0.")
    if (strategic_reserve_fill_price_threshold_ts <= 0).any() or (
        strategic_reserve_release_price_threshold_ts <= 0
    ).any():
        raise ValueError("strategy strategic reserve price thresholds must be > 0.")
    for name, value in {
        "strategic_reserve_max_fill_rate": strategic_reserve_max_fill_rate_ts,
        "strategic_reserve_max_release_rate": strategic_reserve_max_release_rate_ts,
        "strategic_reserve_fill_service_threshold": strategic_reserve_fill_service_threshold_ts,
        "strategic_reserve_release_service_threshold": strategic_reserve_release_service_threshold_ts,
    }.items():
        if (value < 0).any() or (value > 1).any():
            raise ValueError(f"strategy.{name} must be in [0,1].")

    collection_multiplier_min_ts, collection_multiplier_max_ts, collection_multiplier_lag_years_ts = (
        _resolve_collection_control_series(
            sd_params,
            strategy,
            years,
            report_start_year=report_start_year,
        )
    )

    base_scarcity = _as_timeseries(
        sd_params.get("scarcity_multiplier"),
        years=years,
        name="scarcity_multiplier",
        default=1.0,
        report_start_year=report_start_year,
        emit_warnings=is_year_gate(sd_params.get("scarcity_multiplier")),
    )
    service_signal_set = ("service_stress_signal" in sd_params) or ("service_stress_signal_t" in sd_params)
    circular_signal_set = ("circular_supply_stress_signal" in sd_params) or (
        "circular_supply_stress_signal_t" in sd_params
    )
    service_stress_signal = _as_timeseries(
        sd_params.get("service_stress_signal_t", sd_params.get("service_stress_signal")),
        years=years,
        name="service_stress_signal",
        default=0.0,
        report_start_year=report_start_year,
        emit_warnings=is_year_gate(sd_params.get("service_stress_signal_t", sd_params.get("service_stress_signal"))),
    )
    circular_supply_stress_signal = _as_timeseries(
        sd_params.get("circular_supply_stress_signal_t", sd_params.get("circular_supply_stress_signal")),
        years=years,
        name="circular_supply_stress_signal",
        default=0.0,
        report_start_year=report_start_year,
        emit_warnings=is_year_gate(
            sd_params.get("circular_supply_stress_signal_t", sd_params.get("circular_supply_stress_signal"))
        ),
    )
    strategic_stock_coverage_signal = _as_timeseries(
        sd_params.get(
            "strategic_stock_coverage_years_t",
            sd_params.get("strategic_stock_coverage_years", 0.0),
        ),
        years=years,
        name="strategic_stock_coverage_years",
        default=0.0,
        report_start_year=report_start_year,
        emit_warnings=is_year_gate(
            sd_params.get("strategic_stock_coverage_years_t", sd_params.get("strategic_stock_coverage_years"))
        ),
    )
    if (not service_signal_set) and (not circular_signal_set) and np.max(np.abs(base_scarcity - 1.0)) > 1.0e-12:
        gain_safe = np.maximum(coupling_service_stress_gain_ts, 1.0e-12)
        inferred = np.clip((base_scarcity - 1.0) / gain_safe, 0.0, 1.0)
        service_stress_signal = np.where(coupling_service_stress_gain_ts > 0.0, inferred, 0.0)

    service_stress_signal = np.clip(service_stress_signal, 0.0, service_stress_signal_cap_ts)
    circular_supply_stress_signal = np.clip(circular_supply_stress_signal, 0.0, 1.0)
    strategic_stock_coverage_signal = np.maximum(strategic_stock_coverage_signal, 0.0)

    def _stress_multiplier(service_signal: Any, circular_signal: Any) -> np.ndarray:
        service = np.array(service_signal, dtype=float)
        circular = np.array(circular_signal, dtype=float)
        raw = (
            1.0
            + coupling_service_stress_gain_ts * service
            + coupling_circular_supply_stress_gain_ts * circular
        )
        return np.minimum(raw, coupling_stress_multiplier_cap_ts)

    demand_surge = shocks.get("demand_surge")
    rec_disrupt = shocks.get("recycling_disruption")
    collection_rate_shock = shocks.get("collection_rate")
    strategic_fill_intent_shock = shocks.get("strategic_fill_intent")
    strategic_release_intent_shock = shocks.get("strategic_release_intent")

    if isinstance(rec_disrupt, dict):
        rec_disrupt_mult = _shock_multiplier_series(
            years,
            start_year=int(rec_disrupt["start_year"]),
            duration=int(rec_disrupt["duration_years"]),
            multiplier=float(rec_disrupt["multiplier"]),
        )
    else:
        rec_disrupt_mult = np.ones(len(years), dtype=float)

    if isinstance(strategic_fill_intent_shock, dict):
        strategic_fill_intent_mult = _shock_multiplier_series(
            years,
            start_year=int(strategic_fill_intent_shock["start_year"]),
            duration=int(strategic_fill_intent_shock["duration_years"]),
            multiplier=float(strategic_fill_intent_shock["multiplier"]),
        )
    else:
        strategic_fill_intent_mult = np.ones(len(years), dtype=float)

    if isinstance(strategic_release_intent_shock, dict):
        strategic_release_intent_mult = _shock_multiplier_series(
            years,
            start_year=int(strategic_release_intent_shock["start_year"]),
            duration=int(strategic_release_intent_shock["duration_years"]),
            multiplier=float(strategic_release_intent_shock["multiplier"]),
        )
    else:
        strategic_release_intent_mult = np.ones(len(years), dtype=float)

    last_sd: Optional[SDTimeseries] = None
    last_mfa: Optional[MFATimeseries] = None
    signal_trace_rows: list[Dict[str, Any]] = []
    convergence_rows: list[Dict[str, Any]] = []
    converged = False
    last_max_signal_delta = float("inf")
    final_collection_multiplier = np.ones(len(years), dtype=float)
    final_collection_rate = _as_timeseries(
        mfa_params.get("collection_rate"),
        years=years,
        name="collection_rate",
        default=0.4,
    )
    final_strategic_fill_intent = np.zeros(len(years), dtype=float)
    final_strategic_release_intent = np.zeros(len(years), dtype=float)
    collection_multiplier_prev = np.ones(len(years), dtype=float)
    strategic_fill_intent_prev = np.zeros(len(years), dtype=float)
    strategic_release_intent_prev = np.zeros(len(years), dtype=float)

    end_use_items = end_uses or ["total"]

    for it in range(max_iter):
        service_signal_prev = service_stress_signal.copy()
        circular_signal_prev = circular_supply_stress_signal.copy()
        strategic_signal_prev = strategic_stock_coverage_signal.copy()
        stress_multiplier_prev = _stress_multiplier(service_signal_prev, circular_signal_prev)

        sd_params_it = dict(sd_params)
        sd_params_it["scarcity_multiplier"] = stress_multiplier_prev
        sd_params_it["service_stress_signal"] = service_signal_prev
        sd_params_it["strategic_stock_coverage_years"] = strategic_signal_prev
        sd_params_it["demand_exogenous"] = final_demand_t

        if "start_year" not in sd_params_it:
            sd_params_it["start_year"] = int(years[0]) if years else 0
        if "demand_response_start_year" not in sd_params_it:
            ry = sd_params_it.get("report_start_year")
            sd_params_it["demand_response_start_year"] = int(ry) if ry is not None else 2020

        if isinstance(demand_surge, dict) and float(demand_surge.get("multiplier", 1.0)) != 1.0:
            sd_params_it["demand_surge_start"] = float(int(demand_surge["start_year"]) - years[0])
            sd_params_it["demand_surge_duration"] = float(demand_surge["duration_years"])
            sd_params_it["demand_surge_multiplier"] = float(demand_surge["multiplier"])
        if isinstance(collection_rate_shock, dict) and float(collection_rate_shock.get("multiplier", 1.0)) != 1.0:
            sd_params_it["collection_shock_start"] = float(int(collection_rate_shock["start_year"]) - years[0])
            sd_params_it["collection_shock_duration"] = float(collection_rate_shock["duration_years"])
            sd_params_it["collection_shock_multiplier"] = float(collection_rate_shock["multiplier"])

        collection_price_response_gain_ts = _as_timeseries(
            sd_params_it.get("collection_price_response_gain", 0.0),
            years=years,
            name="collection_price_response_gain",
            default=0.0,
            report_start_year=report_start_year,
            emit_warnings=is_year_gate(sd_params_it.get("collection_price_response_gain")),
        )
        if (collection_price_response_gain_ts < 0).any():
            raise ValueError(
                "collection_price_response_gain must be >= 0 for sd_endogenous collection control."
            )
        price_base_ts = _as_timeseries(
            sd_params_it.get("price_base", 1.0),
            years=years,
            name="price_base",
            default=1.0,
            report_start_year=report_start_year,
            emit_warnings=is_year_gate(sd_params_it.get("price_base")),
        )
        if (price_base_ts <= 0).any():
            raise ValueError("sd_parameters.price_base must be > 0 for sd_endogenous collection control.")
        sd_params_it["collection_price_response_gain"] = collection_price_response_gain_ts
        sd_params_it["collection_multiplier_min"] = collection_multiplier_min_ts
        sd_params_it["collection_multiplier_max"] = collection_multiplier_max_ts
        sd_params_it["collection_multiplier_lag_years"] = collection_multiplier_lag_years_ts
        sd_params_it["strategic_reserve_enabled"] = strategic_reserve_enabled_ts
        sd_params_it["strategic_reserve_target_coverage_years"] = strategic_reserve_target_coverage_years_ts
        sd_params_it["strategic_reserve_fill_gain"] = strategic_reserve_fill_gain_ts
        sd_params_it["strategic_reserve_release_gain"] = strategic_reserve_release_gain_ts
        sd_params_it["strategic_reserve_max_fill_rate"] = strategic_reserve_max_fill_rate_ts
        sd_params_it["strategic_reserve_max_release_rate"] = strategic_reserve_max_release_rate_ts
        sd_params_it["strategic_reserve_fill_price_threshold"] = strategic_reserve_fill_price_threshold_ts
        sd_params_it["strategic_reserve_release_price_threshold"] = strategic_reserve_release_price_threshold_ts
        sd_params_it["strategic_reserve_fill_service_threshold"] = strategic_reserve_fill_service_threshold_ts
        sd_params_it["strategic_reserve_release_service_threshold"] = (
            strategic_reserve_release_service_threshold_ts
        )

        sd_ts = run_bptk_sd(years=years, params=sd_params_it)
        sd_scarcity_multiplier_effective = sd_ts.scarcity_multiplier_effective.values.astype(float)
        sd_capacity_envelope = sd_ts.capacity_envelope.values.astype(float)
        sd_flow_utilization = sd_ts.flow_utilization.values.astype(float)
        sd_bottleneck_pressure = sd_ts.bottleneck_pressure.values.astype(float)
        sd_collection_bottleneck_throttle = sd_ts.collection_bottleneck_throttle.values.astype(float)

        base_collection_rate = _as_timeseries(
            mfa_params.get("collection_rate"),
            years=years,
            name="collection_rate",
            default=0.4,
        )
        collection_multiplier_target = sd_ts.collection_multiplier_target.values.astype(float)
        collection_multiplier_next = sd_ts.collection_multiplier.values.astype(float)
        collection_rate_it = np.clip(base_collection_rate * collection_multiplier_next, 0.0, 1.0)

        mfa_params_it = dict(mfa_params)
        mfa_params_it["collection_rate"] = collection_rate_it
        strategic_fill_intent_it = np.clip(
            sd_ts.strategic_fill_intent.values.astype(float) * strategic_fill_intent_mult,
            0.0,
            1.0,
        )
        strategic_release_intent_it = np.clip(
            sd_ts.strategic_release_intent.values.astype(float) * strategic_release_intent_mult,
            0.0,
            1.0,
        )
        strategic_enabled_mask = strategic_reserve_enabled_ts > 0.5
        strategic_fill_intent_it = np.where(strategic_enabled_mask, strategic_fill_intent_it, 0.0)
        strategic_release_intent_it = np.where(strategic_enabled_mask, strategic_release_intent_it, 0.0)
        mfa_params_it["strategic_reserve_enabled"] = strategic_reserve_enabled_ts
        mfa_params_it["strategic_fill_intent"] = strategic_fill_intent_it
        mfa_params_it["strategic_release_intent"] = strategic_release_intent_it

        demand_te = _split_end_use_demand_by_year(sd_ts.demand.values.astype(float), end_use_shares_te, end_use_items)
        service_demand_tre = demand_te[:, None, :]

        _, mfa_ts = run_flodym_mfa(
            years=years,
            regions=[region],
            end_uses=end_use_items,
            service_demand_tre=service_demand_tre,
            params=mfa_params_it,
            mfa_graph=mfa_graph,
            strategy=strategy,
            shocks={"recycling_disruption_multiplier": rec_disrupt_mult},
        )

        service_stress_series = (mfa_ts.unmet_service / mfa_ts.service_demand.replace(0, np.nan)).fillna(0.0)
        circular_supply_stress_series = (
            1.0
            - (mfa_ts.secondary_supply / (mfa_ts.primary_supply + mfa_ts.secondary_supply).replace(0, np.nan)).fillna(0.0)
        ).clip(lower=0.0, upper=1.0)
        strategic_stock_coverage_series = mfa_ts.strategic_stock_coverage_years.clip(lower=0.0)

        report_years = sd_params_it.get("report_years")
        report_year_mask = np.ones(len(years), dtype=bool)
        if feedback_on_report_years_only and isinstance(report_years, (list, tuple)) and report_years:
            report_year_set = {int(y) for y in report_years}
            report_year_mask = np.array([int(y) in report_year_set for y in years], dtype=bool)

        service_stress_year = service_stress_series.reindex(years).fillna(0.0).to_numpy(dtype=float)
        circular_supply_stress_year = circular_supply_stress_series.reindex(years).fillna(0.0).to_numpy(dtype=float)
        strategic_stock_coverage_year = (
            strategic_stock_coverage_series.reindex(years).fillna(0.0).to_numpy(dtype=float)
        )

        if feedback_signal_mode == "scalar_mean":
            service_eval = (
                float(service_stress_year[report_year_mask].mean()) if np.any(report_year_mask) else 0.0
            )
            circular_eval = (
                float(circular_supply_stress_year[report_year_mask].mean()) if np.any(report_year_mask) else 0.0
            )
            strategic_eval = (
                float(strategic_stock_coverage_year[report_year_mask].mean())
                if np.any(report_year_mask)
                else 0.0
            )
            service_stress_target = np.full(len(years), service_eval, dtype=float)
            circular_supply_stress_target = np.full(len(years), circular_eval, dtype=float)
            strategic_stock_coverage_target = np.full(len(years), strategic_eval, dtype=float)
        else:
            service_stress_target = service_stress_year.copy()
            circular_supply_stress_target = circular_supply_stress_year.copy()
            strategic_stock_coverage_target = strategic_stock_coverage_year.copy()

        if feedback_on_report_years_only:
            service_stress_target = np.where(report_year_mask, service_stress_target, service_signal_prev)
            circular_supply_stress_target = np.where(report_year_mask, circular_supply_stress_target, circular_signal_prev)
            strategic_stock_coverage_target = np.where(
                report_year_mask,
                strategic_stock_coverage_target,
                strategic_signal_prev,
            )

        service_stress_target = np.clip(service_stress_target, 0.0, service_stress_signal_cap_ts)

        service_stress_new = (
            (1.0 - coupling_signal_smoothing_ts) * service_signal_prev
            + coupling_signal_smoothing_ts * service_stress_target
        )
        circular_supply_stress_new = (
            (1.0 - coupling_signal_smoothing_ts) * circular_signal_prev
            + coupling_signal_smoothing_ts * circular_supply_stress_target
        )
        strategic_stock_coverage_new = (
            (1.0 - coupling_signal_smoothing_strategic_ts) * strategic_signal_prev
            + coupling_signal_smoothing_strategic_ts * strategic_stock_coverage_target
        )
        service_stress_new = np.clip(service_stress_new, 0.0, service_stress_signal_cap_ts)
        circular_supply_stress_new = np.clip(circular_supply_stress_new, 0.0, 1.0)
        strategic_stock_coverage_new = np.maximum(strategic_stock_coverage_new, 0.0)
        stress_multiplier_new = _stress_multiplier(service_stress_new, circular_supply_stress_new)
        service_residual_lag = service_stress_target - service_stress_new
        circular_residual_lag = circular_supply_stress_target - circular_supply_stress_new
        strategic_residual_lag = strategic_stock_coverage_target - strategic_stock_coverage_new
        max_signal_delta = float(
            max(
                np.max(np.abs(service_stress_new - service_signal_prev)),
                np.max(np.abs(circular_supply_stress_new - circular_signal_prev)),
                np.max(np.abs(strategic_stock_coverage_new - strategic_signal_prev)),
            )
        )
        collection_multiplier_delta = float(
            np.max(np.abs(collection_multiplier_next - collection_multiplier_prev))
        )
        strategic_intent_delta = float(
            max(
                np.max(np.abs(strategic_fill_intent_it - strategic_fill_intent_prev)),
                np.max(np.abs(strategic_release_intent_it - strategic_release_intent_prev)),
            )
        )
        convergence_metric = float(
            max(max_signal_delta, collection_multiplier_delta, strategic_intent_delta)
        )
        last_max_signal_delta = convergence_metric
        converged = bool(convergence_metric < tol)

        last_sd, last_mfa = sd_ts, mfa_ts
        final_collection_multiplier = collection_multiplier_next
        final_collection_rate = collection_rate_it
        final_strategic_fill_intent = strategic_fill_intent_it
        final_strategic_release_intent = strategic_release_intent_it

        convergence_rows.append(
            {
                "iteration": int(it + 1),
                "service_stress_signal_prev": float(np.mean(service_signal_prev)),
                "service_stress_signal_target": float(np.mean(service_stress_target)),
                "service_stress_signal_next": float(np.mean(service_stress_new)),
                "service_stress_residual_lag": float(np.mean(service_residual_lag)),
                "circular_supply_stress_signal_prev": float(np.mean(circular_signal_prev)),
                "circular_supply_stress_signal_target": float(np.mean(circular_supply_stress_target)),
                "circular_supply_stress_signal_next": float(np.mean(circular_supply_stress_new)),
                "circular_supply_stress_residual_lag": float(np.mean(circular_residual_lag)),
                "strategic_stock_coverage_signal_prev": float(np.mean(strategic_signal_prev)),
                "strategic_stock_coverage_signal_target": float(np.mean(strategic_stock_coverage_target)),
                "strategic_stock_coverage_signal_next": float(np.mean(strategic_stock_coverage_new)),
                "strategic_stock_coverage_residual_lag": float(np.mean(strategic_residual_lag)),
                "stress_multiplier_prev": float(np.mean(stress_multiplier_prev)),
                "stress_multiplier_next": float(np.mean(stress_multiplier_new)),
                "max_signal_delta": max_signal_delta,
                "collection_multiplier_delta": collection_multiplier_delta,
                "strategic_intent_delta": strategic_intent_delta,
                "convergence_metric": convergence_metric,
                "collection_multiplier_prev_mean": float(collection_multiplier_prev.mean()),
                "collection_multiplier_target_mean": float(collection_multiplier_target.mean()),
                "collection_multiplier_next_mean": float(collection_multiplier_next.mean()),
                "collection_rate_effective_mean": float(collection_rate_it.mean()),
                "strategic_fill_intent_mean": float(np.mean(strategic_fill_intent_it)),
                "strategic_release_intent_mean": float(np.mean(strategic_release_intent_it)),
                "sd_scarcity_multiplier_effective_mean": float(np.mean(sd_scarcity_multiplier_effective)),
                "sd_capacity_envelope_mean": float(np.mean(sd_capacity_envelope)),
                "sd_flow_utilization_mean": float(np.mean(sd_flow_utilization)),
                "sd_bottleneck_pressure_mean": float(np.mean(sd_bottleneck_pressure)),
                "sd_collection_bottleneck_throttle_mean": float(np.mean(sd_collection_bottleneck_throttle)),
                "feedback_signal_mode": feedback_signal_mode,
                "feedback_on_report_years_only": bool(feedback_on_report_years_only),
                "coupling_tolerance": float(tol),
                "converged": converged,
            }
        )

        for y_idx, y in enumerate(years):
            signal_trace_rows.append(
                {
                    "iteration": int(it + 1),
                    "year": int(y),
                    "service_stress_year": float(service_stress_year[y_idx]),
                    "circular_supply_stress_year": float(circular_supply_stress_year[y_idx]),
                    "strategic_stock_coverage_year": float(strategic_stock_coverage_year[y_idx]),
                    "service_stress_eval": float(service_stress_target[y_idx]),
                    "circular_supply_stress_eval": float(circular_supply_stress_target[y_idx]),
                    "strategic_stock_coverage_eval": float(strategic_stock_coverage_target[y_idx]),
                    "service_stress_signal_prev": float(service_signal_prev[y_idx]),
                    "service_stress_signal_target": float(service_stress_target[y_idx]),
                    "service_stress_signal_next": float(service_stress_new[y_idx]),
                    "service_stress_residual_lag": float(service_residual_lag[y_idx]),
                    "circular_supply_stress_signal_prev": float(circular_signal_prev[y_idx]),
                    "circular_supply_stress_signal_target": float(circular_supply_stress_target[y_idx]),
                    "circular_supply_stress_signal_next": float(circular_supply_stress_new[y_idx]),
                    "circular_supply_stress_residual_lag": float(circular_residual_lag[y_idx]),
                    "strategic_stock_coverage_signal_prev": float(strategic_signal_prev[y_idx]),
                    "strategic_stock_coverage_signal_target": float(strategic_stock_coverage_target[y_idx]),
                    "strategic_stock_coverage_signal_next": float(strategic_stock_coverage_new[y_idx]),
                    "strategic_stock_coverage_residual_lag": float(strategic_residual_lag[y_idx]),
                    "stress_multiplier_prev": float(stress_multiplier_prev[y_idx]),
                    "stress_multiplier_next": float(stress_multiplier_new[y_idx]),
                    "max_signal_delta": max_signal_delta,
                    "collection_multiplier_prev": float(collection_multiplier_prev[y_idx]),
                    "collection_multiplier_target": float(collection_multiplier_target[y_idx]),
                    "collection_multiplier_next": float(collection_multiplier_next[y_idx]),
                    "collection_multiplier_residual_lag": float(
                        collection_multiplier_target[y_idx] - collection_multiplier_next[y_idx]
                    ),
                    "collection_rate_effective": float(collection_rate_it[y_idx]),
                    "collection_multiplier_delta": collection_multiplier_delta,
                    "strategic_fill_intent": float(strategic_fill_intent_it[y_idx]),
                    "strategic_release_intent": float(strategic_release_intent_it[y_idx]),
                    "strategic_intent_delta": strategic_intent_delta,
                    "sd_scarcity_multiplier_effective": float(sd_scarcity_multiplier_effective[y_idx]),
                    "sd_capacity_envelope": float(sd_capacity_envelope[y_idx]),
                    "sd_flow_utilization": float(sd_flow_utilization[y_idx]),
                    "sd_bottleneck_pressure": float(sd_bottleneck_pressure[y_idx]),
                    "sd_collection_bottleneck_throttle": float(sd_collection_bottleneck_throttle[y_idx]),
                    "convergence_metric": convergence_metric,
                    "feedback_signal_mode": feedback_signal_mode,
                    "feedback_on_report_years_only": bool(feedback_on_report_years_only),
                    "converged": converged,
                }
            )

        if converged:
            service_stress_signal = service_stress_new
            circular_supply_stress_signal = circular_supply_stress_new
            strategic_stock_coverage_signal = strategic_stock_coverage_new
            strategic_fill_intent_prev = strategic_fill_intent_it
            strategic_release_intent_prev = strategic_release_intent_it
            break
        service_stress_signal = service_stress_new
        circular_supply_stress_signal = circular_supply_stress_new
        strategic_stock_coverage_signal = strategic_stock_coverage_new
        collection_multiplier_prev = collection_multiplier_next
        strategic_fill_intent_prev = strategic_fill_intent_it
        strategic_release_intent_prev = strategic_release_intent_it

    assert last_sd is not None and last_mfa is not None

    # --- time-series indicators ---
    ind_eol_rr = end_of_life_recycling_rate(last_mfa.eol_recycled, last_mfa.eol_generated).series
    total_input = last_mfa.primary_supply + last_mfa.secondary_supply
    ind_rir = recycling_input_rate(last_mfa.secondary_supply, total_input).series

    ind_unmet = unmet_service(last_mfa.service_demand, last_mfa.delivered_service).series
    ind_service_level = service_level(last_mfa.service_demand, last_mfa.delivered_service).series
    ind_service_deficit = service_deficit(ind_service_level, baseline=1.0).series

    final_service_signal_series = pd.Series(service_stress_signal, index=years)
    final_circular_signal_series = pd.Series(circular_supply_stress_signal, index=years)
    final_strategic_coverage_signal_series = pd.Series(strategic_stock_coverage_signal, index=years)
    final_stress_multiplier = _stress_multiplier(service_stress_signal, circular_supply_stress_signal)

    indicators_ts = {
        # MFA state & flow series
        "Stock_in_use": last_mfa.stock_in_use,
        "Inflow_to_use_total": last_mfa.inflow_to_use_total,
        "Inflow_to_use_new": last_mfa.inflow_to_use_new,
        "Inflow_to_use_reman": last_mfa.inflow_to_use_reman,
        "Outflow_from_use": last_mfa.outflow_from_use,
        "Primary_supply": last_mfa.primary_supply,
        "Primary_refined_net_imports": last_mfa.primary_refined_net_imports,
        "Primary_available_to_refining": last_mfa.primary_available_to_refining,
        "Secondary_supply": last_mfa.secondary_supply,
        "EoL_generated": last_mfa.eol_generated,
        "EoL_collected": last_mfa.eol_collected,
        "Collection_rate_effective": (
            last_mfa.eol_collected / last_mfa.eol_generated.replace(0, np.nan)
        ).fillna(0.0),
        "EoL_recycled": last_mfa.eol_recycled,
        "EoL_remanufactured": last_mfa.eol_remanufactured,
        "EoL_disposal": last_mfa.eol_disposal,
        "EoL_uncollected": last_mfa.eol_uncollected,

        "Fabrication_losses": last_mfa.fabrication_losses,
        "New_scrap_generated": last_mfa.new_scrap_generated,
        "New_scrap_to_secondary": last_mfa.new_scrap_to_secondary,
        "New_scrap_to_residue": last_mfa.new_scrap_to_residue,
        "Old_scrap_generated": last_mfa.old_scrap_generated,
        "Old_scrap_collected": last_mfa.old_scrap_collected,
        "Old_scrap_uncollected": last_mfa.old_scrap_uncollected,

        "Recycling_process_losses": last_mfa.recycling_process_losses,
        "Recycling_surplus_unused": last_mfa.recycling_surplus_unused,
        "Refinery_stockpile_inflow": last_mfa.refinery_stockpile_inflow,
        "Refinery_stockpile_outflow": last_mfa.refinery_stockpile_outflow,
        "Refinery_stockpile_stock": last_mfa.refinery_stockpile_stock,
        "Strategic_inventory_inflow": last_mfa.strategic_inventory_inflow,
        "Strategic_inventory_outflow": last_mfa.strategic_inventory_outflow,
        "Strategic_inventory_stock": last_mfa.strategic_inventory_stock,
        "Strategic_stock_coverage_years": last_mfa.strategic_stock_coverage_years,
        "Strategic_fill_intent": pd.Series(final_strategic_fill_intent, index=years),
        "Strategic_release_intent": pd.Series(final_strategic_release_intent, index=years),

        "Remanufacture_process_losses": last_mfa.remanufacture_process_losses,
        "Remanufacture_surplus_unused": last_mfa.remanufacture_surplus_unused,
        "Extraction_losses": last_mfa.extraction_losses,
        "Beneficiation_losses": last_mfa.beneficiation_losses,
        "Refining_losses": last_mfa.refining_losses,
        "Sorting_rejects_to_disposal": last_mfa.sorting_rejects_to_disposal,
        "Sorting_rejects_to_sysenv": last_mfa.sorting_rejects_to_sysenv,
        "Mass_balance_residual_max_abs": last_mfa.mass_balance_residual_max_abs,

        # Circularity ratios
        "EoL_RR": ind_eol_rr,
        "RIR": ind_rir,

        # Service series
        "Service_demand": last_mfa.service_demand,
        "Delivered_service": last_mfa.delivered_service,
        "Unmet_service": ind_unmet,
        "Service_level": ind_service_level,
        "Service_deficit": ind_service_deficit,
        "Coupling_service_stress": (last_mfa.unmet_service / last_mfa.service_demand.replace(0, np.nan)).fillna(0.0),
        "Coupling_circular_supply_stress": (
            1.0
            - (last_mfa.secondary_supply / (last_mfa.primary_supply + last_mfa.secondary_supply).replace(0, np.nan)).fillna(0.0)
        ).clip(lower=0.0, upper=1.0),
        "Coupling_service_stress_signal": final_service_signal_series,
        "Coupling_circular_supply_stress_signal": final_circular_signal_series,
        "Coupling_strategic_stock_coverage_signal": final_strategic_coverage_signal_series,
        "Coupling_stress_multiplier": pd.Series(final_stress_multiplier, index=years),
        "Coupling_collection_multiplier": pd.Series(final_collection_multiplier, index=years),

        # SD state series (useful for debugging)
        "SD_price": last_sd.price,
        "SD_demand_realized": last_sd.demand,
        "SD_scarcity_multiplier_effective": last_sd.scarcity_multiplier_effective,
        "SD_capacity_envelope": last_sd.capacity_envelope,
        "SD_flow_utilization": last_sd.flow_utilization,
        "SD_bottleneck_pressure": last_sd.bottleneck_pressure,
        "SD_collection_bottleneck_throttle": last_sd.collection_bottleneck_throttle,
    }
    # --- scalar resilience metrics ---
    # Compute scalar resilience metrics over the *reporting window* if provided,
    # otherwise over the full simulated horizon.
    sl_for_scalars = ind_service_level
    rep_years = sd_params_it.get("report_years")
    if isinstance(rep_years, (list, tuple)) and rep_years:
        years_keep = [y for y in rep_years if y in sl_for_scalars.index]
        if years_keep:
            sl_for_scalars = sl_for_scalars.loc[years_keep]

    indicators_scalar = {
        "Resilience_triangle_area": float(resilience_triangle_area(sl_for_scalars, baseline=1.0).value),
        "Years_below_service_threshold": float(
            years_below_service_threshold(sl_for_scalars, threshold=float(service_level_threshold)).value
        ),
        "Max_consecutive_years_below_threshold": float(
            max_consecutive_years_below_threshold(sl_for_scalars, threshold=float(service_level_threshold)).value
        ),
    }

    return CoupledRunResult(
        sd=last_sd,
        mfa=last_mfa,
        indicators_ts=indicators_ts,
        indicators_scalar=indicators_scalar,
        coupling_signals_iter_year=pd.DataFrame(signal_trace_rows),
        coupling_convergence_iter=pd.DataFrame(convergence_rows),
        meta={
            "iterations": it + 1,
            "coupling_converged": converged,
            "coupling_convergence_metric": float(last_max_signal_delta),
            "coupling_tolerance": float(tol),
            "coupling_smoothing": float(np.mean(coupling_signal_smoothing_ts)),
            "coupling_interface_registry": "crm_model.coupling.interface",
            "coupling_feedback_signal_mode": feedback_signal_mode,
            "coupling_feedback_on_report_years_only": bool(feedback_on_report_years_only),
            "final_service_stress_signal": float(np.mean(service_stress_signal)),
            "final_circular_supply_stress_signal": float(np.mean(circular_supply_stress_signal)),
            "final_strategic_stock_coverage_signal": float(np.mean(strategic_stock_coverage_signal)),
            "final_stress_multiplier": float(np.mean(final_stress_multiplier)),
            "final_collection_multiplier_mean": float(np.mean(final_collection_multiplier)),
            "final_collection_rate_mean": float(np.mean(final_collection_rate)),
            "final_scarcity_multiplier_effective_mean": float(np.mean(last_sd.scarcity_multiplier_effective.values)),
            "final_capacity_envelope_mean": float(np.mean(last_sd.capacity_envelope.values)),
            "final_flow_utilization_mean": float(np.mean(last_sd.flow_utilization.values)),
            "final_bottleneck_pressure_mean": float(np.mean(last_sd.bottleneck_pressure.values)),
            "final_collection_bottleneck_throttle_mean": float(
                np.mean(last_sd.collection_bottleneck_throttle.values)
            ),
            "final_strategic_fill_intent_mean": float(np.mean(final_strategic_fill_intent)),
            "final_strategic_release_intent_mean": float(np.mean(final_strategic_release_intent)),
            "strategic_reserve_enabled": bool(np.any(strategic_reserve_enabled_ts > 0.5)),
            "material": material,
            "region": region,
        },
    )
