from __future__ import annotations

from typing import Any, Dict, Sequence, Tuple

import numpy as np
from crm_model.sd.params import (
    expand_temporal_value,
    inject_gate_before,
    is_year_gate,
    normalize_sd_parameters,
    validate_sd_heterogeneity_rule_keys,
    validate_sd_parameter_ranges,
)


def deep_update(base: Dict[str, Any], upd: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in upd.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_update(out[k], v)
        else:
            out[k] = v
    return out


def _event_to_dict(event: Any) -> Dict[str, Any] | None:
    if event is None:
        return None
    if isinstance(event, dict):
        return event
    if hasattr(event, "model_dump"):
        return event.model_dump(exclude_none=True)
    raise ValueError(f"Unsupported shock event type: {type(event)}")


def _to_plain_mapping(node: Any) -> Dict[str, Any]:
    if node is None:
        return {}
    if isinstance(node, dict):
        return node
    if hasattr(node, "model_dump"):
        return node.model_dump(exclude_none=True, exclude_unset=True)
    raise ValueError(f"Unsupported mapping type: {type(node)}")


def _is_year_gate(value: Any) -> bool:
    return is_year_gate(value)


def _gate_with_before(value: Any, before: Any) -> Any:
    if is_year_gate(value):
        return inject_gate_before(value, before)
    if isinstance(value, dict) and "points" in value and "before" not in value:
        out = dict(value)
        out["before"] = before
        return out
    return value


def inject_gate_baselines(
    *,
    overrides: Dict[str, Any],
    primary_base: Dict[str, Any] | None,
    secondary_base: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in (overrides or {}).items():
        primary_val = primary_base.get(key) if isinstance(primary_base, dict) else None
        secondary_val = secondary_base.get(key) if isinstance(secondary_base, dict) else None
        if _is_year_gate(value):
            if "before" in value:
                out[key] = value
            else:
                baseline = primary_val if primary_val is not None else secondary_val
                out[key] = _gate_with_before(value, baseline) if baseline is not None else value
            continue
        if isinstance(value, dict):
            out[key] = inject_gate_baselines(
                overrides=value,
                primary_base=primary_val if isinstance(primary_val, dict) else {},
                secondary_base=secondary_val if isinstance(secondary_val, dict) else {},
            )
            continue
        out[key] = value
    return out


def _as_timeseries(
    value: Any,
    *,
    years: Sequence[int],
    name: str,
    default: float | None = None,
) -> np.ndarray:
    return expand_temporal_value(value, years=years, name=name, default=default)


def _shock_multiplier_series(years: Sequence[int], event: Dict[str, Any]) -> np.ndarray:
    start_year = int(event["start_year"])
    duration = int(event["duration_years"])
    multiplier = float(event["multiplier"])
    if duration < 0:
        raise ValueError(f"duration_years must be >= 0 for shock event; got {duration}")

    mult = np.ones(len(years), dtype=float)
    end_year = start_year + duration
    for i, y in enumerate(years):
        if start_year <= int(y) < end_year:
            mult[i] = multiplier
    return mult


def _matches_scope(
    *,
    material: str,
    region: str,
    materials: Sequence[str] | None,
    regions: Sequence[str] | None,
) -> bool:
    mat_ok = True
    reg_ok = True
    if materials:
        mat_ok = material.lower() in {str(m).lower() for m in materials}
    if regions:
        reg_ok = region.lower() in {str(r).lower() for r in regions}
    return mat_ok and reg_ok


def resolve_variant_slice_overrides(
    *,
    cfg,
    variant_name: str,
    material: str,
    region: str,
) -> Dict[str, Dict[str, Any]]:
    variant = cfg.variants[variant_name]
    sd_base = normalize_sd_parameters(
        getattr(cfg, "sd_parameters", {}) or {},
        emit_warnings=True,
        context="run sd_parameters",
    )
    variant_sd = normalize_sd_parameters(
        variant.sd_parameters or {},
        emit_warnings=True,
        context=f"variant '{variant_name}'",
    )
    out = {
        "sd_parameters": inject_gate_baselines(
            overrides=variant_sd,
            primary_base=sd_base,
        ),
        "mfa_parameters": (variant.mfa_parameters or {}),
        "strategy": _to_plain_mapping(variant.strategy),
        "transition_policy": _to_plain_mapping(getattr(variant, "transition_policy", None)),
        "demand_transformation": _to_plain_mapping(getattr(variant, "demand_transformation", None)),
        "shocks": _to_plain_mapping(variant.shocks),
    }

    for ov in variant.dimension_overrides:
        if not _matches_scope(
            material=material,
            region=region,
            materials=ov.materials,
            regions=ov.regions,
        ):
            continue
        if ov.sd_parameters:
            ov_sd = normalize_sd_parameters(
                ov.sd_parameters,
                emit_warnings=True,
                context=f"variant '{variant_name}' dimension_overrides",
            )
            out["sd_parameters"] = deep_update(
                out["sd_parameters"],
                inject_gate_baselines(
                    overrides=ov_sd,
                    primary_base=out["sd_parameters"],
                    secondary_base=sd_base,
                ),
            )
        if ov.mfa_parameters:
            out["mfa_parameters"] = deep_update(out["mfa_parameters"], ov.mfa_parameters)
        if ov.strategy:
            out["strategy"] = deep_update(
                out["strategy"],
                _to_plain_mapping(ov.strategy),
            )
        if ov.transition_policy:
            out["transition_policy"] = deep_update(
                out["transition_policy"],
                _to_plain_mapping(ov.transition_policy),
            )
        if ov.demand_transformation:
            out["demand_transformation"] = deep_update(
                out["demand_transformation"],
                _to_plain_mapping(ov.demand_transformation),
            )
        if ov.shocks:
            out["shocks"] = deep_update(
                out["shocks"],
                _to_plain_mapping(ov.shocks),
            )
    return out


def resolve_sd_parameters_for_slice(
    *,
    sd_base: Dict[str, Any],
    sd_heterogeneity: Sequence[Any],
    material: str,
    region: str,
) -> Dict[str, Any]:
    """Apply top-level SD heterogeneity rules for a material-region slice.

    Rules are applied in order; later matches override earlier values.
    """
    out = normalize_sd_parameters(sd_base, emit_warnings=True, context="run sd_parameters")
    for rule in sd_heterogeneity or []:
        if isinstance(rule, dict):
            materials = rule.get("materials")
            regions = rule.get("regions")
            sd_params = rule.get("sd_parameters") or {}
            rule_name = str(rule.get("name") or "")
        else:
            materials = getattr(rule, "materials", None)
            regions = getattr(rule, "regions", None)
            sd_params = getattr(rule, "sd_parameters", {}) or {}
            rule_name = str(getattr(rule, "name", "") or "")
        if not _matches_scope(material=material, region=region, materials=materials, regions=regions):
            continue
        rule_context = f"sd_heterogeneity rule '{rule_name}'" if rule_name else "sd_heterogeneity rule"
        sd_params_norm = normalize_sd_parameters(
            sd_params,
            emit_warnings=True,
            context=rule_context,
        )
        validate_sd_heterogeneity_rule_keys(sd_params_norm, context=rule_context)
        out = deep_update(out, sd_params_norm)
    validate_sd_parameter_ranges(out)
    return out


def apply_series_shock(
    *,
    series_tr: np.ndarray,
    years: Sequence[int],
    shocks: Dict[str, Any],
    shock_name: str,
) -> np.ndarray:
    event = _event_to_dict(shocks.get(shock_name))
    if event is None:
        return np.array(series_tr, dtype=float)
    mult = _shock_multiplier_series(years, event)
    return np.array(series_tr, dtype=float) * mult[:, None]


def resolve_routing_rates(
    *,
    years: Sequence[int],
    strategy: Dict[str, Any],
    params: Dict[str, Any],
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    reman_baseline = params.get("remanufacturing_rate", params.get("remanufacture_share", 0.0))
    if "remanufacturing_rate" in strategy:
        reman_rate = _gate_with_before(strategy.get("remanufacturing_rate"), reman_baseline)
    elif "remanufacture_share" in strategy:
        reman_rate = _gate_with_before(strategy.get("remanufacture_share"), reman_baseline)
    else:
        reman_rate = reman_baseline

    rec_baseline = params.get("recycling_rate")
    rec_rate = (
        _gate_with_before(strategy.get("recycling_rate"), rec_baseline)
        if "recycling_rate" in strategy
        else rec_baseline
    )

    disp_baseline = params.get("disposal_rate")
    disp_rate = (
        _gate_with_before(strategy.get("disposal_rate"), disp_baseline)
        if "disposal_rate" in strategy
        else disp_baseline
    )

    reman_ts = _as_timeseries(reman_rate, years=years, name="remanufacturing_rate", default=0.0)

    rec_default = None
    disp_default = None
    if rec_rate is None and disp_rate is None:
        rec_default = 1.0
        disp_default = 0.0
    elif rec_rate is None:
        rec_default = 0.0
    elif disp_rate is None:
        disp_default = 0.0

    rec_ts = _as_timeseries(rec_rate, years=years, name="recycling_rate", default=rec_default)
    disp_ts = _as_timeseries(disp_rate, years=years, name="disposal_rate", default=disp_default)

    if rec_rate is None and disp_rate is not None:
        rec_ts = 1.0 - reman_ts - disp_ts
    elif disp_rate is None and rec_rate is not None:
        disp_ts = 1.0 - reman_ts - rec_ts
    elif rec_rate is None and disp_rate is None:
        rec_ts = 1.0 - reman_ts

    for name, arr in {
        "recycling_rate": rec_ts,
        "remanufacturing_rate": reman_ts,
        "disposal_rate": disp_ts,
    }.items():
        if (arr < 0).any() or (arr > 1).any():
            raise ValueError(f"{name} must be in [0, 1].")
    if not np.allclose(rec_ts + reman_ts + disp_ts, 1.0, atol=1e-9):
        raise ValueError("recycling_rate + remanufacturing_rate + disposal_rate must equal 1.0.")
    return rec_ts, reman_ts, disp_ts


def apply_routing_rate_shocks(
    *,
    recycling_rate: Any,
    remanufacturing_rate: Any,
    disposal_rate: Any,
    years: Sequence[int],
    shocks: Dict[str, Any],
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    rec = _as_timeseries(recycling_rate, years=years, name="recycling_rate")
    rem = _as_timeseries(remanufacturing_rate, years=years, name="remanufacturing_rate")
    disp = _as_timeseries(disposal_rate, years=years, name="disposal_rate")

    for shock_name, arr in {
        "recycling_rate": rec,
        "remanufacturing_rate": rem,
        "disposal_rate": disp,
    }.items():
        event = _event_to_dict(shocks.get(shock_name))
        if event is None:
            continue
        arr *= _shock_multiplier_series(years, event)

    rec = np.maximum(rec, 0.0)
    rem = np.maximum(rem, 0.0)
    disp = np.maximum(disp, 0.0)

    total = rec + rem + disp
    if (total <= 0).any():
        raise ValueError("Routing-rate shocks produced zero total routing in at least one year.")

    rec = rec / total
    rem = rem / total
    disp = disp / total
    return rec, rem, disp
