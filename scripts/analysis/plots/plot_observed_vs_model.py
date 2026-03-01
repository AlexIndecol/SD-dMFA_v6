#!/usr/bin/env python
"""Plot observed exogenous variables against modeled baseline/calibrated outputs."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from crm_model.common.io import load_run_config, resolve_repo_root_from_config
from crm_model.common.run_layout import (
    archive_old_timestamped_runs,
    latest_timestamp_from_candidate_roots,
    scenario_variant_root_candidates,
)


def _resolve_runs_base_root(repo_root: Path, root_arg: str) -> Path:
    p = Path(root_arg)
    return p.resolve() if p.is_absolute() else (repo_root / root_arg).resolve()


def _find_latest_variant_run(
    *,
    repo_root: Path,
    runs_root_arg: str,
    config_stem: str,
    variant: str,
) -> Path:
    base_root = _resolve_runs_base_root(repo_root, runs_root_arg)
    candidates = scenario_variant_root_candidates(base_root, config_stem, variant)
    latest = latest_timestamp_from_candidate_roots(candidates)
    if latest is None:
        cand_text = "\n".join(f"- {p}" for p in candidates)
        raise FileNotFoundError(
            f"No run folders found for config='{config_stem}', variant='{variant}' under roots:\n{cand_text}"
        )
    return latest


def _load_observed_series(path: Path, kind: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if kind == "stock_in_use":
        needed = {"year", "material", "region", "end_use", "value"}
    else:
        needed = {"year", "material", "region", "value"}
    missing = sorted(needed - set(df.columns))
    if missing:
        raise ValueError(f"Observed file {path} is missing columns: {missing}")

    out = (
        df.groupby(["material", "region", "year"], as_index=False)["value"]
        .sum()
        .rename(columns={"value": "observed_value"})
    )
    return out


def _load_modeled_indicator(run_dir: Path, phase: str, indicator: str) -> pd.DataFrame:
    p = run_dir / "indicators" / "timeseries.csv"
    if not p.exists():
        raise FileNotFoundError(f"Missing timeseries file: {p}")
    df = pd.read_csv(p)
    needed = {"phase", "material", "region", "year", "indicator", "value"}
    missing = sorted(needed - set(df.columns))
    if missing:
        raise ValueError(f"Timeseries file {p} missing columns: {missing}")
    out = df[(df["phase"] == phase) & (df["indicator"] == indicator)].copy()
    out = (
        out.groupby(["material", "region", "year"], as_index=False)["value"]
        .sum()
        .rename(columns={"value": "model_value"})
    )
    return out


def _load_stage_yields(cfg, repo_root: Path, override_path: str | None = None) -> pd.DataFrame:
    if override_path:
        p = Path(override_path)
        p = p.resolve() if p.is_absolute() else (repo_root / p).resolve()
    else:
        vars_ = cfg.variables
        if "stage_yields_losses" not in vars_:
            raise KeyError("stage_yields_losses variable not found in config registry.")
        p = (repo_root / vars_["stage_yields_losses"].path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Missing stage yields file: {p}")
    df = pd.read_csv(p)
    needed = {"year", "material", "region", "beneficiation_yield", "refining_yield"}
    missing = sorted(needed - set(df.columns))
    if missing:
        raise ValueError(f"Stage yields file {p} missing columns: {missing}")
    out = df[["year", "material", "region", "beneficiation_yield", "refining_yield"]].copy()
    out["beneficiation_yield"] = pd.to_numeric(out["beneficiation_yield"], errors="coerce")
    out["refining_yield"] = pd.to_numeric(out["refining_yield"], errors="coerce")
    return out


def _modeled_proxy_from_primary_supply(
    *,
    run_dir: Path,
    phase: str,
    proxy_kind: str,
    stage_yields_df: pd.DataFrame,
) -> pd.DataFrame:
    primary = _load_modeled_indicator(run_dir, phase, "Primary_supply")
    merged = primary.merge(stage_yields_df, on=["material", "region", "year"], how="left")
    if merged[["beneficiation_yield", "refining_yield"]].isna().any().any():
        raise ValueError(
            "Missing stage_yields_losses coverage for one or more modeled (material, region, year) rows."
        )
    eps = 1.0e-12
    by = np.maximum(merged["beneficiation_yield"].to_numpy(dtype=float), eps)
    ry = np.maximum(merged["refining_yield"].to_numpy(dtype=float), eps)
    ps = merged["model_value"].to_numpy(dtype=float)

    if proxy_kind == "beneficiation_output_proxy":
        vals = ps / ry
    elif proxy_kind == "primary_extraction_output_proxy":
        vals = ps / (ry * by)
    else:
        raise ValueError(f"Unknown modeled proxy kind: {proxy_kind}")

    return pd.DataFrame(
        {
            "material": merged["material"].to_numpy(),
            "region": merged["region"].to_numpy(),
            "year": merged["year"].to_numpy(dtype=int),
            "model_value": vals,
        }
    )


def _load_modeled_series(
    *,
    run_dir: Path,
    phase: str,
    spec: Dict[str, str],
    stage_yields_df: pd.DataFrame,
) -> pd.DataFrame:
    proxy_kind = spec.get("modeled_proxy")
    if proxy_kind:
        return _modeled_proxy_from_primary_supply(
            run_dir=run_dir,
            phase=phase,
            proxy_kind=proxy_kind,
            stage_yields_df=stage_yields_df,
        )
    indicator = spec.get("indicator")
    if not indicator:
        raise ValueError(f"Missing indicator for observed spec: {spec}")
    return _load_modeled_indicator(run_dir, phase, indicator)


def _stitch_modeled_series(calibration: pd.DataFrame, reporting: pd.DataFrame) -> pd.DataFrame:
    out = pd.concat([calibration, reporting], ignore_index=True)
    out = out.sort_values(["material", "region", "year"])
    # If a boundary year appears in both phases, prefer the reporting value.
    out = out.drop_duplicates(subset=["material", "region", "year"], keep="last")
    return out.reset_index(drop=True)


def _join_series(
    observed: pd.DataFrame,
    baseline: pd.DataFrame,
    calibrated: pd.DataFrame,
) -> pd.DataFrame:
    merged = observed.merge(
        baseline.rename(columns={"model_value": "baseline_model_value"}),
        on=["material", "region", "year"],
        how="outer",
    )
    merged = merged.merge(
        calibrated.rename(columns={"model_value": "calibrated_model_value"}),
        on=["material", "region", "year"],
        how="outer",
    )
    return merged.sort_values(["material", "region", "year"]).reset_index(drop=True)


def _fit_metrics(df: pd.DataFrame) -> Dict[str, float]:
    y_obs = df["observed_value"].to_numpy(dtype=float)
    y_mod = df["model_value"].to_numpy(dtype=float)
    err = y_mod - y_obs
    rmse = float(np.sqrt(np.mean(err**2)))
    mae = float(np.mean(np.abs(err)))
    mean_obs = float(np.mean(np.abs(y_obs)))
    nrmse = float(rmse / mean_obs) if mean_obs > 0 else np.nan
    return {"rmse": rmse, "mae": mae, "nrmse_mean": nrmse}


def _year_span(df: pd.DataFrame, year_col: str = "year") -> str:
    years = pd.to_numeric(df[year_col], errors="coerce").dropna()
    if years.empty:
        return "n/a"
    return f"{int(years.min())}-{int(years.max())}"


def _plot_grid(
    *,
    joined: pd.DataFrame,
    materials: List[str],
    regions: List[str],
    title: str,
    ylabel: str,
    out_path: Path,
    baseline_label: str,
    calibrated_label: str,
) -> None:
    n_rows = len(materials)
    n_cols = len(regions)
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(4.4 * n_cols, 2.9 * n_rows), sharex=True)
    if n_rows == 1 and n_cols == 1:
        axes = np.array([[axes]])
    elif n_rows == 1:
        axes = np.array([axes])
    elif n_cols == 1:
        axes = np.array([[ax] for ax in axes])

    for i, mat in enumerate(materials):
        for j, reg in enumerate(regions):
            ax = axes[i, j]
            sub = joined[(joined["material"] == mat) & (joined["region"] == reg)].copy()
            if sub.empty:
                ax.set_title(f"{mat} | {reg} (no data)")
                ax.grid(alpha=0.25)
                continue
            sub = sub.sort_values("year")
            ax.plot(
                sub["year"],
                sub["observed_value"],
                color="#111111",
                linewidth=1.8,
                label="Observed",
            )
            ax.plot(
                sub["year"],
                sub["baseline_model_value"],
                color="#d97706",
                linestyle="--",
                linewidth=1.4,
                label=baseline_label,
            )
            ax.plot(
                sub["year"],
                sub["calibrated_model_value"],
                color="#0369a1",
                linewidth=1.5,
                label=calibrated_label,
            )
            ax.set_title(f"{mat} | {reg}", fontsize=9)
            ax.grid(alpha=0.25)
            if j == 0:
                ax.set_ylabel(ylabel)
            if i == n_rows - 1:
                ax.set_xlabel("Year")

    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(0.5, 1.02))
    fig.suptitle(title, y=1.06, fontsize=12)
    fig.tight_layout()
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _iter_materials(cfg) -> List[str]:
    return [m.name for m in cfg.dimensions.materials]


def _iter_regions(cfg) -> List[str]:
    return list(cfg.dimensions.regions)


def main() -> int:
    ap = argparse.ArgumentParser(description="Visual comparison of observed exogenous vs modeled series.")
    ap.add_argument("--config", default="configs/runs/mvp.yml")
    ap.add_argument("--phase", default="calibration", choices=["calibration", "reporting", "full"])
    ap.add_argument("--baseline-run", default=None, help="Path to baseline run directory.")
    ap.add_argument("--calibrated-run", default=None, help="Path to calibrated run directory.")
    ap.add_argument("--baseline-variant", default="baseline", help="Variant name for baseline modeled series.")
    ap.add_argument("--calibrated-variant", default="calibrated", help="Variant name for calibrated modeled series.")
    ap.add_argument(
        "--run-root",
        default="outputs/runs",
        help="Root where run folders are searched (new layout: outputs/runs/<config_stem>/<variant>/<timestamp>).",
    )
    ap.add_argument(
        "--baseline-calibration-run",
        default=None,
        help="Path to baseline calibration-phase run directory (used when --phase full).",
    )
    ap.add_argument(
        "--baseline-reporting-run",
        default=None,
        help="Path to baseline reporting-phase run directory (used when --phase full).",
    )
    ap.add_argument(
        "--calibrated-calibration-run",
        default=None,
        help="Path to calibrated calibration-phase run directory (used when --phase full).",
    )
    ap.add_argument(
        "--calibrated-reporting-run",
        default=None,
        help="Path to calibrated reporting-phase run directory (used when --phase full).",
    )
    ap.add_argument(
        "--calibration-run-root",
        default="outputs/runs",
        help="Root containing calibration-phase runs (used when --phase full).",
    )
    ap.add_argument(
        "--reporting-run-root",
        default="outputs/runs",
        help="Root containing reporting-phase runs (used when --phase full).",
    )
    ap.add_argument("--year-start", type=int, default=None, help="Optional inclusive start year filter.")
    ap.add_argument("--year-end", type=int, default=None, help="Optional inclusive end year filter.")
    ap.add_argument(
        "--baseline-stage-yields-file",
        default=None,
        help="Optional stage_yields_losses file to use for baseline proxy reconstruction.",
    )
    ap.add_argument(
        "--calibrated-stage-yields-file",
        default=None,
        help="Optional stage_yields_losses file to use for calibrated proxy reconstruction.",
    )
    ap.add_argument("--outdir", default="outputs/analysis/observed_vs_model_comparison")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = load_run_config(cfg_path)
    repo_root = resolve_repo_root_from_config(cfg_path)
    config_stem = cfg_path.stem

    if args.phase == "full":
        if args.baseline_calibration_run:
            baseline_calibration_run = Path(args.baseline_calibration_run).resolve()
        else:
            baseline_calibration_run = _find_latest_variant_run(
                repo_root=repo_root,
                runs_root_arg=args.calibration_run_root,
                config_stem=config_stem,
                variant=args.baseline_variant,
            )
        if args.baseline_reporting_run:
            baseline_reporting_run = Path(args.baseline_reporting_run).resolve()
        else:
            baseline_reporting_run = _find_latest_variant_run(
                repo_root=repo_root,
                runs_root_arg=args.reporting_run_root,
                config_stem=config_stem,
                variant=args.baseline_variant,
            )

        if args.calibrated_calibration_run:
            calibrated_calibration_run = Path(args.calibrated_calibration_run).resolve()
        else:
            calibrated_calibration_run = _find_latest_variant_run(
                repo_root=repo_root,
                runs_root_arg=args.calibration_run_root,
                config_stem=config_stem,
                variant=args.calibrated_variant,
            )
        if args.calibrated_reporting_run:
            calibrated_reporting_run = Path(args.calibrated_reporting_run).resolve()
        else:
            calibrated_reporting_run = _find_latest_variant_run(
                repo_root=repo_root,
                runs_root_arg=args.reporting_run_root,
                config_stem=config_stem,
                variant=args.calibrated_variant,
            )
    else:
        if args.baseline_run:
            baseline_run = Path(args.baseline_run).resolve()
        else:
            baseline_run = _find_latest_variant_run(
                repo_root=repo_root,
                runs_root_arg=args.run_root,
                config_stem=config_stem,
                variant=args.baseline_variant,
            )
        if args.calibrated_run:
            calibrated_run = Path(args.calibrated_run).resolve()
        else:
            calibrated_run = _find_latest_variant_run(
                repo_root=repo_root,
                runs_root_arg=args.run_root,
                config_stem=config_stem,
                variant=args.calibrated_variant,
            )

    vars_ = cfg.variables
    baseline_stage_yields_df = _load_stage_yields(
        cfg, repo_root=repo_root, override_path=args.baseline_stage_yields_file
    )
    calibrated_stage_yields_df = _load_stage_yields(
        cfg,
        repo_root=repo_root,
        override_path=args.calibrated_stage_yields_file or args.baseline_stage_yields_file,
    )
    observed_specs: List[Dict[str, str]] = [
        {
            "observed_id": "stock_in_use",
            "observed_var_key": "stock_in_use",
            "indicator": "Stock_in_use",
            "ylabel": "Stock in use [t]",
        },
        # Useful trade-side comparator: sign and magnitude of exogenous net imports vs modeled usage.
        {
            "observed_id": "primary_refined_net_imports",
            "observed_var_key": "primary_refined_net_imports",
            "indicator": "Primary_refined_net_imports",
            "ylabel": "Net flow [t/year]",
        },
        # Upstream diagnostics: compare observed stage series with stage-consistent modeled proxies.
        {
            "observed_id": "primary_refined_observed",
            "observed_path": "data/exogenous/primary_refined_observed.csv",
            "indicator": "Primary_supply",
            "ylabel": "Flow [t/year]",
        },
        {
            "observed_id": "beneficiation_output_observed",
            "observed_path": "data/exogenous/beneficiation_output_observed.csv",
            "modeled_proxy": "beneficiation_output_proxy",
            "ylabel": "Flow [t/year]",
        },
        {
            "observed_id": "primary_extraction_observed",
            "observed_path": "data/exogenous/primary_extraction_observed.csv",
            "modeled_proxy": "primary_extraction_output_proxy",
            "ylabel": "Flow [t/year]",
        },
    ]

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = (repo_root / args.outdir / stamp).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    materials = _iter_materials(cfg)
    regions = _iter_regions(cfg)
    metrics_rows = []
    selection_rows = []

    for spec in observed_specs:
        observed_key = spec["observed_id"]
        ylabel = spec["ylabel"]
        observed_var_key = spec.get("observed_var_key")
        observed_path = spec.get("observed_path")
        if observed_path:
            obs_path = (repo_root / observed_path).resolve()
        elif observed_var_key and observed_var_key in vars_:
            obs_path = (repo_root / vars_[observed_var_key].path).resolve()
        else:
            continue
        if not obs_path.exists():
            continue

        observed = _load_observed_series(obs_path, observed_key)
        if args.phase == "full":
            baseline_cal = _load_modeled_series(
                run_dir=baseline_calibration_run,
                phase="calibration",
                spec=spec,
                stage_yields_df=baseline_stage_yields_df,
            )
            baseline_rep = _load_modeled_series(
                run_dir=baseline_reporting_run,
                phase="reporting",
                spec=spec,
                stage_yields_df=baseline_stage_yields_df,
            )
            calibrated_cal = _load_modeled_series(
                run_dir=calibrated_calibration_run,
                phase="calibration",
                spec=spec,
                stage_yields_df=calibrated_stage_yields_df,
            )
            calibrated_rep = _load_modeled_series(
                run_dir=calibrated_reporting_run,
                phase="reporting",
                spec=spec,
                stage_yields_df=calibrated_stage_yields_df,
            )
            baseline = _stitch_modeled_series(baseline_cal, baseline_rep)
            calibrated = _stitch_modeled_series(calibrated_cal, calibrated_rep)
        else:
            baseline = _load_modeled_series(
                run_dir=baseline_run,
                phase=args.phase,
                spec=spec,
                stage_yields_df=baseline_stage_yields_df,
            )
            calibrated = _load_modeled_series(
                run_dir=calibrated_run,
                phase=args.phase,
                spec=spec,
                stage_yields_df=calibrated_stage_yields_df,
            )
        joined = _join_series(observed, baseline, calibrated)
        if args.year_start is not None:
            joined = joined[joined["year"] >= args.year_start]
        if args.year_end is not None:
            joined = joined[joined["year"] <= args.year_end]
        joined = joined.sort_values(["material", "region", "year"]).reset_index(drop=True)
        baseline_span = _year_span(baseline)
        calibrated_span = _year_span(calibrated)
        if args.year_start is not None or args.year_end is not None:
            baseline_span = _year_span(joined.dropna(subset=["baseline_model_value"]))
            calibrated_span = _year_span(joined.dropna(subset=["calibrated_model_value"]))

        # Save joined data for transparency.
        joined.to_csv(out_dir / f"{observed_key}__joined.csv", index=False)

        # Fit metrics by material-region for both model variants.
        for mat in materials:
            for reg in regions:
                sub = joined[(joined["material"] == mat) & (joined["region"] == reg)].copy()
                base_sub = sub.dropna(subset=["observed_value", "baseline_model_value"]).rename(
                    columns={"baseline_model_value": "model_value"}
                )
                cal_sub = sub.dropna(subset=["observed_value", "calibrated_model_value"]).rename(
                    columns={"calibrated_model_value": "model_value"}
                )
                if len(base_sub) > 0:
                    m = _fit_metrics(base_sub)
                    metrics_rows.append(
                        {
                            "observed_variable": observed_key,
                            "model_series": "baseline",
                            "material": mat,
                            "region": reg,
                            "n_years": len(base_sub),
                            **m,
                        }
                    )
                if len(cal_sub) > 0:
                    m = _fit_metrics(cal_sub)
                    metrics_rows.append(
                        {
                            "observed_variable": observed_key,
                            "model_series": "calibrated",
                            "material": mat,
                            "region": reg,
                            "n_years": len(cal_sub),
                            **m,
                        }
                    )

        fig_name = f"{observed_key}__observed_vs_modeled__{args.phase}.png"
        _plot_grid(
            joined=joined,
            materials=materials,
            regions=regions,
            title=(
                f"{observed_key}: observed vs modeled ({args.phase})\n"
                f"Modeled periods - baseline: {baseline_span}; calibrated: {calibrated_span}"
            ),
            ylabel=ylabel,
            out_path=out_dir / fig_name,
            baseline_label=f"Modeled baseline ({baseline_span})",
            calibrated_label=f"Modeled calibrated ({calibrated_span})",
        )

    metrics_df = pd.DataFrame(metrics_rows)
    if not metrics_df.empty:
        metrics_df.to_csv(out_dir / "fit_metrics_by_variable_material_region.csv", index=False)
        pivot = metrics_df.pivot_table(
            index=["observed_variable", "material", "region"],
            columns="model_series",
            values=["rmse", "mae", "nrmse_mean"],
        )
        pivot.columns = [f"{a}_{b}" for a, b in pivot.columns]
        pivot = pivot.reset_index()
        if "rmse_baseline" in pivot.columns and "rmse_calibrated" in pivot.columns:
            pivot["rmse_improvement_factor_baseline_over_calibrated"] = (
                pivot["rmse_baseline"] / pivot["rmse_calibrated"]
            )
        if "nrmse_mean_baseline" in pivot.columns and "nrmse_mean_calibrated" in pivot.columns:
            pivot["nrmse_improvement_factor_baseline_over_calibrated"] = (
                pivot["nrmse_mean_baseline"] / pivot["nrmse_mean_calibrated"]
            )
        pivot.to_csv(out_dir / "fit_metrics_comparison_baseline_vs_calibrated.csv", index=False)

    if args.phase == "full":
        selection_rows.append(
            {
                "baseline_calibration_run_dir": str(baseline_calibration_run),
                "baseline_reporting_run_dir": str(baseline_reporting_run),
                "calibrated_calibration_run_dir": str(calibrated_calibration_run),
                "calibrated_reporting_run_dir": str(calibrated_reporting_run),
                "phase": args.phase,
                "year_start": args.year_start,
                "year_end": args.year_end,
                "generated_at": stamp,
            }
        )
    else:
        selection_rows.append(
            {
                "baseline_run_dir": str(baseline_run),
                "calibrated_run_dir": str(calibrated_run),
                "phase": args.phase,
                "year_start": args.year_start,
                "year_end": args.year_end,
                "generated_at": stamp,
            }
        )
    pd.DataFrame(selection_rows).to_csv(out_dir / "run_selection.csv", index=False)

    print(f"Wrote comparison package to: {out_dir}")
    moved = archive_old_timestamped_runs((repo_root / args.outdir).resolve(), keep_last=3)
    if moved:
        print(f"Archived {len(moved)} older run(s) into {(repo_root / args.outdir / '_archive').resolve()}")
    if args.phase == "full":
        print(f"Baseline calibration run:   {baseline_calibration_run}")
        print(f"Baseline reporting run:     {baseline_reporting_run}")
        print(f"Calibrated calibration run: {calibrated_calibration_run}")
        print(f"Calibrated reporting run:   {calibrated_reporting_run}")
    else:
        print(f"Baseline run:   {baseline_run}")
        print(f"Calibrated run: {calibrated_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
