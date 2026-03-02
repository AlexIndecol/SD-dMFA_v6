#!/usr/bin/env python
"""Calibrate OD-trade allocator controls against observed OD flows.

This script calibrates trade-layer parameters while keeping the existing
stock-in-use calibration workflow unchanged.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import yaml

from crm_model import cli as cli_runtime
from crm_model.config.io import load_run_config, resolve_repo_root_from_config
from crm_model.data import load_trade_od_constraints, load_trade_od_observed, load_trade_od_weights
from crm_model.trade import run_trade_od_allocator, validate_trade_od_sources


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
    ap.add_argument("--variant", default="baseline")
    ap.add_argument("--phase", choices=["calibration", "reporting"], default="reporting")
    ap.add_argument("--lambda-grid", default="0.1,0.2,0.3,0.4,0.5")
    ap.add_argument("--sd-cap-multiplier-grid", default="0.8,1.0,1.2")
    ap.add_argument("--outdir", default="outputs/runs/calibration/trade_od")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    repo_root = resolve_repo_root_from_config(cfg_path)
    cfg = load_run_config(cfg_path)
    if args.variant not in cfg.variants:
        raise ValueError(f"Unknown variant '{args.variant}'. Available: {list(cfg.variants.keys())}")

    # Ensure OD path is active for calibration pass.
    cfg.trade_od.enabled = True

    years = cfg.time.calibration_years if args.phase == "calibration" else cfg.time.years

    # Run model once to obtain SD capacity-envelope trajectories by material-region slice.
    cli_runtime.run_one_variant(
        cfg=cfg,
        repo_root=repo_root,
        variant_name=args.variant,
        phase=args.phase,
        collect_scalar=False,
        collect_summary=False,
        collect_coupling_debug=False,
    )
    with cli_runtime._CACHE_LOCK:
        payload = cli_runtime._LAST_TRADE_OD_ARTIFACTS.get((args.phase, args.variant), {})
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

    lambda_grid = _parse_grid(args.lambda_grid, name="lambda")
    sd_mult_grid = _parse_grid(args.sd_cap_multiplier_grid, name="sd-cap-multiplier")
    rows: List[Dict[str, float | str]] = []
    best = None

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
                observed_flows=observed,
                weights=weights,
                constraints=constraints,
                sd_capacity_envelope_by_material_region=cap_lookup,
                historical_window_start_year=int(cfg.trade_od.historical_window_start_year),
                historical_window_end_year=int(cfg.trade_od.historical_window_end_year),
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
                "observed_total_kt": float(metrics["observed_total_kt"]),
                "modeled_total_kt": float(metrics["modeled_total_kt"]),
            }
            rows.append(row)
            if best is None or row["rmse"] < best["rmse"]:
                best = row

    if best is None:
        raise RuntimeError("No calibration candidates evaluated.")

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = (repo_root / args.outdir / Path(args.config).stem / args.variant / ts).resolve()
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
                "variant": args.variant,
                "phase": args.phase,
                "best": best,
                "lambda_grid": lambda_grid,
                "sd_capacity_multiplier_grid": sd_mult_grid,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    print(f"Wrote trade calibration artifacts to: {outdir}")
    print(
        "Best trade_od params: "
        f"lambda={best['lambda']:.3f}, sd_capacity_multiplier={best['sd_capacity_multiplier']:.3f}, rmse={best['rmse']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

