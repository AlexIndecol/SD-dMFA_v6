#!/usr/bin/env python
"""Compare observed OD trade flows against pre/post calibration model allocations."""

from __future__ import annotations
# ruff: noqa: E402

import argparse
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Keep matplotlib cache writable inside repo/sandbox before importing pyplot.
_REPO_ROOT_GUESS = Path(__file__).resolve().parents[3]
_CACHE_ROOT = _REPO_ROOT_GUESS / ".cache"
(_CACHE_ROOT / "matplotlib").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_CACHE_ROOT / "matplotlib"))

import matplotlib.pyplot as plt
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
        "pct_bias": pct_bias,
        "abs_pct_bias": float(abs(pct_bias)),
        "observed_total_kt": obs_sum,
        "modeled_total_kt": modeled_sum,
    }


def _resolve_calibration_run_dir(
    *, repo_root: Path, config_stem: str, variant: str, run_dir_arg: str | None
) -> Path:
    if run_dir_arg:
        run_dir = Path(run_dir_arg).resolve()
        if not run_dir.exists():
            raise FileNotFoundError(f"calibration run dir not found: {run_dir}")
        return run_dir

    root = repo_root / "outputs" / "runs" / "calibration" / "trade_od" / config_stem / variant
    if not root.exists():
        raise FileNotFoundError(f"trade calibration root not found: {root}")
    candidates = sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name)
    if not candidates:
        raise FileNotFoundError(f"no trade calibration timestamp directories under: {root}")
    return candidates[-1]


def _plot_totals_by_commodity(joined: pd.DataFrame, outdir: Path) -> None:
    g = (
        joined.groupby(["year", "commodity"], as_index=False)[
            ["observed_flow_kt", "pre_flow_kt", "post_flow_kt"]
        ]
        .sum()
        .sort_values(["commodity", "year"])
    )
    commodities = sorted(g["commodity"].unique())
    n = len(commodities)
    n_cols = 2
    n_rows = int(np.ceil(n / n_cols)) if n > 0 else 1
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(6.5 * n_cols, 3.5 * n_rows), sharex=True)
    axes_arr = np.atleast_1d(axes).reshape(-1)

    for i, commodity in enumerate(commodities):
        ax = axes_arr[i]
        sub = g[g["commodity"] == commodity]
        ax.plot(sub["year"], sub["observed_flow_kt"], color="#222222", linewidth=1.8, label="Observed")
        ax.plot(sub["year"], sub["pre_flow_kt"], color="#3B82F6", linewidth=1.4, label="Model pre")
        ax.plot(sub["year"], sub["post_flow_kt"], color="#D97706", linewidth=1.6, label="Model post")
        ax.set_title(str(commodity))
        ax.set_ylabel("Flow (kt)")
        ax.grid(alpha=0.25)

    for j in range(len(commodities), len(axes_arr)):
        axes_arr[j].axis("off")

    handles, labels = axes_arr[0].get_legend_handles_labels() if commodities else ([], [])
    if handles:
        fig.legend(handles, labels, loc="upper center", ncol=3, frameon=False)
    fig.suptitle("OD trade totals by commodity: observed vs model pre/post", y=0.995)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(outdir / "trade_od_totals_by_commodity.png", dpi=160)
    plt.close(fig)


def _plot_parity(joined: pd.DataFrame, outdir: Path) -> None:
    d = joined[["observed_flow_kt", "pre_flow_kt", "post_flow_kt"]].copy()
    d = d[(d["observed_flow_kt"] > 0) | (d["pre_flow_kt"] > 0) | (d["post_flow_kt"] > 0)]
    if d.empty:
        return

    obs = d["observed_flow_kt"].to_numpy(dtype=float)
    pre = d["pre_flow_kt"].to_numpy(dtype=float)
    post = d["post_flow_kt"].to_numpy(dtype=float)
    max_v = float(max(np.max(obs), np.max(pre), np.max(post)))
    max_v = max(max_v, 1.0)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharex=True, sharey=True)

    axes[0].scatter(obs, pre, s=8, alpha=0.35, color="#3B82F6", edgecolors="none")
    axes[0].plot([0, max_v], [0, max_v], color="#111111", linewidth=1.1)
    axes[0].set_title("Pre vs observed")
    axes[0].set_xlabel("Observed flow (kt)")
    axes[0].set_ylabel("Modeled flow (kt)")
    axes[0].grid(alpha=0.25)

    axes[1].scatter(obs, post, s=8, alpha=0.35, color="#D97706", edgecolors="none")
    axes[1].plot([0, max_v], [0, max_v], color="#111111", linewidth=1.1)
    axes[1].set_title("Post vs observed")
    axes[1].set_xlabel("Observed flow (kt)")
    axes[1].grid(alpha=0.25)

    fig.suptitle("OD flow parity plots (all OD pairs)")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(outdir / "trade_od_parity_pre_vs_post.png", dpi=160)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description="Plot OD trade pre/post model flows against observed data.")
    ap.add_argument("--config", default="configs/runs/mvp.yml")
    ap.add_argument("--variant", default="baseline")
    ap.add_argument("--phase", choices=["calibration", "reporting"], default="reporting")
    ap.add_argument(
        "--calibration-run-dir",
        default=None,
        help="Path to trade calibration run directory containing trade_od_calibration_summary.yml.",
    )
    ap.add_argument("--outdir", default="outputs/analysis/trade_od_observed_vs_model")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    repo_root = resolve_repo_root_from_config(cfg_path)
    cfg = load_run_config(cfg_path)
    if args.variant not in cfg.variants:
        raise ValueError(f"Unknown variant '{args.variant}'. Available: {list(cfg.variants.keys())}")

    cal_run_dir = _resolve_calibration_run_dir(
        repo_root=repo_root,
        config_stem=Path(args.config).stem,
        variant=args.variant,
        run_dir_arg=args.calibration_run_dir,
    )
    summary_path = cal_run_dir / "trade_od_calibration_summary.yml"
    if not summary_path.exists():
        raise FileNotFoundError(f"trade calibration summary not found: {summary_path}")
    summary = _read_yaml(summary_path)
    best = summary.get("best") or {}
    post_lambda = float(best.get("lambda"))
    post_sd_mult = float(best.get("sd_capacity_multiplier"))

    pre_lambda = float(cfg.trade_od.coupling_relax_lambda_0_1)
    pre_sd_mult = float(cfg.trade_od.capacity_cap_sd_multiplier)

    cfg.trade_od.enabled = True
    years = cfg.time.calibration_years if args.phase == "calibration" else cfg.time.years

    # Run once to get SD-derived capacity envelope by material-region.
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
        raise RuntimeError("trade_od capacity envelope payload is empty; cannot build comparison.")

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

    pre_out = run_trade_od_allocator(
        years=years,
        materials=materials,
        regions=regions,
        commodities=commodities,
        weights=weights,
        constraints=constraints,
        sd_capacity_envelope_by_material_region=cap_lookup,
        capacity_cap_hybrid_mode=str(cfg.trade_od.capacity_cap_hybrid_mode),
        capacity_cap_sd_multiplier=float(pre_sd_mult),
        coupling_relax_lambda_0_1=float(pre_lambda),
        max_reallocation_passes=int(cfg.trade_od.allocator_max_reallocation_passes),
    )
    post_out = run_trade_od_allocator(
        years=years,
        materials=materials,
        regions=regions,
        commodities=commodities,
        weights=weights,
        constraints=constraints,
        sd_capacity_envelope_by_material_region=cap_lookup,
        capacity_cap_hybrid_mode=str(cfg.trade_od.capacity_cap_hybrid_mode),
        capacity_cap_sd_multiplier=float(post_sd_mult),
        coupling_relax_lambda_0_1=float(post_lambda),
        max_reallocation_passes=int(cfg.trade_od.allocator_max_reallocation_passes),
    )

    keys = ["year", "material", "commodity", "origin_region", "destination_region"]
    obs_df = observed[keys + ["flow_kt"]].rename(columns={"flow_kt": "observed_flow_kt"})
    pre_df = pre_out.flows[keys + ["flow_kt"]].rename(columns={"flow_kt": "pre_flow_kt"})
    post_df = post_out.flows[keys + ["flow_kt"]].rename(columns={"flow_kt": "post_flow_kt"})
    joined = (
        obs_df.merge(pre_df, on=keys, how="left")
        .merge(post_df, on=keys, how="left")
        .fillna({"pre_flow_kt": 0.0, "post_flow_kt": 0.0})
    )

    pre_metrics = _metrics_against_observed(
        pre_out.flows,
        observed,
    )
    post_metrics = _metrics_against_observed(
        post_out.flows,
        observed,
    )

    by_comm_rows: List[Dict[str, Any]] = []
    for commodity, obs_sub in observed.groupby("commodity"):
        pre_sub = pre_out.flows[pre_out.flows["commodity"] == commodity]
        post_sub = post_out.flows[post_out.flows["commodity"] == commodity]
        m_pre = _metrics_against_observed(pre_sub, obs_sub)
        m_post = _metrics_against_observed(post_sub, obs_sub)
        by_comm_rows.append(
            {
                "commodity": str(commodity),
                "pre_rmse": float(m_pre["rmse"]),
                "post_rmse": float(m_post["rmse"]),
                "pre_mae": float(m_pre["mae"]),
                "post_mae": float(m_post["mae"]),
                "pre_abs_pct_bias": float(m_pre["abs_pct_bias"]),
                "post_abs_pct_bias": float(m_post["abs_pct_bias"]),
                "observed_total_kt": float(m_pre["observed_total_kt"]),
            }
        )
    by_commodity = pd.DataFrame(by_comm_rows).sort_values("commodity")

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = (repo_root / args.outdir / Path(args.config).stem / args.variant / ts).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    joined.to_csv(out_dir / "trade_od_joined_observed_pre_post.csv", index=False)
    by_commodity.to_csv(out_dir / "trade_od_metrics_by_commodity.csv", index=False)
    (out_dir / "trade_od_metrics_summary.yml").write_text(
        yaml.safe_dump(
            {
                "config": str(cfg_path),
                "variant": args.variant,
                "phase": args.phase,
                "calibration_run_dir": str(cal_run_dir),
                "pre_parameters": {
                    "coupling_relax_lambda_0_1": pre_lambda,
                    "capacity_cap_sd_multiplier": pre_sd_mult,
                },
                "post_parameters": {
                    "coupling_relax_lambda_0_1": post_lambda,
                    "capacity_cap_sd_multiplier": post_sd_mult,
                },
                "pre_metrics": pre_metrics,
                "post_metrics": post_metrics,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    _plot_totals_by_commodity(joined, out_dir)
    _plot_parity(joined, out_dir)

    print(f"Wrote OD trade observed-vs-model outputs to: {out_dir}")
    print(
        "Overall RMSE/MAE/abs_pct_bias (pre -> post): "
        f"{pre_metrics['rmse']:.3f}/{pre_metrics['mae']:.3f}/{pre_metrics['abs_pct_bias']:.3f} -> "
        f"{post_metrics['rmse']:.3f}/{post_metrics['mae']:.3f}/{post_metrics['abs_pct_bias']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
