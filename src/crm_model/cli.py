from __future__ import annotations

import argparse
import os
from datetime import datetime
from glob import glob
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Tuple

# Keep matplotlib/fontconfig caches under repo when HOME-level cache dirs are unavailable.
if "MPLCONFIGDIR" not in os.environ:
    _repo_root_guess = Path(__file__).resolve().parents[2]
    _cache_root = _repo_root_guess / ".cache"
    _cache_root.mkdir(parents=True, exist_ok=True)
    _mpl_cache = _cache_root / "matplotlib"
    _mpl_cache.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(_mpl_cache)
    os.environ.setdefault("XDG_CACHE_HOME", str(_cache_root))

import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table

from crm_model.config.io import load_run_config, resolve_repo_root_from_config
from crm_model.coupling.runner import run_loose_coupled
from crm_model.data import (
    collection_routing_rates_t,
    end_use_shares_te,
    final_demand_t,
    load_collection_routing_rates,
    load_end_use_shares,
    load_final_demand,
    load_lifetime_distributions,
    load_material_intensity,
    load_primary_refined_net_imports,
    load_primary_refined_output,
    load_remanufacturing_end_use_eligibility,
    load_service_activity,
    load_stage_yields_losses,
    load_stock_in_use,
    material_intensity_t,
    primary_refined_net_imports_tr,
    primary_refined_output_tr,
    remanufacturing_eligibility_tre,
    service_activity_t,
    stage_yields_losses_t,
    stock_in_use_t,
)
from crm_model.mfa import lifetime_pdf_trea_flodym_adapter
from crm_model.sd.params import (
    expand_temporal_value,
    is_year_gate,
    migrate_legacy_strategy_sd_controls,
    normalize_and_validate_sd_parameters,
)
from crm_model.data.validate import validate_exogenous_inputs
from crm_model.scenarios import (
    apply_series_shock,
    apply_primary_refined_net_imports_shock,
    apply_routing_rate_shocks,
    deep_update,
    inject_gate_baselines,
    resolve_routing_rates,
    resolve_sd_parameters_for_slice,
    resolve_variant_slice_overrides,
)
from crm_model.scenario_profiles import (
    build_variant_payload_from_profiles,
    load_reporting_profile_csv,
)
from crm_model.utils import archive_old_timestamped_runs, scenario_variant_root


def _write_yaml(path: Path, data: Any) -> None:
    import yaml

    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _resolve_exogenous_path(repo_root: Path, rel: str) -> Path:
    return (repo_root / rel).resolve()


def _to_plain_mapping(node: Any) -> Dict[str, Any]:
    if node is None:
        return {}
    if isinstance(node, dict):
        return dict(node)
    if hasattr(node, "model_dump"):
        return node.model_dump(exclude_none=True, exclude_unset=True)
    raise ValueError(f"Unsupported mapping type: {type(node)}")


def _resolve_scenario_profile_csv_files(csv_globs: List[str]) -> List[Path]:
    files: List[Path] = []
    seen: set[str] = set()
    for spec in csv_globs:
        pattern = str(spec).strip()
        if not pattern:
            continue
        matches = sorted(Path(p).resolve() for p in glob(pattern))
        # Backward compatibility: support one-cycle migration from data/scenario_profiles to data/ramp_profiles.
        if not matches and "data/scenario_profiles/" in pattern:
            fallback_pattern = pattern.replace("data/scenario_profiles/", "data/ramp_profiles/")
            matches = sorted(Path(p).resolve() for p in glob(fallback_pattern))
        for p in matches:
            if not p.is_file():
                continue
            key = str(p)
            if key in seen:
                continue
            seen.add(key)
            files.append(p)
    return files


def _collect_profile_payloads(
    *,
    cfg,
    years: List[int],
    report_start_year: int,
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    scenario_profiles = getattr(cfg, "scenario_profiles", None)
    if scenario_profiles is None or not bool(getattr(scenario_profiles, "enabled", False)):
        return {}, {"enabled": False, "csv_files": [], "variants_in_profiles": [], "collision_keys": []}

    csv_files = _resolve_scenario_profile_csv_files(list(getattr(scenario_profiles, "csv_globs", []) or []))
    if not csv_files:
        raise ValueError("scenario_profiles.enabled=true but no CSV files matched scenario_profiles.csv_globs.")

    frames = [load_reporting_profile_csv(p) for p in csv_files]
    profiles = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    payloads = build_variant_payload_from_profiles(
        profiles=profiles,
        years=years,
        report_start_year=report_start_year,
    )
    variants_in_profiles = sorted({str(v) for v in profiles["variant"].unique().tolist()}) if not profiles.empty else []
    return payloads, {
        "enabled": True,
        "csv_files": [str(p) for p in csv_files],
        "variants_in_profiles": variants_in_profiles,
        "collision_keys": [],
        "apply_precedence": str(getattr(scenario_profiles, "apply_precedence", "profile_overrides_variant")),
    }


def _matches_profile_scope(
    *,
    material: str,
    region: str,
    materials: List[str] | None,
    regions: List[str] | None,
) -> bool:
    mat_ok = True
    reg_ok = True
    if materials:
        mat_ok = str(material).lower() in {str(m).lower() for m in materials}
    if regions:
        reg_ok = str(region).lower() in {str(r).lower() for r in regions}
    return mat_ok and reg_ok


def _collect_overlap_paths(base: Any, overlay: Any, *, prefix: str = "") -> List[str]:
    if not isinstance(base, dict) or not isinstance(overlay, dict):
        return []
    hits: List[str] = []
    for key, value in overlay.items():
        cur = f"{prefix}.{key}" if prefix else str(key)
        if key not in base:
            continue
        hits.append(cur)
        if isinstance(base.get(key), dict) and isinstance(value, dict):
            hits.extend(_collect_overlap_paths(base.get(key), value, prefix=cur))
    return hits


def _is_ramp_points(value: Any) -> bool:
    return isinstance(value, dict) and "points" in value


def _is_exogenous_ramp_reference(value: Any) -> bool:
    return isinstance(value, dict) and "exogenous_ramp" in value


def _parse_ramp_points_dict(points: Any) -> Dict[int, float]:
    if isinstance(points, dict):
        out: Dict[int, float] = {}
        for k, v in points.items():
            out[int(k)] = float(v)
        return out
    if isinstance(points, (list, tuple)):
        out = {}
        for row in points:
            if not isinstance(row, dict) or "year" not in row or "value" not in row:
                continue
            out[int(row["year"])] = float(row["value"])
        return out
    return {}


def _clip_ramp_points_to_reporting(value: Dict[str, Any], report_start_year: int) -> Dict[str, Any]:
    points = _parse_ramp_points_dict(value.get("points"))
    if not points:
        return value
    years_sorted = sorted(points.keys())
    if years_sorted[0] >= int(report_start_year):
        return value

    x = np.array(years_sorted, dtype=float)
    y = np.array([points[yy] for yy in years_sorted], dtype=float)
    y_report = float(np.interp(float(report_start_year), x, y, left=float(y[0]), right=float(y[-1])))
    clipped = {int(yy): float(vv) for yy, vv in points.items() if int(yy) >= int(report_start_year)}
    clipped[int(report_start_year)] = y_report
    out = dict(value)
    out["points"] = {int(k): float(clipped[k]) for k in sorted(clipped.keys())}
    return out


def _resolve_exogenous_ramp_csv_path(*, repo_root: Path, raw_path: Any) -> Path:
    spec = str(raw_path).strip()
    if not spec:
        raise ValueError("exogenous_ramp path must be a non-empty string.")
    p = Path(spec).expanduser()
    if not p.is_absolute():
        p = (repo_root / p).resolve()
    # Backward compatibility: support one-cycle migration from data/scenario_profiles to data/ramp_profiles.
    if (not p.exists() or not p.is_file()) and "data/scenario_profiles/" in str(p):
        p = Path(str(p).replace("data/scenario_profiles/", "data/ramp_profiles/"))
    if not p.exists() or not p.is_file():
        raise ValueError(f"exogenous_ramp CSV file not found: {p}")
    return p


def _select_ramp_scope_rows(
    *,
    profile_df: pd.DataFrame,
    variant: str,
    block: str,
    key: str,
    material: str,
    region: str,
) -> pd.DataFrame:
    subset = profile_df[
        (profile_df["variant"] == str(variant))
        & (profile_df["block"] == str(block))
        & (profile_df["key"] == str(key))
    ]
    if subset.empty:
        raise ValueError(
            f"exogenous_ramp reference unresolved: no rows for variant={variant!r}, block={block!r}, key={key!r}."
        )

    material_norm = str(material).strip()
    region_norm = str(region).strip()
    candidates = [
        subset[(subset["material"] == material_norm) & (subset["region"] == region_norm)],
        subset[(subset["material"] == material_norm) & (subset["region"] == "")],
        subset[(subset["material"] == "") & (subset["region"] == region_norm)],
        subset[(subset["material"] == "") & (subset["region"] == "")],
    ]
    for cand in candidates:
        if not cand.empty:
            return cand
    raise ValueError(
        "exogenous_ramp reference unresolved for scope "
        f"material={material_norm!r}, region={region_norm!r}, "
        f"variant={variant!r}, block={block!r}, key={key!r}."
    )


def _resolve_exogenous_ramp_reference(
    *,
    value: Dict[str, Any],
    repo_root: Path,
    variant_name: str,
    block_name: str,
    key_name: str,
    material: str,
    region: str,
) -> Dict[str, Any]:
    csv_path = _resolve_exogenous_ramp_csv_path(repo_root=repo_root, raw_path=value.get("exogenous_ramp"))
    profile_df, _ = _load_table_cached(csv_path, load_reporting_profile_csv)

    variant = str(value.get("variant", variant_name))
    block = str(value.get("block", block_name))
    key = str(value.get("key", key_name))
    scoped_material = str(value.get("material", material)).strip()
    scoped_region = str(value.get("region", region)).strip()

    rows = _select_ramp_scope_rows(
        profile_df=profile_df,
        variant=variant,
        block=block,
        key=key,
        material=scoped_material,
        region=scoped_region,
    )
    rows_sorted = rows.sort_values("year")
    points = {int(r.year): float(r.value) for r in rows_sorted.itertuples(index=False)}
    if not points:
        raise ValueError(
            f"exogenous_ramp reference unresolved: no year points for variant={variant!r}, block={block!r}, key={key!r}."
        )
    out: Dict[str, Any] = {"points": points}
    if "before" in value and value["before"] is not None:
        out["before"] = float(value["before"])
    else:
        before_vals = rows_sorted["before"].dropna().astype(float).unique().tolist()
        if before_vals:
            out["before"] = float(before_vals[0])
    return out


def _resolve_exogenous_ramps_in_mapping(
    *,
    overrides: Dict[str, Any],
    repo_root: Path,
    variant_name: str,
    block_name: str,
    material: str,
    region: str,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in (overrides or {}).items():
        if _is_exogenous_ramp_reference(value):
            out[key] = _resolve_exogenous_ramp_reference(
                value=dict(value),
                repo_root=repo_root,
                variant_name=variant_name,
                block_name=block_name,
                key_name=str(key),
                material=material,
                region=region,
            )
            continue
        if isinstance(value, dict) and not is_year_gate(value) and not _is_ramp_points(value):
            out[key] = _resolve_exogenous_ramps_in_mapping(
                overrides=value,
                repo_root=repo_root,
                variant_name=variant_name,
                block_name=block_name,
                material=material,
                region=region,
            )
            continue
        out[key] = value
    return out


def _resolve_exogenous_ramps_for_variant_slice(
    *,
    variant_slice: Dict[str, Dict[str, Any]],
    repo_root: Path,
    variant_name: str,
    material: str,
    region: str,
) -> Dict[str, Dict[str, Any]]:
    out = dict(variant_slice)
    for block in [
        "sd_parameters",
        "mfa_parameters",
        "strategy",
        "transition_policy",
        "demand_transformation",
    ]:
        out[block] = _resolve_exogenous_ramps_in_mapping(
            overrides=out.get(block, {}),
            repo_root=repo_root,
            variant_name=variant_name,
            block_name=block,
            material=material,
            region=region,
        )
    return out


def _variant_base_payload(cfg, *, variant_name: str) -> Dict[str, Any]:
    variant = cfg.variants[variant_name]
    if hasattr(variant, "model_dump"):
        return variant.model_dump(exclude_none=True, exclude_unset=True)
    return dict(variant)


def _profile_collision_keys(
    *,
    cfg,
    variant_name: str,
    profile_payload: Dict[str, Any],
) -> List[str]:
    if not profile_payload:
        return []
    base_payload = _variant_base_payload(cfg, variant_name=variant_name)
    collisions = _collect_overlap_paths(base_payload, profile_payload)
    return sorted(set(collisions))


def _apply_profile_payload_to_slice(
    *,
    base_slice: Dict[str, Dict[str, Any]],
    profile_payload: Dict[str, Any] | None,
    material: str,
    region: str,
) -> Dict[str, Dict[str, Any]]:
    if not profile_payload:
        return base_slice

    out: Dict[str, Dict[str, Any]] = {k: dict(v) if isinstance(v, dict) else v for k, v in base_slice.items()}
    for block in [
        "sd_parameters",
        "mfa_parameters",
        "strategy",
        "transition_policy",
        "demand_transformation",
        "shocks",
    ]:
        overlay = profile_payload.get(block)
        if isinstance(overlay, dict) and overlay:
            base_block = out.get(block, {})
            if not isinstance(base_block, dict):
                base_block = {}
            out[block] = deep_update(base_block, overlay)

    for ov in profile_payload.get("dimension_overrides", []) or []:
        if not isinstance(ov, dict):
            continue
        if not _matches_profile_scope(
            material=material,
            region=region,
            materials=ov.get("materials"),
            regions=ov.get("regions"),
        ):
            continue
        for block in [
            "sd_parameters",
            "mfa_parameters",
            "strategy",
            "transition_policy",
            "demand_transformation",
            "shocks",
        ]:
            overlay = ov.get(block)
            if isinstance(overlay, dict) and overlay:
                base_block = out.get(block, {})
                if not isinstance(base_block, dict):
                    base_block = {}
                out[block] = deep_update(base_block, overlay)
    return out


def _enforce_reporting_only_temporal_mapping(
    *,
    overrides: Dict[str, Any],
    baseline: Dict[str, Any] | None,
    years: List[int],
    report_start_year: int,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    baseline_map = baseline or {}

    for key, value in (overrides or {}).items():
        base_val = baseline_map.get(key) if isinstance(baseline_map, dict) else None

        # Shock-event mapping: clamp activation to reporting phase, trimming pre-report duration.
        if (
            isinstance(value, dict)
            and {"start_year", "duration_years", "multiplier"}.issubset(value.keys())
        ):
            evt = dict(value)
            start = int(evt["start_year"])
            duration = int(evt["duration_years"])
            if start < int(report_start_year):
                trim = int(report_start_year) - start
                evt["start_year"] = int(report_start_year)
                evt["duration_years"] = max(0, duration - trim)
            out[key] = evt
            continue

        if is_year_gate(value):
            gate = dict(value)
            gate["start_year"] = max(int(gate["start_year"]), int(report_start_year))
            if "before" not in gate and base_val is not None:
                gate["before"] = base_val
            out[key] = gate
            continue

        if _is_ramp_points(value):
            ramp = _clip_ramp_points_to_reporting(dict(value), int(report_start_year))
            if "before" not in ramp and base_val is not None:
                ramp["before"] = base_val
            out[key] = ramp
            continue

        if isinstance(value, dict):
            out[key] = _enforce_reporting_only_temporal_mapping(
                overrides=value,
                baseline=base_val if isinstance(base_val, dict) else {},
                years=years,
                report_start_year=report_start_year,
            )
            continue

        if isinstance(value, (list, tuple, np.ndarray)):
            arr = np.array(value).reshape(-1)
            if int(arr.size) == int(len(years)):
                gated: Dict[str, Any] = {
                    "start_year": int(report_start_year),
                    "value": list(value),
                }
                if base_val is not None:
                    gated["before"] = base_val
                out[key] = gated
                continue

        out[key] = value
    return out


def _enforce_reporting_phase_for_variant_slice(
    *,
    variant_slice: Dict[str, Dict[str, Any]],
    years: List[int],
    report_start_year: int,
    sd_base: Dict[str, Any],
    mfa_base: Dict[str, Any],
    strategy_base: Dict[str, Any],
    transition_policy_base: Dict[str, Any],
    demand_transformation_base: Dict[str, Any],
    shocks_base: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    out = dict(variant_slice)
    out["sd_parameters"] = _enforce_reporting_only_temporal_mapping(
        overrides=out.get("sd_parameters", {}),
        baseline=sd_base,
        years=years,
        report_start_year=report_start_year,
    )
    out["mfa_parameters"] = _enforce_reporting_only_temporal_mapping(
        overrides=out.get("mfa_parameters", {}),
        baseline=mfa_base,
        years=years,
        report_start_year=report_start_year,
    )
    out["strategy"] = _enforce_reporting_only_temporal_mapping(
        overrides=out.get("strategy", {}),
        baseline=strategy_base,
        years=years,
        report_start_year=report_start_year,
    )
    out["transition_policy"] = _enforce_reporting_only_temporal_mapping(
        overrides=out.get("transition_policy", {}),
        baseline=transition_policy_base,
        years=years,
        report_start_year=report_start_year,
    )
    out["demand_transformation"] = _enforce_reporting_only_temporal_mapping(
        overrides=out.get("demand_transformation", {}),
        baseline=demand_transformation_base,
        years=years,
        report_start_year=report_start_year,
    )
    out["shocks"] = _enforce_reporting_only_temporal_mapping(
        overrides=out.get("shocks", {}),
        baseline=shocks_base,
        years=years,
        report_start_year=report_start_year,
    )
    return out


def _temporal_series(
    value: Any,
    *,
    years: List[int],
    name: str,
    default: float,
    report_start_year: int | None = None,
) -> np.ndarray:
    return expand_temporal_value(
        value,
        years=years,
        name=name,
        default=default,
        report_start_year=report_start_year,
        emit_warnings=True,
        context="run_one_variant",
    ).astype(float)


def _build_transition_adoption_series(
    *,
    years: List[int],
    transition_policy: Dict[str, Any],
) -> np.ndarray:
    enabled = bool(transition_policy.get("enabled", False))
    if not enabled:
        return np.zeros(len(years), dtype=float)

    start_year = int(transition_policy.get("start_year", years[0] if years else 0))
    target = float(np.clip(transition_policy.get("adoption_target", 0.0), 0.0, 1.0))
    lag_years = max(float(transition_policy.get("adoption_lag_years", 4.0)), 1.0e-6)
    compliance_delay = max(float(transition_policy.get("compliance_delay_years", 0.0)), 0.0)
    activation_year = float(start_year) + compliance_delay

    adoption = np.zeros(len(years), dtype=float)
    for i, y in enumerate(years):
        elapsed = float(y) - activation_year
        if elapsed < 0.0:
            adoption[i] = 0.0
            continue
        adoption[i] = float(target * (1.0 - np.exp(-elapsed / lag_years)))
    return np.clip(adoption, 0.0, target)


def _apply_demand_transformation(
    *,
    base_demand: np.ndarray,
    years: List[int],
    demand_transformation: Dict[str, Any],
    service_activity: np.ndarray | None,
    material_intensity: np.ndarray | None,
    transition_adoption: np.ndarray,
    transition_policy: Dict[str, Any],
    report_start_year: int,
) -> tuple[np.ndarray, np.ndarray]:
    enabled = bool(demand_transformation.get("enabled", False))
    if not enabled:
        return np.array(base_demand, dtype=float), np.ones(len(years), dtype=float)

    normalize_exogenous = bool(demand_transformation.get("normalize_exogenous", True))

    if service_activity is None:
        activity_index = np.ones(len(years), dtype=float)
    else:
        activity = np.array(service_activity, dtype=float)
        if normalize_exogenous:
            denom = float(activity[0]) if activity.size else 1.0
            denom = denom if abs(denom) > 1.0e-12 else 1.0
            activity_index = activity / denom
        else:
            activity_index = activity

    if material_intensity is None:
        intensity_index = np.ones(len(years), dtype=float)
    else:
        intensity = np.array(material_intensity, dtype=float)
        if normalize_exogenous:
            denom = float(intensity[0]) if intensity.size else 1.0
            denom = denom if abs(denom) > 1.0e-12 else 1.0
            intensity_index = intensity / denom
        else:
            intensity_index = intensity

    activity_multiplier = _temporal_series(
        demand_transformation.get("service_activity_multiplier", 1.0),
        years=years,
        name="demand_transformation.service_activity_multiplier",
        default=1.0,
        report_start_year=report_start_year,
    )
    intensity_multiplier = _temporal_series(
        demand_transformation.get("material_intensity_multiplier", 1.0),
        years=years,
        name="demand_transformation.material_intensity_multiplier",
        default=1.0,
        report_start_year=report_start_year,
    )
    efficiency_improvement = np.clip(
        _temporal_series(
            demand_transformation.get("efficiency_improvement", 0.0),
            years=years,
            name="demand_transformation.efficiency_improvement",
            default=0.0,
            report_start_year=report_start_year,
        ),
        0.0,
        0.95,
    )
    rebound_effect = np.clip(
        _temporal_series(
            demand_transformation.get("rebound_effect", 0.0),
            years=years,
            name="demand_transformation.rebound_effect",
            default=0.0,
            report_start_year=report_start_year,
        ),
        0.0,
        1.0,
    )
    transition_weight = float(
        np.clip(demand_transformation.get("transition_adoption_weight", 0.0), 0.0, 1.0)
    )
    transition_reduction_max = float(
        np.clip(transition_policy.get("demand_intensity_reduction_max", 0.0), 0.0, 1.0)
    )

    compounded_efficiency = np.clip(
        efficiency_improvement + transition_weight * transition_reduction_max * transition_adoption,
        0.0,
        0.95,
    )
    efficiency_factor = 1.0 - compounded_efficiency * (1.0 - rebound_effect)
    raw_multiplier = activity_index * intensity_index * activity_multiplier * intensity_multiplier * efficiency_factor

    min_mult = float(demand_transformation.get("min_demand_multiplier", 0.25))
    max_mult = float(demand_transformation.get("max_demand_multiplier", 2.5))
    multiplier = np.clip(raw_multiplier, min_mult, max_mult)
    transformed = np.maximum(np.array(base_demand, dtype=float) * multiplier, 0.0)
    return transformed, multiplier


def _apply_transition_policy_adjustments(
    *,
    years: List[int],
    transition_policy: Dict[str, Any],
    transition_adoption: np.ndarray,
    sd_params: Dict[str, Any],
    mfa_params: Dict[str, Any],
    strategy: Dict[str, Any],
    report_start_year: int,
) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    enabled = bool(transition_policy.get("enabled", False))
    if not enabled:
        return sd_params, mfa_params, strategy

    out_sd = dict(sd_params)
    out_mfa = dict(mfa_params)
    out_strategy = dict(strategy)

    collection_uplift_max = max(float(transition_policy.get("collection_uplift_max", 0.0)), 0.0)
    if collection_uplift_max > 0.0:
        collection_base = _temporal_series(
            out_mfa.get("collection_rate", 0.4),
            years=years,
            name="mfa_parameters.collection_rate",
            default=0.4,
            report_start_year=report_start_year,
        )
        out_mfa["collection_rate"] = np.clip(
            collection_base * (1.0 + collection_uplift_max * transition_adoption),
            0.0,
            1.0,
        )

    recycling_yield_uplift_max = max(float(transition_policy.get("recycling_yield_uplift_max", 0.0)), 0.0)
    if recycling_yield_uplift_max > 0.0:
        recycling_yield_base = _temporal_series(
            out_strategy.get("recycling_yield", out_mfa.get("recycling_yield", 0.8)),
            years=years,
            name="strategy.recycling_yield",
            default=0.8,
            report_start_year=report_start_year,
        )
        out_strategy["recycling_yield"] = np.clip(
            recycling_yield_base * (1.0 + recycling_yield_uplift_max * transition_adoption),
            0.0,
            1.0,
        )

    capacity_expansion_gain_uplift = max(
        float(transition_policy.get("capacity_expansion_gain_uplift", 0.0)),
        0.0,
    )
    if capacity_expansion_gain_uplift > 0.0:
        capacity_gain_base = _temporal_series(
            out_sd.get("capacity_expansion_gain", 0.2),
            years=years,
            name="sd_parameters.capacity_expansion_gain",
            default=0.2,
            report_start_year=report_start_year,
        )
        out_sd["capacity_expansion_gain"] = np.maximum(
            capacity_gain_base * (1.0 + capacity_expansion_gain_uplift * transition_adoption),
            0.0,
        )

    bottleneck_relief_max = float(np.clip(transition_policy.get("bottleneck_relief_max", 0.0), 0.0, 1.0))
    if bottleneck_relief_max > 0.0:
        relief = np.clip(1.0 - bottleneck_relief_max * transition_adoption, 0.0, 1.0)
        for key, default in (
            ("bottleneck_scarcity_gain", 0.0),
            ("bottleneck_collection_sensitivity", 0.0),
        ):
            base = _temporal_series(
                out_sd.get(key, default),
                years=years,
                name=f"sd_parameters.{key}",
                default=default,
                report_start_year=report_start_year,
            )
            out_sd[key] = np.maximum(base * relief, 0.0)

    return out_sd, out_mfa, out_strategy


_TABLE_CACHE: Dict[Tuple[str, str, int, int], Any] = {}
_ARRAY_CACHE: Dict[Tuple[Any, ...], Any] = {}
_COUPLING_WARM_START: Dict[Tuple[Any, ...], Tuple[float, float, float]] = {}
_CACHE_LOCK = Lock()


def _file_signature(path: Path) -> Tuple[str, int, int]:
    st = path.stat()
    return (str(path), int(st.st_mtime_ns), int(st.st_size))


def _load_table_cached(path: Path, loader) -> Tuple[Any, Tuple[str, int, int]]:
    sig = _file_signature(path)
    key = (loader.__name__, sig[0], sig[1], sig[2])
    with _CACHE_LOCK:
        hit = _TABLE_CACHE.get(key)
    if hit is not None:
        return hit, sig
    df = loader(path)
    with _CACHE_LOCK:
        _TABLE_CACHE[key] = df
    return df, sig


def _cached_array(key: Tuple[Any, ...], factory):
    with _CACHE_LOCK:
        hit = _ARRAY_CACHE.get(key)
    if hit is not None:
        return hit.copy()
    arr = factory()
    with _CACHE_LOCK:
        _ARRAY_CACHE[key] = arr
    return arr.copy()


def run_one_variant(
    *,
    cfg,
    repo_root: Path,
    variant_name: str,
    phase: str,
    profile_payload: Dict[str, Any] | None = None,
    timeseries_indicators: List[str] | None = None,
    collect_scalar: bool = True,
    collect_summary: bool = True,
    collect_coupling_debug: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Returns (ts_indicators, scalar_metrics, summary_table_rows, coupling_signal_trace_rows, coupling_convergence_rows)."""

    time = cfg.time
    dims = cfg.dimensions

    assert time is not None and dims is not None

    if phase == "calibration":
        years = time.calibration_years
        report_years: List[int] = []
    else:
        years = time.years
        report_years = time.report_years

    service_level_threshold = float(cfg.indicators.service_risk.get("threshold_service_level", 0.95))

    allowed_ts = set(timeseries_indicators) if timeseries_indicators is not None else set(cfg.indicators.all_metrics())
    mfa_graph_payload = cfg.mfa_graph.model_dump(by_alias=True) if cfg.mfa_graph is not None else None
    coupling_payload = cfg.coupling.model_dump() if cfg.coupling else {}

    sd_base = normalize_and_validate_sd_parameters(
        cfg.sd_parameters,
        emit_warnings=True,
        context="run sd_parameters",
    )
    mfa_base = cfg.mfa_parameters
    strategy_base = cfg.strategy.model_dump(exclude_none=True, exclude_unset=True)
    transition_policy_base = _to_plain_mapping(getattr(cfg, "transition_policy", None))
    demand_transformation_base = _to_plain_mapping(getattr(cfg, "demand_transformation", None))
    shocks_base = cfg.shocks.model_dump(exclude_none=True, exclude_unset=True)

    # load exogenous inputs
    vars_ = cfg.variables
    assert vars_ is not None

    demand_df, demand_sig = _load_table_cached(
        _resolve_exogenous_path(repo_root, vars_["final_demand"].path), load_final_demand
    )
    shares_df, shares_sig = _load_table_cached(
        _resolve_exogenous_path(repo_root, vars_["end_use_shares"].path), load_end_use_shares
    )
    optional_demand_drivers: Dict[str, Tuple[Any, Tuple[str, int, int]]] = {}
    for var_name, loader in (
        ("service_activity", load_service_activity),
        ("material_intensity", load_material_intensity),
    ):
        if var_name not in vars_:
            continue
        source_path = _resolve_exogenous_path(repo_root, vars_[var_name].path)
        if not source_path.exists():
            continue
        df_opt, sig_opt = _load_table_cached(source_path, loader)
        optional_demand_drivers[var_name] = (df_opt, sig_opt)
    refined_output_df = None
    refined_output_sig = None
    if "primary_refined_output" in vars_:
        refined_output_df, refined_output_sig = _load_table_cached(
            _resolve_exogenous_path(repo_root, vars_["primary_refined_output"].path),
            load_primary_refined_output,
        )

    refined_net_imp_df = None
    refined_net_imp_sig = None
    if "primary_refined_net_imports" in vars_:
        refined_net_imp_df, refined_net_imp_sig = _load_table_cached(
            _resolve_exogenous_path(repo_root, vars_["primary_refined_net_imports"].path),
            load_primary_refined_net_imports,
        )

    stage_df = None
    stage_sig = None
    if "stage_yields_losses" in vars_:
        stage_df, stage_sig = _load_table_cached(
            _resolve_exogenous_path(repo_root, vars_["stage_yields_losses"].path),
            load_stage_yields_losses,
        )
    routing_rates_df = None
    routing_sig = None
    if "collection_routing_rates" in vars_:
        routing_rates_df, routing_sig = _load_table_cached(
            _resolve_exogenous_path(repo_root, vars_["collection_routing_rates"].path),
            load_collection_routing_rates,
        )
    reman_eligibility_df = None
    reman_eligibility_sig = None
    if "remanufacturing_end_use_eligibility" in vars_:
        reman_eligibility_df, reman_eligibility_sig = _load_table_cached(
            _resolve_exogenous_path(repo_root, vars_["remanufacturing_end_use_eligibility"].path),
            load_remanufacturing_end_use_eligibility,
        )
    lt_df, _ = _load_table_cached(
        _resolve_exogenous_path(repo_root, vars_["lifetime_distributions"].path), load_lifetime_distributions
    )

    stock_df = None
    stock_sig = None
    if phase in {"calibration", "both"} and "stock_in_use" in vars_:
        stock_path = _resolve_exogenous_path(repo_root, vars_["stock_in_use"].path)
        if stock_path.exists():
            stock_df, stock_sig = _load_table_cached(stock_path, load_stock_in_use)

    years_key = tuple(int(y) for y in years)
    calibration_years_key = tuple(int(y) for y in time.calibration_years)
    end_uses_key = tuple(str(eu) for eu in dims.end_uses)

    ts_rows: List[Dict[str, Any]] = []
    scalar_rows: List[Dict[str, Any]] = []
    summary_rows: List[Dict[str, Any]] = []
    coupling_trace_rows: List[Dict[str, Any]] = []
    coupling_convergence_rows: List[Dict[str, Any]] = []

    for mat in dims.materials:
        material = mat.name
        for region in dims.regions:
            variant_slice = resolve_variant_slice_overrides(
                cfg=cfg,
                variant_name=variant_name,
                material=material,
                region=region,
            )
            variant_slice = _apply_profile_payload_to_slice(
                base_slice=variant_slice,
                profile_payload=profile_payload,
                material=material,
                region=region,
            )
            variant_slice = _resolve_exogenous_ramps_for_variant_slice(
                variant_slice=variant_slice,
                repo_root=repo_root,
                variant_name=variant_name,
                material=material,
                region=region,
            )
            sd_params = resolve_sd_parameters_for_slice(
                sd_base=sd_base,
                sd_heterogeneity=cfg.sd_heterogeneity,
                material=material,
                region=region,
            )
            variant_slice = _enforce_reporting_phase_for_variant_slice(
                variant_slice=variant_slice,
                years=years,
                report_start_year=int(time.report_start_year),
                sd_base=sd_params,
                mfa_base=mfa_base,
                strategy_base=strategy_base,
                transition_policy_base=transition_policy_base,
                demand_transformation_base=demand_transformation_base,
                shocks_base=shocks_base,
            )
            mfa_overrides = inject_gate_baselines(
                overrides=variant_slice["mfa_parameters"],
                primary_base=mfa_base,
            )
            strategy_overrides = inject_gate_baselines(
                overrides=variant_slice["strategy"],
                primary_base=strategy_base,
                secondary_base=mfa_base,
            )
            transition_policy_overrides = inject_gate_baselines(
                overrides=variant_slice["transition_policy"],
                primary_base=transition_policy_base,
            )
            demand_transformation_overrides = inject_gate_baselines(
                overrides=variant_slice["demand_transformation"],
                primary_base=demand_transformation_base,
            )
            sd_overrides = inject_gate_baselines(
                overrides=variant_slice["sd_parameters"],
                primary_base=sd_params,
            )
            sd_params = deep_update(sd_params, sd_overrides)
            mfa_params = deep_update(mfa_base, mfa_overrides)
            strategy = deep_update(strategy_base, strategy_overrides)
            transition_policy = deep_update(transition_policy_base, transition_policy_overrides)
            demand_transformation = deep_update(
                demand_transformation_base,
                demand_transformation_overrides,
            )
            shocks = deep_update(shocks_base, variant_slice["shocks"])
            sd_params, strategy = migrate_legacy_strategy_sd_controls(
                sd_parameters=sd_params,
                strategy=strategy,
                emit_warnings=True,
                context=f"variant '{variant_name}'",
            )
            sd_params = normalize_and_validate_sd_parameters(
                sd_params,
                years=years,
                report_start_year=time.report_start_year,
                emit_warnings=True,
                context=f"variant '{variant_name}' sd_parameters",
            )

            sd_params["report_start_year"] = time.report_start_year
            sd_params["report_years"] = report_years
            transition_adoption = _build_transition_adoption_series(
                years=years,
                transition_policy=transition_policy,
            )
            warm_key = ("coupling_warm_start", phase, variant_name, years_key, material, region)
            with _CACHE_LOCK:
                warm_signals = _COUPLING_WARM_START.get(warm_key)
            if warm_signals is not None:
                sd_params.setdefault("service_stress_signal", float(warm_signals[0]))
                sd_params.setdefault("circular_supply_stress_signal", float(warm_signals[1]))
                if len(warm_signals) > 2:
                    sd_params.setdefault("strategic_stock_coverage_years", float(warm_signals[2]))

            fd_t_raw = _cached_array(
                ("final_demand_t", demand_sig, years_key, material, region),
                lambda: final_demand_t(demand_df, years=years, material=material, region=region),
            )
            sh_te = _cached_array(
                ("end_use_shares_te", shares_sig, years_key, material, region, end_uses_key),
                lambda: end_use_shares_te(
                    shares_df, years=years, material=material, region=region, end_uses=dims.end_uses
                ),
            )
            service_activity_series = None
            material_intensity_series = None
            service_activity_source = str(
                demand_transformation.get("service_activity_source", "service_activity")
            ).strip()
            material_intensity_source = str(
                demand_transformation.get("material_intensity_source", "material_intensity")
            ).strip()
            if service_activity_source in optional_demand_drivers:
                service_df, service_sig = optional_demand_drivers[service_activity_source]
                service_activity_series = _cached_array(
                    ("service_activity_t", service_sig, years_key, material, region, service_activity_source),
                    lambda: service_activity_t(
                        service_df,
                        years=years,
                        material=material,
                        region=region,
                    ),
                )
            if material_intensity_source in optional_demand_drivers:
                intensity_df, intensity_sig = optional_demand_drivers[material_intensity_source]
                material_intensity_series = _cached_array(
                    (
                        "material_intensity_t",
                        intensity_sig,
                        years_key,
                        material,
                        region,
                        material_intensity_source,
                    ),
                    lambda: material_intensity_t(
                        intensity_df,
                        years=years,
                        material=material,
                        region=region,
                    ),
                )

            fd_t, demand_transform_multiplier = _apply_demand_transformation(
                base_demand=fd_t_raw,
                years=years,
                demand_transformation=demand_transformation,
                service_activity=service_activity_series,
                material_intensity=material_intensity_series,
                transition_adoption=transition_adoption,
                transition_policy=transition_policy,
                report_start_year=time.report_start_year,
            )

            lt_mult = _temporal_series(
                strategy.get("lifetime_multiplier", 1.0),
                years=years,
                name="strategy.lifetime_multiplier",
                default=1.0,
                report_start_year=time.report_start_year,
            )
            lt_pdf = lifetime_pdf_trea_flodym_adapter(
                lt_df,
                years=years,
                material=material,
                regions=[region],
                end_uses=dims.end_uses,
                lifetime_multiplier=lt_mult,
            )

            if refined_output_df is not None:
                refined_output_tr = _cached_array(
                    ("primary_refined_output_tr", refined_output_sig, years_key, material, region),
                    lambda: primary_refined_output_tr(
                        refined_output_df,
                        years=years,
                        material=material,
                        regions=[region],
                    ),
                )
            else:
                raise ValueError(
                    "Missing required exogenous input for primary refined output: "
                    "primary_refined_output."
                )

            if refined_net_imp_df is not None:
                refined_net_imp_tr = _cached_array(
                    ("primary_refined_net_imports_tr", refined_net_imp_sig, years_key, material, region),
                    lambda: primary_refined_net_imports_tr(
                        refined_net_imp_df,
                        years=years,
                        material=material,
                        regions=[region],
                    ),
                )
            else:
                refined_net_imp_tr = np.zeros_like(refined_output_tr, dtype=float)

            refined_output_tr = apply_series_shock(
                series_tr=refined_output_tr,
                years=years,
                shocks=shocks,
                shock_name="primary_refined_output",
            )
            refined_net_imp_tr = apply_series_shock(
                series_tr=refined_net_imp_tr,
                years=years,
                shocks=shocks,
                shock_name="primary_refined_net_imports",
            )
            refined_net_imp_tr = apply_primary_refined_net_imports_shock(
                primary_refined_net_imports_tr=refined_net_imp_tr,
                years=years,
                shocks=shocks,
            )
            primary_available_tr = np.maximum(refined_output_tr + refined_net_imp_tr, 0.0)

            stage_params = {
                "extraction_yield": np.ones(len(years), dtype=float),
                "beneficiation_yield": np.ones(len(years), dtype=float),
                "refining_yield": np.ones(len(years), dtype=float),
                "sorting_yield": np.ones(len(years), dtype=float),
                "extraction_loss_to_sysenv_share": np.ones(len(years), dtype=float),
                "beneficiation_loss_to_sysenv_share": np.ones(len(years), dtype=float),
                "refining_loss_to_sysenv_share": np.ones(len(years), dtype=float),
                "sorting_reject_to_disposal_share": np.ones(len(years), dtype=float),
                "sorting_reject_to_sysenv_share": np.zeros(len(years), dtype=float),
            }
            if stage_df is not None:
                stage_map = _cached_array(
                    ("stage_yields_losses_t", stage_sig, years_key, material, region),
                    lambda: stage_yields_losses_t(
                        stage_df,
                        years=years,
                        material=material,
                        region=region,
                    ),
                )
                # _cached_array copies numpy arrays, but here the payload is a dict; avoid mutating cache payload.
                stage_params = {k: np.array(v, dtype=float).copy() for k, v in stage_map.items()}

            for key in ["extraction_yield", "beneficiation_yield", "refining_yield", "sorting_yield"]:
                stage_params[key] = np.clip(
                    apply_series_shock(
                        series_tr=stage_params[key][:, None],
                        years=years,
                        shocks=shocks,
                        shock_name=key,
                    )[:, 0],
                    0.0,
                    1.0,
                )

            mfa_params_it = dict(mfa_params)
            mfa_params_it["lifetime_pdf_trea"] = lt_pdf
            mfa_params_it["primary_available_to_refining"] = primary_available_tr
            mfa_params_it["primary_refined_output"] = refined_output_tr
            mfa_params_it["primary_refined_net_imports"] = refined_net_imp_tr
            for k, v in stage_params.items():
                mfa_params_it[k] = v
            if reman_eligibility_df is not None:
                mfa_params_it["remanufacturing_end_use_eligibility_tre"] = _cached_array(
                    ("remanufacturing_eligibility_tre", reman_eligibility_sig, years_key, region, end_uses_key),
                    lambda: remanufacturing_eligibility_tre(
                        reman_eligibility_df,
                        years=years,
                        regions=[region],
                        end_uses=dims.end_uses,
                    ),
                )
            strategy_it = dict(strategy)
            if routing_rates_df is not None:
                routing_arr = _cached_array(
                    ("collection_routing_rates_t", routing_sig, years_key, material, region),
                    lambda: np.stack(
                        collection_routing_rates_t(
                            routing_rates_df, years=years, material=material, region=region
                        ),
                        axis=0,
                    ),
                )
                rec_t, rem_t, disp_t = routing_arr[0], routing_arr[1], routing_arr[2]
                if any(
                    k in strategy_it
                    for k in ["recycling_rate", "remanufacturing_rate", "remanufacture_share", "disposal_rate"]
                ):
                    rec_t, rem_t, disp_t = resolve_routing_rates(
                        years=years,
                        strategy=strategy_it,
                        params={
                            "recycling_rate": rec_t,
                            "remanufacturing_rate": rem_t,
                            "disposal_rate": disp_t,
                        },
                    )
            else:
                rec_t, rem_t, disp_t = resolve_routing_rates(
                    years=years,
                    strategy=strategy_it,
                    params=mfa_params_it,
                )

            rec_t, rem_t, disp_t = apply_routing_rate_shocks(
                recycling_rate=rec_t,
                remanufacturing_rate=rem_t,
                disposal_rate=disp_t,
                years=years,
                shocks=shocks,
            )
            strategy_it["recycling_rate"] = rec_t
            strategy_it["remanufacturing_rate"] = rem_t
            strategy_it["disposal_rate"] = disp_t

            sd_params, mfa_params_it, strategy_it = _apply_transition_policy_adjustments(
                years=years,
                transition_policy=transition_policy,
                transition_adoption=transition_adoption,
                sd_params=sd_params,
                mfa_params=mfa_params_it,
                strategy=strategy_it,
                report_start_year=time.report_start_year,
            )

            res = run_loose_coupled(
                years=years,
                material=material,
                region=region,
                end_uses=dims.end_uses,
                final_demand_t=fd_t,
                end_use_shares_te=sh_te,
                sd_params=sd_params,
                mfa_params=mfa_params_it,
                mfa_graph=mfa_graph_payload,
                strategy=strategy_it,
                shocks=shocks,
                coupling=coupling_payload,
                service_level_threshold=service_level_threshold,
            )
            final_service_signal = float(res.meta.get("final_service_stress_signal", np.nan))
            final_circular_signal = float(res.meta.get("final_circular_supply_stress_signal", np.nan))
            final_strategic_signal = float(res.meta.get("final_strategic_stock_coverage_signal", np.nan))
            if (
                np.isfinite(final_service_signal)
                and np.isfinite(final_circular_signal)
                and np.isfinite(final_strategic_signal)
            ):
                with _CACHE_LOCK:
                    _COUPLING_WARM_START[warm_key] = (
                        final_service_signal,
                        final_circular_signal,
                        final_strategic_signal,
                    )

            # time-series indicators
            keep_years = years if phase in {"calibration"} else report_years
            for ind_name, series in res.indicators_ts.items():
                if ind_name not in allowed_ts:
                    continue
                s = series.loc[[y for y in keep_years if y in series.index]]
                for y, v in s.items():
                    ts_rows.append(
                        {
                            "phase": phase,
                            "variant": variant_name,
                            "material": material,
                            "region": region,
                            "year": int(y),
                            "indicator": ind_name,
                            "value": float(v),
                        }
                    )

            if collect_scalar:
                for met_name, v in res.indicators_scalar.items():
                    scalar_rows.append(
                        {
                            "phase": phase,
                            "variant": variant_name,
                            "material": material,
                            "region": region,
                            "metric": met_name,
                            "value": float(v),
                        }
                    )

            if collect_coupling_debug:
                if not res.coupling_signals_iter_year.empty:
                    trace = res.coupling_signals_iter_year.copy()
                    trace["phase"] = phase
                    trace["variant"] = variant_name
                    trace["material"] = material
                    trace["region"] = region
                    coupling_trace_rows.extend(trace.to_dict(orient="records"))
                if not res.coupling_convergence_iter.empty:
                    conv = res.coupling_convergence_iter.copy()
                    conv["phase"] = phase
                    conv["variant"] = variant_name
                    conv["material"] = material
                    conv["region"] = region
                    coupling_convergence_rows.extend(conv.to_dict(orient="records"))

            # calibration-only fit metric (stock RMSE)
            stock_rmse = np.nan
            if stock_df is not None and (collect_scalar or collect_summary):
                obs = _cached_array(
                    (
                        "stock_in_use_t",
                        stock_sig,
                        calibration_years_key,
                        material,
                        region,
                        end_uses_key,
                    ),
                    lambda: stock_in_use_t(
                        stock_df,
                        years=time.calibration_years,
                        material=material,
                        region=region,
                        end_uses=dims.end_uses,
                    ),
                )
                mod = res.mfa.stock_in_use.loc[time.calibration_years].to_numpy(dtype=float)
                mask = ~np.isnan(obs)
                if mask.any():
                    stock_rmse = float(np.sqrt(np.mean((mod[mask] - obs[mask]) ** 2)))
                    if collect_scalar:
                        scalar_rows.append(
                            {
                                "phase": phase,
                                "variant": variant_name,
                                "material": material,
                                "region": region,
                                "metric": "Stock_RMSE_calibration",
                                "value": stock_rmse,
                            }
                        )

            if collect_summary:
                summary_rows.append(
                    {
                        "variant": variant_name,
                        "phase": phase,
                        "material": material,
                        "region": region,
                        "iterations": int(res.meta.get("iterations", 0)),
                        "final_service_stress_signal": float(res.meta.get("final_service_stress_signal", np.nan)),
                        "final_circular_supply_stress_signal": float(
                            res.meta.get("final_circular_supply_stress_signal", np.nan)
                        ),
                        "final_strategic_stock_coverage_signal": float(
                            res.meta.get("final_strategic_stock_coverage_signal", np.nan)
                        ),
                        "final_stress_multiplier": float(res.meta.get("final_stress_multiplier", np.nan)),
                        "final_collection_multiplier_mean": float(res.meta.get("final_collection_multiplier_mean", np.nan)),
                        "final_collection_rate_mean": float(res.meta.get("final_collection_rate_mean", np.nan)),
                        "final_scarcity_multiplier_effective_mean": float(
                            res.meta.get("final_scarcity_multiplier_effective_mean", np.nan)
                        ),
                        "final_capacity_envelope_mean": float(res.meta.get("final_capacity_envelope_mean", np.nan)),
                        "final_flow_utilization_mean": float(res.meta.get("final_flow_utilization_mean", np.nan)),
                        "final_bottleneck_pressure_mean": float(res.meta.get("final_bottleneck_pressure_mean", np.nan)),
                        "final_collection_bottleneck_throttle_mean": float(
                            res.meta.get("final_collection_bottleneck_throttle_mean", np.nan)
                        ),
                        "final_transition_adoption_mean": float(np.mean(transition_adoption)),
                        "final_demand_transformation_multiplier_mean": float(
                            np.mean(demand_transform_multiplier)
                        ),
                        "final_strategic_fill_intent_mean": float(
                            res.meta.get("final_strategic_fill_intent_mean", np.nan)
                        ),
                        "final_strategic_release_intent_mean": float(
                            res.meta.get("final_strategic_release_intent_mean", np.nan)
                        ),
                        "coupling_converged": bool(res.meta.get("coupling_converged", False)),
                        "coupling_convergence_metric": float(res.meta.get("coupling_convergence_metric", np.nan)),
                        "coupling_tolerance": float(res.meta.get("coupling_tolerance", np.nan)),
                        "stock_rmse_cal": stock_rmse,
                    }
                )

    return (
        pd.DataFrame(ts_rows),
        pd.DataFrame(scalar_rows),
        pd.DataFrame(summary_rows),
        pd.DataFrame(coupling_trace_rows),
        pd.DataFrame(coupling_convergence_rows),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the coupled SD–dMFA model")
    ap.add_argument("--config", default="configs/runs/mvp.yml")
    ap.add_argument("--variant", default="baseline")
    ap.add_argument("--phase", choices=["calibration", "reporting", "both"], default="reporting")
    ap.add_argument("--save-csv", action="store_true")
    ap.add_argument("--outdir", default="outputs/runs")
    args = ap.parse_args()

    console = Console()

    cfg_path = Path(args.config).resolve()
    cfg = load_run_config(cfg_path)
    repo_root = resolve_repo_root_from_config(cfg_path)

    warnings = validate_exogenous_inputs(cfg, repo_root=repo_root)
    for w in warnings:
        console.print(f"[yellow]Warning:[/yellow] {w}")

    if args.variant not in cfg.variants:
        raise SystemExit(f"Unknown variant: {args.variant}. Available: {list(cfg.variants.keys())}")

    scenario_profile_payloads: Dict[str, Dict[str, Any]] = {}
    scenario_profile_meta: Dict[str, Any] = {
        "enabled": False,
        "csv_files": [],
        "variants_in_profiles": [],
        "collision_keys": [],
        "apply_precedence": "profile_overrides_variant",
        "active_variant_has_payload": False,
    }
    if bool(getattr(cfg.scenario_profiles, "enabled", False)):
        scenario_profile_payloads, scenario_profile_meta = _collect_profile_payloads(
            cfg=cfg,
            years=cfg.time.years if cfg.time is not None else [],
            report_start_year=int(cfg.time.report_start_year) if cfg.time is not None else 0,
        )
        scenario_profile_meta["collision_keys"] = _profile_collision_keys(
            cfg=cfg,
            variant_name=args.variant,
            profile_payload=scenario_profile_payloads.get(args.variant, {}),
        )
        scenario_profile_meta["active_variant_has_payload"] = bool(scenario_profile_payloads.get(args.variant))
        console.print(
            "[cyan]Scenario profiles active:[/cyan] "
            f"files={len(scenario_profile_meta['csv_files'])}, "
            f"active_variant_has_payload={scenario_profile_meta['active_variant_has_payload']}, "
            f"collision_keys={len(scenario_profile_meta['collision_keys'])}"
        )

    phases = ["calibration", "reporting"] if args.phase == "both" else [args.phase]

    all_ts = []
    all_scalar = []
    all_summary = []
    all_coupling_trace = []
    all_coupling_convergence = []

    for ph in phases:
        ts_df, scalar_df, summary_df, coupling_trace_df, coupling_conv_df = run_one_variant(
            cfg=cfg,
            repo_root=repo_root,
            variant_name=args.variant,
            phase=ph,
            profile_payload=scenario_profile_payloads.get(args.variant, {}) if ph == "reporting" else {},
        )
        all_ts.append(ts_df)
        all_scalar.append(scalar_df)
        all_summary.append(summary_df)
        all_coupling_trace.append(coupling_trace_df)
        all_coupling_convergence.append(coupling_conv_df)

    ts = pd.concat(all_ts, ignore_index=True) if all_ts else pd.DataFrame()
    scalar = pd.concat(all_scalar, ignore_index=True) if all_scalar else pd.DataFrame()
    summary = pd.concat(all_summary, ignore_index=True) if all_summary else pd.DataFrame()
    coupling_trace = pd.concat(all_coupling_trace, ignore_index=True) if all_coupling_trace else pd.DataFrame()
    coupling_convergence = (
        pd.concat(all_coupling_convergence, ignore_index=True) if all_coupling_convergence else pd.DataFrame()
    )

    # Console summary
    table = Table(title=f"{cfg.name} | variant={args.variant} | phase={args.phase}")
    for col in [
        "phase",
        "material",
        "region",
        "iterations",
        "final_service_stress_signal",
        "final_circular_supply_stress_signal",
        "final_strategic_stock_coverage_signal",
        "final_stress_multiplier",
        "coupling_converged",
        "coupling_convergence_metric",
        "stock_rmse_cal",
    ]:
        table.add_column(col)

    for _, r in summary.iterrows():
        table.add_row(
            str(r.get("phase")),
            str(r.get("material")),
            str(r.get("region")),
            str(int(r.get("iterations"))),
            (
                f"{float(r.get('final_service_stress_signal')):.3f}"
                if pd.notna(r.get("final_service_stress_signal"))
                else "NA"
            ),
            (
                f"{float(r.get('final_circular_supply_stress_signal')):.3f}"
                if pd.notna(r.get("final_circular_supply_stress_signal"))
                else "NA"
            ),
            (
                f"{float(r.get('final_strategic_stock_coverage_signal')):.3f}"
                if pd.notna(r.get("final_strategic_stock_coverage_signal"))
                else "NA"
            ),
            (
                f"{float(r.get('final_stress_multiplier')):.3f}"
                if pd.notna(r.get("final_stress_multiplier"))
                else "NA"
            ),
            str(bool(r.get("coupling_converged"))),
            (
                f"{float(r.get('coupling_convergence_metric')):.4f}"
                if pd.notna(r.get("coupling_convergence_metric"))
                else "NA"
            ),
            f"{float(r.get('stock_rmse_cal')):.3g}" if pd.notna(r.get("stock_rmse_cal")) else "NA",
        )

    console.print(table)

    if args.save_csv:
        variant_cfg = cfg.variants[args.variant]
        out_root = (repo_root / args.outdir).resolve()
        config_stem = Path(args.config).stem
        scenario_root = scenario_variant_root(out_root, config_stem, args.variant)
        ts_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir = scenario_root / ts_stamp
        run_dir.mkdir(parents=True, exist_ok=True)

        _write_yaml(
            run_dir / "run_metadata.yml",
            {
                "timestamp": ts_stamp,
                "config": str(Path(args.config)),
                "variant": args.variant,
                "phase": args.phase,
                "variant_description": variant_cfg.description,
                "variant_implementation": variant_cfg.implementation,
                "dimension_overrides_count": len(variant_cfg.dimension_overrides),
                "scenario_profiles": scenario_profile_meta,
            },
        )
        if bool(getattr(cfg.scenario_profiles, "emit_resolved_payload", False)):
            _write_yaml(
                run_dir / "resolved_profile_payload.yml",
                {
                    "variant": args.variant,
                    "profile_payload": scenario_profile_payloads.get(args.variant, {}),
                    "scenario_profiles": scenario_profile_meta,
                },
            )

        ind_dir = run_dir / "indicators"
        ind_dir.mkdir(parents=True, exist_ok=True)

        ts.to_csv(ind_dir / "timeseries.csv", index=False)
        scalar.to_csv(ind_dir / "scalar_metrics.csv", index=False)
        coupling_trace.to_csv(ind_dir / "coupling_signals_iteration_year.csv", index=False)
        coupling_convergence.to_csv(ind_dir / "coupling_convergence_iteration.csv", index=False)
        summary.to_csv(run_dir / "summary.csv", index=False)

        moved = archive_old_timestamped_runs(scenario_root, keep_last=3)
        if moved:
            console.print(
                f"Archived {len(moved)} older run(s) to: {scenario_root / '_archive'}"
            )

        console.print(f"Saved run artifacts to: {run_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
