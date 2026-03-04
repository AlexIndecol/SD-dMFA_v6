#!/usr/bin/env python
"""Calibrate OD-trade allocator controls against observed OD flows.

This script calibrates trade-layer parameters while keeping the existing
stock-in-use calibration workflow unchanged.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import yaml

from crm_model import cli as cli_runtime
from crm_model.config.io import load_run_config, resolve_repo_root_from_config
from crm_model.data import load_trade_od_constraints, load_trade_od_observed, load_trade_od_weights
from crm_model.trade import run_trade_od_allocator, validate_trade_od_sources


def _read_yaml(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML file must contain a top-level mapping: {path}")
    return data


def _parse_grid(raw: str, *, name: str) -> List[float]:
    vals: List[float] = []
    for token in str(raw).split(","):
        s = token.strip()
        if not s:
            continue
        vals.append(float(s))
    if not vals:
        raise ValueError(f"{name} grid is empty.")
    return vals


def _parse_grid_from_obj(raw: Any, *, name: str) -> List[float]:
    if isinstance(raw, str):
        return _parse_grid(raw, name=name)
    if isinstance(raw, (list, tuple)):
        vals = [float(x) for x in raw]
        if not vals:
            raise ValueError(f"{name} grid is empty.")
        return vals
    raise ValueError(f"{name} grid must be a comma string or list; got {type(raw)}")


def _metrics_against_observed(modeled: pd.DataFrame, observed: pd.DataFrame) -> Dict[str, float]:
    keys = ["year", "material", "commodity", "origin_region", "destination_region"]
    m = modeled[keys + ["flow_kt"]].rename(columns={"flow_kt": "modeled_flow_kt"})
    o = observed[keys + ["flow_kt"]].rename(columns={"flow_kt": "observed_flow_kt"})
    merged = o.merge(m, on=keys, how="left")
    merged["modeled_flow_kt"] = merged["modeled_flow_kt"].fillna(0.0)
    err = merged["modeled_flow_kt"].to_numpy(dtype=float) - merged["observed_flow_kt"].to_numpy(dtype=float)
    rmse = float(np.sqrt(np.mean(err**2)))
    mae = float(np.mean(np.abs(err)))
    obs_sum = float(merged["observed_flow_kt"].sum())
    modeled_sum = float(merged["modeled_flow_kt"].sum())
    pct_bias = float(100.0 * (modeled_sum - obs_sum) / obs_sum) if obs_sum > 0 else 0.0
    return {
        "rmse": rmse,
        "mae": mae,
        "observed_total_kt": obs_sum,
        "modeled_total_kt": modeled_sum,
        "pct_bias": pct_bias,
    }


def _select_best(rows: List[Dict[str, float | str]], *, primary_metric: str, fallback_metric: str) -> Dict[str, float | str]:
    if not rows:
        raise RuntimeError("No trade calibration rows available for selection.")
    valid_metrics = {"rmse", "mae", "abs_pct_bias", "pct_bias"}
    if primary_metric not in valid_metrics:
        raise ValueError(f"Unsupported primary metric '{primary_metric}'. Allowed: {sorted(valid_metrics)}")
    if fallback_metric not in valid_metrics:
        raise ValueError(f"Unsupported fallback metric '{fallback_metric}'. Allowed: {sorted(valid_metrics)}")

    df = pd.DataFrame(rows).copy()
    if primary_metric == "pct_bias":
        df = df.assign(_metric_primary=df["pct_bias"].abs())
    else:
        df = df.assign(_metric_primary=df[primary_metric].astype(float))
    if fallback_metric == "pct_bias":
        df = df.assign(_metric_fallback=df["pct_bias"].abs())
    else:
        df = df.assign(_metric_fallback=df[fallback_metric].astype(float))
    df = df.sort_values(["_metric_primary", "_metric_fallback", "rmse", "mae"], ascending=True)
    return dict(df.iloc[0].drop(labels=["_metric_primary", "_metric_fallback"]).to_dict())


def _capacity_lookup_from_df(
    *,
    capacity_df: pd.DataFrame,
    years: List[int],
    materials: List[str],
    regions: List[str],
) -> Dict[Tuple[str, str], np.ndarray]:
    out: Dict[Tuple[str, str], np.ndarray] = {}
    for material in materials:
        for region in regions:
            sub = capacity_df[
                (capacity_df["material"] == material)
                & (capacity_df["region"] == region)
                & (capacity_df["year"].isin(years))
            ].copy()
            if sub.empty:
                out[(material, region)] = np.ones(len(years), dtype=float)
                continue
            s = sub.sort_values("year").set_index("year")["capacity_envelope"].reindex(years)
            s = s.ffill().bfill().fillna(1.0)
            out[(material, region)] = s.to_numpy(dtype=float)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Calibrate OD-trade allocator against observed OD matrices.")
    ap.add_argument("--config", default="configs/runs/mvp.yml")
    ap.add_argument("--calibration-spec", default="configs/calibration_trade.yml")
    ap.add_argument("--variant", default="baseline")
    ap.add_argument("--phase", choices=["calibration", "reporting"], default=None)
    ap.add_argument("--lambda-grid", default=None, help="Override lambda grid (comma-list).")
    ap.add_argument(
        "--sd-cap-multiplier-grid",
        default=None,
        help="Override SD capacity multiplier grid (comma-list).",
    )
    ap.add_argument("--outdir", default=None, help="Override output root.")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cal_path = Path(args.calibration_spec).resolve()
    repo_root = resolve_repo_root_from_config(cfg_path)
    cfg = load_run_config(cfg_path)
    spec = _read_yaml(cal_path)
    if args.variant not in cfg.variants:
        raise ValueError(f"Unknown variant '{args.variant}'. Available: {list(cfg.variants.keys())}")

    windows_cfg = spec.get("windows") or {}
    params_cfg = spec.get("parameters") or {}
    optimization_cfg = spec.get("optimization") or {}
    runtime_cfg = spec.get("runtime") or {}  # legacy fallback
    grids_cfg = spec.get("grids") or {}  # legacy fallback
    selection_cfg = spec.get("selection") or {}
    outputs_cfg = spec.get("outputs") or {}
    fit_window_cfg = windows_cfg.get("fit") or {}
    trade_params_cfg = (params_cfg.get("trade_od") or {}) if isinstance(params_cfg, dict) else {}
    grid_search_cfg = (optimization_cfg.get("grid_search") or {}) if isinstance(optimization_cfg, dict) else {}

    phase = str(
        args.phase
        or fit_window_cfg.get("phase")
        or runtime_cfg.get("phase", "reporting")
    ).strip().lower()
    if phase not in {"calibration", "reporting"}:
        raise ValueError(f"Invalid phase {phase!r}; expected 'calibration' or 'reporting'.")

    if args.lambda_grid:
        lambda_grid = _parse_grid(args.lambda_grid, name="lambda")
    else:
        lam_cfg = trade_params_cfg.get("coupling_relax_lambda_0_1", {}) if isinstance(trade_params_cfg, dict) else {}
        lambda_grid = _parse_grid_from_obj(
            (lam_cfg.get("grid") if isinstance(lam_cfg, dict) else None)
            or grid_search_cfg.get("coupling_relax_lambda_0_1")
            or grids_cfg.get("coupling_relax_lambda_0_1")
            or [0.1, 0.2, 0.3, 0.4, 0.5],
            name="coupling_relax_lambda_0_1",
        )
    if args.sd_cap_multiplier_grid:
        sd_mult_grid = _parse_grid(args.sd_cap_multiplier_grid, name="sd-cap-multiplier")
    else:
        cap_cfg = trade_params_cfg.get("capacity_cap_sd_multiplier", {}) if isinstance(trade_params_cfg, dict) else {}
        sd_mult_grid = _parse_grid_from_obj(
            (cap_cfg.get("grid") if isinstance(cap_cfg, dict) else None)
            or grid_search_cfg.get("capacity_cap_sd_multiplier")
            or grids_cfg.get("capacity_cap_sd_multiplier")
            or [0.8, 1.0, 1.2],
            name="capacity_cap_sd_multiplier",
        )
    outdir_root = str(args.outdir or outputs_cfg.get("outdir", "outputs/runs/calibration/trade_od")).strip()
    if not outdir_root:
        raise ValueError("Trade calibration outdir cannot be empty.")
    primary_metric = str(selection_cfg.get("primary_metric", "rmse")).strip()
    fallback_metric = str(selection_cfg.get("fallback_metric", "mae")).strip()
    selection_constraints = selection_cfg.get("constraints") or {}
    max_abs_pct_bias = selection_constraints.get("max_abs_pct_bias")
    max_abs_pct_bias = None if max_abs_pct_bias is None else float(max_abs_pct_bias)

    # Ensure OD path is active for calibration pass.
    cfg.trade_od.enabled = True

    years = cfg.time.calibration_years if phase == "calibration" else cfg.time.years
    fit_start_year = fit_window_cfg.get("start_year")
    fit_end_year = fit_window_cfg.get("end_year")
    if fit_start_year is not None:
        years = [y for y in years if int(y) >= int(fit_start_year)]
    if fit_end_year is not None:
        years = [y for y in years if int(y) <= int(fit_end_year)]
    if not years:
        raise ValueError("No years remain after applying windows.fit start/end filters.")

    # Run model once to obtain SD capacity-envelope trajectories by material-region slice.
    cli_runtime.run_one_variant(
        cfg=cfg,
        repo_root=repo_root,
        variant_name=args.variant,
        phase=phase,
        collect_scalar=False,
        collect_summary=False,
        collect_coupling_debug=False,
    )
    with cli_runtime._CACHE_LOCK:
        payload = cli_runtime._LAST_TRADE_OD_ARTIFACTS.get((phase, args.variant), {})
    capacity_df = payload.get("sd_capacity_envelope_by_slice", pd.DataFrame()).copy()
    if capacity_df.empty:
        raise RuntimeError("trade_od capacity envelope payload is empty; cannot calibrate trade allocator.")

    vars_map = cfg.variables or {}
    for src in [cfg.trade_od.observed_flow_source, cfg.trade_od.weights_source, cfg.trade_od.constraints_source]:
        if src not in vars_map:
            raise ValueError(f"Missing trade source in variable registry: {src}")
    observed = load_trade_od_observed(repo_root / vars_map[cfg.trade_od.observed_flow_source].path)
    weights = load_trade_od_weights(repo_root / vars_map[cfg.trade_od.weights_source].path)
    constraints = load_trade_od_constraints(repo_root / vars_map[cfg.trade_od.constraints_source].path)

    materials = [m.name for m in cfg.dimensions.materials]  # type: ignore[union-attr]
    regions = list(cfg.dimensions.regions)  # type: ignore[union-attr]
    commodities = list(cfg.trade_od.commodities)
    validate_trade_od_sources(
        observed_flows=observed,
        weights=weights,
        constraints=constraints,
        materials=materials,
        regions=regions,
        commodities=commodities,
    )

    cap_lookup = _capacity_lookup_from_df(
        capacity_df=capacity_df,
        years=years,
        materials=materials,
        regions=regions,
    )

    rows: List[Dict[str, float | str]] = []

    for lam in lambda_grid:
        if lam < 0 or lam > 1:
            raise ValueError("lambda-grid values must be in [0,1].")
        for sd_mult in sd_mult_grid:
            if sd_mult <= 0:
                raise ValueError("sd-cap-multiplier-grid values must be > 0.")
            out = run_trade_od_allocator(
                years=years,
                materials=materials,
                regions=regions,
                commodities=commodities,
                weights=weights,
                constraints=constraints,
                sd_capacity_envelope_by_material_region=cap_lookup,
                capacity_cap_hybrid_mode=str(cfg.trade_od.capacity_cap_hybrid_mode),
                capacity_cap_sd_multiplier=float(sd_mult),
                coupling_relax_lambda_0_1=float(lam),
                max_reallocation_passes=int(cfg.trade_od.allocator_max_reallocation_passes),
            )
            metrics = _metrics_against_observed(out.flows, observed)
            row = {
                "lambda": float(lam),
                "sd_capacity_multiplier": float(sd_mult),
                "rmse": float(metrics["rmse"]),
                "mae": float(metrics["mae"]),
                "pct_bias": float(metrics["pct_bias"]),
                "abs_pct_bias": float(abs(metrics["pct_bias"])),
                "observed_total_kt": float(metrics["observed_total_kt"]),
                "modeled_total_kt": float(metrics["modeled_total_kt"]),
            }
            rows.append(row)

    if not rows:
        raise RuntimeError("No calibration candidates evaluated.")
    rows_for_selection = rows
    if max_abs_pct_bias is not None:
        rows_for_selection = [r for r in rows if float(r["abs_pct_bias"]) <= max_abs_pct_bias]
    if not rows_for_selection:
        rows_for_selection = rows
    best = _select_best(rows_for_selection, primary_metric=primary_metric, fallback_metric=fallback_metric)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = (repo_root / outdir_root / Path(args.config).stem / args.variant / ts).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).sort_values(["rmse", "mae"]).to_csv(outdir / "trade_od_calibration_grid.csv", index=False)

    patch = {
        "trade_od": {
            "coupling_relax_lambda_0_1": float(best["lambda"]),
            "capacity_cap_sd_multiplier": float(best["sd_capacity_multiplier"]),
        }
    }
    (outdir / "best_trade_od_patch.yml").write_text(yaml.safe_dump(patch, sort_keys=False), encoding="utf-8")
    (outdir / "trade_od_calibration_summary.yml").write_text(
        yaml.safe_dump(
            {
                "config": str(cfg_path),
                "calibration_spec": str(cal_path),
                "variant": args.variant,
                "phase": phase,
                "best": best,
                "selection": {
                    "primary_metric": primary_metric,
                    "fallback_metric": fallback_metric,
                    "constraints": {
                        "max_abs_pct_bias": max_abs_pct_bias,
                    },
                    "candidates_evaluated": len(rows),
                    "candidates_selected_pool": len(rows_for_selection),
                },
                "lambda_grid": lambda_grid,
                "sd_capacity_multiplier_grid": sd_mult_grid,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    print(f"Wrote trade calibration artifacts to: {outdir}")
    print(
        f"Selected best ({primary_metric}) trade_od params: "
        f"lambda={best['lambda']:.3f}, sd_capacity_multiplier={best['sd_capacity_multiplier']:.3f}, "
        f"rmse={best['rmse']:.3f}, mae={best['mae']:.3f}, abs_pct_bias={best['abs_pct_bias']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
