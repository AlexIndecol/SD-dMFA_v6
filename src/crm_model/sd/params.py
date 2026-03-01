from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple
import warnings

import numpy as np

SD_ALIAS_MAP: Dict[str, str] = {
    "base_price": "price_base",
    "scarcity_sensitivity": "price_scarcity_sensitivity",
    "price_elasticity": "demand_price_elasticity",
    "service_stress_gain": "coupling_service_stress_gain",
    "circular_supply_stress_gain": "coupling_circular_supply_stress_gain",
    "scarcity_smooth": "coupling_signal_smoothing",
}

LEGACY_STRATEGY_TO_SD_MAP: Dict[str, str] = {
    "collection_multiplier_min": "collection_multiplier_min",
    "collection_multiplier_max": "collection_multiplier_max",
    "collection_multiplier_lag_years": "collection_multiplier_lag_years",
}

SD_HETEROGENEITY_ALLOWLIST: set[str] = {
    "price_base",
    "price_scarcity_sensitivity",
    "demand_price_elasticity",
    "coupling_service_stress_gain",
    "coupling_circular_supply_stress_gain",
    "coupling_signal_smoothing",
    "coupling_signal_smoothing_strategic",
    "service_stress_signal_cap",
    "coupling_stress_multiplier_cap",
    "collection_price_response_gain",
    "collection_multiplier_min",
    "collection_multiplier_max",
    "collection_multiplier_lag_years",
    "capacity_envelope_initial",
    "capacity_envelope_min",
    "capacity_envelope_max",
    "capacity_expansion_gain",
    "capacity_retirement_gain",
    "capacity_adjustment_lag_years",
    "capacity_pressure_shortage_weight",
    "bottleneck_scarcity_gain",
    "bottleneck_collection_sensitivity",
}


def _context_prefix(context: str | None) -> str:
    if not context:
        return ""
    return f"{context}: "


def canonical_sd_key(key: str) -> str:
    key_s = str(key)
    if key_s in SD_ALIAS_MAP:
        canonical = SD_ALIAS_MAP[key_s]
        raise ValueError(
            f"sd_parameters.{key_s} is no longer supported; use sd_parameters.{canonical}."
        )
    return key_s


def normalize_sd_parameters(
    sd_parameters: Mapping[str, Any] | None,
    *,
    emit_warnings: bool = False,
    context: str | None = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for raw_key, value in (sd_parameters or {}).items():
        key = str(raw_key)
        canonical = canonical_sd_key(key)
        out[canonical] = value
    return out


def migrate_legacy_strategy_sd_controls(
    *,
    sd_parameters: Mapping[str, Any] | None,
    strategy: Mapping[str, Any] | None,
    emit_warnings: bool = False,
    context: str | None = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    sd_out = dict(sd_parameters or {})
    strategy_out = dict(strategy or {})
    offenders = [k for k in LEGACY_STRATEGY_TO_SD_MAP.keys() if k in strategy_out]
    if offenders:
        joined = ", ".join([f"strategy.{k}" for k in offenders])
        raise ValueError(
            f"{_context_prefix(context)}legacy strategy collection controls are no longer supported: {joined}. "
            "Set the same keys under sd_parameters instead."
        )
    for strategy_key, sd_key in LEGACY_STRATEGY_TO_SD_MAP.items():
        if strategy_key not in strategy_out:
            continue
        # kept for interface stability; this loop is currently unreachable due to strict offender check above.
        if sd_key not in sd_out:
            sd_out[sd_key] = strategy_out[strategy_key]
    return sd_out, strategy_out


def is_year_gate(value: Any) -> bool:
    return isinstance(value, dict) and "start_year" in value and "value" in value


def is_ramp_points(value: Any) -> bool:
    return isinstance(value, dict) and "points" in value


def _parse_ramp_points(*, points: Any, name: str) -> tuple[np.ndarray, np.ndarray]:
    if isinstance(points, Mapping):
        items = []
        for k, v in points.items():
            items.append((int(k), float(v)))
    elif isinstance(points, Sequence) and not isinstance(points, (str, bytes)):
        items = []
        for row in points:
            if not isinstance(row, Mapping) or "year" not in row or "value" not in row:
                raise ValueError(
                    f"{name}.points list items must be mappings with 'year' and 'value'."
                )
            items.append((int(row["year"]), float(row["value"])))
    else:
        raise ValueError(
            f"{name}.points must be a mapping {{year: value}} or a list of {{year, value}} mappings."
        )
    if not items:
        raise ValueError(f"{name}.points must not be empty.")
    items = sorted(items, key=lambda kv: kv[0])
    years = np.array([int(y) for y, _ in items], dtype=float)
    values = np.array([float(v) for _, v in items], dtype=float)
    if np.unique(years).size != years.size:
        raise ValueError(f"{name}.points contains duplicate years.")
    return years, values


def inject_gate_before(value: Any, baseline: Any) -> Any:
    if not is_year_gate(value):
        return value
    if "before" in value or baseline is None:
        return value
    out = dict(value)
    out["before"] = baseline
    return out


def expand_temporal_value(
    value: Any,
    *,
    years: Sequence[int],
    name: str,
    default: float | None = None,
    report_start_year: int | None = None,
    emit_warnings: bool = False,
    context: str | None = None,
) -> np.ndarray:
    n_years = len(years)
    if is_ramp_points(value):
        interpolation = str(value.get("interpolation", "linear")).strip().lower()
        if interpolation != "linear":
            raise ValueError(
                f"{name}.interpolation must be 'linear'; got {interpolation!r}."
            )
        x, y = _parse_ramp_points(points=value.get("points"), name=name)
        if report_start_year is not None and int(np.min(x)) < int(report_start_year) and emit_warnings:
            warnings.warn(
                (
                    f"{_context_prefix(context)}{name} points start at year {int(np.min(x))}, before "
                    f"report_start_year={int(report_start_year)}."
                ),
                DeprecationWarning,
                stacklevel=2,
            )
        xq = np.array([int(yy) for yy in years], dtype=float)
        yq = np.interp(xq, x, y, left=float(y[0]), right=float(y[-1]))
        before_value = value.get("before", None)
        if before_value is None:
            return np.array(yq, dtype=float)
        before_ts = expand_temporal_value(
            before_value,
            years=years,
            name=f"{name}.before",
            default=default,
            report_start_year=report_start_year,
            emit_warnings=emit_warnings,
            context=context,
        )
        out = before_ts.copy()
        start_year = int(np.min(x))
        for i, yy in enumerate(years):
            if int(yy) >= start_year:
                out[i] = float(yq[i])
        return out

    if is_year_gate(value):
        start_year = int(value["start_year"])
        if report_start_year is not None and start_year < int(report_start_year) and emit_warnings:
            warnings.warn(
                (
                    f"{_context_prefix(context)}{name} start_year={start_year} is before "
                    f"report_start_year={int(report_start_year)}. Historic-phase SD gates are "
                    "allowed in this release but will be enforced later."
                ),
                DeprecationWarning,
                stacklevel=2,
            )
        before_value = value.get("before", default)
        gate_ts = expand_temporal_value(
            value["value"],
            years=years,
            name=f"{name}.value",
            default=default,
            report_start_year=report_start_year,
            emit_warnings=emit_warnings,
            context=context,
        )
        if all(int(y) >= start_year for y in years):
            return gate_ts
        if before_value is None:
            raise ValueError(
                f"{name} gate is missing 'before' and no default baseline is available."
            )
        before_ts = expand_temporal_value(
            before_value,
            years=years,
            name=f"{name}.before",
            default=default,
            report_start_year=report_start_year,
            emit_warnings=emit_warnings,
            context=context,
        )
        out = before_ts.copy()
        for i, y in enumerate(years):
            if int(y) >= start_year:
                out[i] = gate_ts[i]
        return out

    if value is None:
        if default is None:
            raise ValueError(f"Missing required parameter '{name}'.")
        return np.array([float(default)] * n_years, dtype=float)
    if isinstance(value, (list, tuple, np.ndarray)):
        arr = np.array(value, dtype=float).reshape(-1)
        if arr.size != n_years:
            raise ValueError(f"{name} must have length {n_years}; got {arr.size}.")
        return arr
    try:
        return np.array([float(value)] * n_years, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{name} must be a scalar, year-gate mapping, ramp-points mapping, or length-{n_years} timeseries."
        ) from exc


def validate_temporal_shape_and_bounds(
    *,
    key: str,
    value: Any,
    years: Sequence[int] | None = None,
    default: float | None = None,
    lower: float | None = None,
    upper: float | None = None,
    strict_lower: bool = False,
    strict_upper: bool = False,
    report_start_year: int | None = None,
    emit_warnings: bool = False,
    context: str | None = None,
) -> np.ndarray | None:
    if years is None:
        values = list(_iter_numeric_values(value))
        if values:
            _validate_bounds(
                key=key,
                values=values,
                lower=lower,
                upper=upper,
                strict_lower=strict_lower,
                strict_upper=strict_upper,
            )
        return None

    arr = expand_temporal_value(
        value,
        years=years,
        name=f"sd_parameters.{key}",
        default=default,
        report_start_year=report_start_year,
        emit_warnings=emit_warnings,
        context=context,
    )
    _validate_bounds(
        key=key,
        values=arr,
        lower=lower,
        upper=upper,
        strict_lower=strict_lower,
        strict_upper=strict_upper,
    )
    return arr


def _iter_numeric_values(value: Any) -> Iterable[float]:
    if is_ramp_points(value):
        _, vals = _parse_ramp_points(points=value.get("points"), name="ramp")
        for v in vals:
            yield float(v)
        before_value = value.get("before")
        if before_value is not None:
            yield from _iter_numeric_values(before_value)
        return
    if is_year_gate(value):
        before_value = value.get("before")
        if before_value is not None:
            yield from _iter_numeric_values(before_value)
        yield from _iter_numeric_values(value.get("value"))
        return
    if isinstance(value, (list, tuple, np.ndarray)):
        arr = np.array(value, dtype=float).reshape(-1)
        for x in arr:
            yield float(x)
        return
    if isinstance(value, (int, float, np.integer, np.floating)):
        yield float(value)


def _as_optional_array(value: Any) -> np.ndarray | None:
    if value is None or is_year_gate(value):
        return None
    if isinstance(value, (list, tuple, np.ndarray)):
        return np.array(value, dtype=float).reshape(-1)
    if isinstance(value, (int, float, np.integer, np.floating)):
        return np.array([float(value)], dtype=float)
    return None


def _validate_bounds(
    *,
    key: str,
    values: Iterable[float],
    lower: float | None = None,
    upper: float | None = None,
    strict_lower: bool = False,
    strict_upper: bool = False,
) -> None:
    for v in values:
        if lower is not None:
            if strict_lower and not (v > lower):
                op = ">"
                raise ValueError(f"sd_parameters.{key} must be {op} {lower}; got {v}.")
            if (not strict_lower) and not (v >= lower):
                op = ">="
                raise ValueError(f"sd_parameters.{key} must be {op} {lower}; got {v}.")
        if upper is not None:
            if strict_upper and not (v < upper):
                op = "<"
                raise ValueError(f"sd_parameters.{key} must be {op} {upper}; got {v}.")
            if (not strict_upper) and not (v <= upper):
                op = "<="
                raise ValueError(f"sd_parameters.{key} must be {op} {upper}; got {v}.")


def validate_sd_parameter_ranges(
    sd_parameters: Mapping[str, Any] | None,
    *,
    years: Sequence[int] | None = None,
    report_start_year: int | None = None,
    emit_warnings: bool = False,
    context: str | None = None,
) -> None:
    params = dict(sd_parameters or {})

    checks = [
        ("price_base", {"lower": 0.0, "strict_lower": True}),
        ("price_scarcity_sensitivity", {"lower": 0.0}),
        ("demand_price_elasticity", {"lower": 0.0}),
        ("coupling_service_stress_gain", {"lower": 0.0}),
        ("coupling_circular_supply_stress_gain", {"lower": 0.0}),
        ("coupling_signal_smoothing", {"lower": 0.0, "upper": 1.0}),
        ("coupling_signal_smoothing_strategic", {"lower": 0.0, "upper": 1.0}),
        ("service_stress_signal_cap", {"lower": 0.0, "upper": 1.0}),
        ("coupling_stress_multiplier_cap", {"lower": 0.0, "strict_lower": True}),
        ("collection_price_response_gain", {"lower": 0.0}),
        ("collection_multiplier_min", {"lower": 0.0}),
        ("collection_multiplier_max", {"lower": 0.0, "strict_lower": True}),
        ("collection_multiplier_lag_years", {"lower": 0.0}),
        ("capacity_envelope_initial", {"lower": 0.0, "strict_lower": True}),
        ("capacity_envelope_min", {"lower": 0.0, "strict_lower": True}),
        ("capacity_envelope_max", {"lower": 0.0, "strict_lower": True}),
        ("capacity_expansion_gain", {"lower": 0.0}),
        ("capacity_retirement_gain", {"lower": 0.0}),
        ("capacity_adjustment_lag_years", {"lower": 0.0}),
        ("capacity_pressure_shortage_weight", {"lower": 0.0, "upper": 1.0}),
        ("bottleneck_scarcity_gain", {"lower": 0.0}),
        ("bottleneck_collection_sensitivity", {"lower": 0.0}),
    ]
    expanded: Dict[str, np.ndarray] = {}

    for key, kwargs in checks:
        if key not in params:
            continue
        arr = validate_temporal_shape_and_bounds(
            key=key,
            value=params[key],
            years=years,
            report_start_year=report_start_year,
            emit_warnings=emit_warnings,
            context=context,
            **kwargs,
        )
        if arr is not None:
            expanded[key] = arr

    if years is not None:
        min_arr = expanded.get("collection_multiplier_min")
        max_arr = expanded.get("collection_multiplier_max")
        if min_arr is not None and max_arr is not None and (min_arr > max_arr).any():
            raise ValueError("sd_parameters.collection_multiplier_min must be <= collection_multiplier_max.")
    else:
        min_arr = _as_optional_array(params.get("collection_multiplier_min"))
        max_arr = _as_optional_array(params.get("collection_multiplier_max"))
        if min_arr is not None and max_arr is not None:
            if min_arr.size == 1 and max_arr.size > 1:
                min_arr = np.full(max_arr.size, float(min_arr[0]), dtype=float)
            if max_arr.size == 1 and min_arr.size > 1:
                max_arr = np.full(min_arr.size, float(max_arr[0]), dtype=float)
            if min_arr.size == max_arr.size and (min_arr > max_arr).any():
                raise ValueError("sd_parameters.collection_multiplier_min must be <= collection_multiplier_max.")

    if years is not None:
        env_min = expanded.get("capacity_envelope_min")
        env_max = expanded.get("capacity_envelope_max")
        if env_min is not None and env_max is not None and (env_min > env_max).any():
            raise ValueError("sd_parameters.capacity_envelope_min must be <= capacity_envelope_max.")
    else:
        env_min = _as_optional_array(params.get("capacity_envelope_min"))
        env_max = _as_optional_array(params.get("capacity_envelope_max"))
        if env_min is not None and env_max is not None:
            if env_min.size == 1 and env_max.size > 1:
                env_min = np.full(env_max.size, float(env_min[0]), dtype=float)
            if env_max.size == 1 and env_min.size > 1:
                env_max = np.full(env_min.size, float(env_max[0]), dtype=float)
            if env_min.size == env_max.size and (env_min > env_max).any():
                raise ValueError("sd_parameters.capacity_envelope_min must be <= capacity_envelope_max.")


def normalize_and_validate_sd_parameters(
    sd_parameters: Mapping[str, Any] | None,
    *,
    years: Sequence[int] | None = None,
    report_start_year: int | None = None,
    emit_warnings: bool = False,
    context: str | None = None,
) -> Dict[str, Any]:
    out = normalize_sd_parameters(sd_parameters, emit_warnings=emit_warnings, context=context)
    validate_sd_parameter_ranges(
        out,
        years=years,
        report_start_year=report_start_year,
        emit_warnings=emit_warnings,
        context=context,
    )
    return out


def validate_sd_heterogeneity_rule_keys(
    sd_parameters: Mapping[str, Any] | None,
    *,
    context: str | None = None,
) -> None:
    params = normalize_sd_parameters(sd_parameters, emit_warnings=False, context=context)
    unknown = sorted([k for k in params.keys() if k not in SD_HETEROGENEITY_ALLOWLIST])
    if unknown:
        raise ValueError(
            f"{_context_prefix(context)}unsupported sd_heterogeneity keys: {unknown}. "
            f"Allowed keys: {sorted(SD_HETEROGENEITY_ALLOWLIST)}."
        )


__all__ = [
    "SD_ALIAS_MAP",
    "LEGACY_STRATEGY_TO_SD_MAP",
    "SD_HETEROGENEITY_ALLOWLIST",
    "canonical_sd_key",
    "is_year_gate",
    "inject_gate_before",
    "expand_temporal_value",
    "validate_temporal_shape_and_bounds",
    "normalize_sd_parameters",
    "migrate_legacy_strategy_sd_controls",
    "validate_sd_parameter_ranges",
    "normalize_and_validate_sd_parameters",
    "validate_sd_heterogeneity_rule_keys",
]
