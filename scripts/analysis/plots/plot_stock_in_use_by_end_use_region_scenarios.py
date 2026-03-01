#!/usr/bin/env python
"""Plot stock-in-use by end-use and region across scenario variants."""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence

import numpy as np
import pandas as pd

# Keep matplotlib cache inside repo to avoid permission/cache issues.
if "MPLCONFIGDIR" not in os.environ:
    _repo_root_guess = Path(__file__).resolve().parents[1]
    _mpl_cache = _repo_root_guess / ".cache" / "matplotlib"
    _mpl_cache.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(_mpl_cache)

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from crm_model.common.io import load_run_config, resolve_repo_root_from_config
from crm_model.common.run_layout import archive_old_timestamped_runs
from crm_model.coupling.runner import run_loose_coupled
from crm_model.data import (
    collection_routing_rates_t,
    end_use_shares_te,
    final_demand_t,
    load_collection_routing_rates,
    load_end_use_shares,
    load_final_demand,
    load_lifetime_distributions,
    load_primary_refined_net_imports,
    load_primary_refined_output,
    load_remanufacturing_end_use_eligibility,
    primary_refined_net_imports_tr,
    primary_refined_output_tr,
    remanufacturing_eligibility_tre,
)
from crm_model.mfa import lifetime_pdf_trea_flodym_adapter
from crm_model.mfa.run_mfa import run_flodym_mfa
from crm_model.sd.params import (
    migrate_legacy_strategy_sd_controls,
    normalize_and_validate_sd_parameters,
)
from crm_model.scenarios import (
    apply_primary_refined_net_imports_shock,
    apply_routing_rate_shocks,
    deep_update,
    resolve_routing_rates,
    resolve_sd_parameters_for_slice,
    resolve_variant_slice_overrides,
)


def _resolve_exogenous_path(repo_root: Path, rel: str) -> Path:
    return (repo_root / rel).resolve()


def _split_end_use_demand_by_year(total: np.ndarray, shares_te: np.ndarray) -> np.ndarray:
    t = len(total)
    arr = np.array(shares_te, dtype=float)
    if arr.ndim != 2 or arr.shape[0] != t:
        raise ValueError(f"end_use_shares_te must have shape (t,e) with t={t}; got {arr.shape}")

    row_sums = arr.sum(axis=1)
    p = arr.shape[1]
    for i in range(t):
        if row_sums[i] > 0:
            arr[i, :] = arr[i, :] / row_sums[i]
        else:
            arr[i, :] = np.ones(p, dtype=float) / p

    return total[:, None] * arr


def _shock_multiplier_series(
    years: Sequence[int],
    recycling_disruption: Dict[str, Any] | None,
) -> np.ndarray:
    mult = np.ones(len(years), dtype=float)
    if not isinstance(recycling_disruption, dict):
        return mult

    start_year = int(recycling_disruption["start_year"])
    duration = int(recycling_disruption["duration_years"])
    level = float(recycling_disruption["multiplier"])
    end_year = start_year + duration

    for i, y in enumerate(years):
        if start_year <= int(y) < end_year:
            mult[i] = level
    return mult


def _as_timeseries(value: Any, *, years: Sequence[int], name: str, default: float) -> np.ndarray:
    if value is None:
        return np.array([float(default)] * len(years), dtype=float)
    if isinstance(value, (list, tuple, np.ndarray)):
        arr = np.array(value, dtype=float).reshape(-1)
        if arr.size != len(years):
            raise ValueError(f"{name} must have length {len(years)}; got {arr.size}.")
        return arr
    return np.array([float(value)] * len(years), dtype=float)


def _collect_stock_rows(
    *,
    cfg,
    repo_root: Path,
    years: List[int],
    report_years: List[int],
    variant_name: str,
) -> pd.DataFrame:
    dims = cfg.dimensions
    assert dims is not None

    service_level_threshold = float(cfg.indicators.service_risk.get("threshold_service_level", 0.95))
    sd_base = normalize_and_validate_sd_parameters(
        cfg.sd_parameters,
        emit_warnings=True,
        context="run sd_parameters",
    )
    mfa_base = cfg.mfa_parameters
    strategy_base = cfg.strategy.model_dump(exclude_none=True, exclude_unset=True)
    shocks_base = cfg.shocks.model_dump(exclude_none=True, exclude_unset=True)

    vars_ = cfg.variables
    demand_df = load_final_demand(_resolve_exogenous_path(repo_root, vars_["final_demand"].path))
    shares_df = load_end_use_shares(_resolve_exogenous_path(repo_root, vars_["end_use_shares"].path))
    prod_df = load_primary_refined_output(_resolve_exogenous_path(repo_root, vars_["primary_refined_output"].path))
    net_imp_df = (
        load_primary_refined_net_imports(_resolve_exogenous_path(repo_root, vars_["primary_refined_net_imports"].path))
        if "primary_refined_net_imports" in vars_
        else None
    )
    routing_rates_df = (
        load_collection_routing_rates(_resolve_exogenous_path(repo_root, vars_["collection_routing_rates"].path))
        if "collection_routing_rates" in vars_
        else None
    )
    reman_eligibility_df = (
        load_remanufacturing_end_use_eligibility(
            _resolve_exogenous_path(repo_root, vars_["remanufacturing_end_use_eligibility"].path)
        )
        if "remanufacturing_end_use_eligibility" in vars_
        else None
    )
    lt_df = load_lifetime_distributions(_resolve_exogenous_path(repo_root, vars_["lifetime_distributions"].path))

    rows: List[pd.DataFrame] = []

    for mat in dims.materials:
        material = mat.name
        for region in dims.regions:
            variant_slice = resolve_variant_slice_overrides(
                cfg=cfg,
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
            sd_params = deep_update(sd_params, variant_slice["sd_parameters"])
            mfa_params = deep_update(mfa_base, variant_slice["mfa_parameters"])
            strategy = deep_update(strategy_base, variant_slice["strategy"])
            shocks = deep_update(shocks_base, variant_slice["shocks"])
            sd_params, strategy = migrate_legacy_strategy_sd_controls(
                sd_parameters=sd_params,
                strategy=strategy,
                emit_warnings=True,
                context=f"variant '{variant_name}'",
            )
            sd_params = normalize_and_validate_sd_parameters(sd_params)
            if years:
                sd_params["start_year"] = int(years[0])
            sd_params["report_start_year"] = cfg.time.report_start_year
            sd_params["report_years"] = report_years

            fd_t = final_demand_t(demand_df, years=years, material=material, region=region)
            sh_te = end_use_shares_te(
                shares_df,
                years=years,
                material=material,
                region=region,
                end_uses=dims.end_uses,
            )

            lt_mult = float(strategy.get("lifetime_multiplier", 1.0) or 1.0)
            lt_pdf = lifetime_pdf_trea_flodym_adapter(
                lt_df,
                years=years,
                material=material,
                regions=[region],
                end_uses=dims.end_uses,
                lifetime_multiplier=lt_mult,
            )
            cap_tr = primary_refined_output_tr(prod_df, years=years, material=material, regions=[region])
            if net_imp_df is not None:
                net_imp_tr = primary_refined_net_imports_tr(
                    net_imp_df, years=years, material=material, regions=[region]
                )
            else:
                net_imp_tr = np.zeros_like(cap_tr)
            net_imp_tr = apply_primary_refined_net_imports_shock(
                primary_refined_net_imports_tr=net_imp_tr,
                years=years,
                shocks=shocks,
            )
            primary_available = np.maximum(cap_tr + net_imp_tr, 0.0)

            mfa_params_it = dict(mfa_params)
            mfa_params_it["lifetime_pdf_trea"] = lt_pdf
            mfa_params_it["primary_available_to_refining"] = primary_available
            mfa_params_it["primary_refined_net_imports"] = net_imp_tr
            if reman_eligibility_df is not None:
                mfa_params_it["remanufacturing_end_use_eligibility_tre"] = remanufacturing_eligibility_tre(
                    reman_eligibility_df,
                    years=years,
                    regions=[region],
                    end_uses=dims.end_uses,
                )
            strategy_it = dict(strategy)
            if routing_rates_df is not None:
                rec_t, rem_t, disp_t = collection_routing_rates_t(
                    routing_rates_df, years=years, material=material, region=region
                )
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

            coupled = run_loose_coupled(
                years=years,
                material=material,
                region=region,
                end_uses=dims.end_uses,
                final_demand_t=fd_t,
                end_use_shares_te=sh_te,
                sd_params=sd_params,
                mfa_params=mfa_params_it,
                mfa_graph=cfg.mfa_graph.model_dump(by_alias=True) if cfg.mfa_graph is not None else None,
                strategy=strategy_it,
                shocks=shocks,
                coupling=cfg.coupling.model_dump() if cfg.coupling else {},
                service_level_threshold=service_level_threshold,
            )

            # Reuse the final SD-native collection multiplier from the coupled run.
            base_collection_rate = _as_timeseries(
                mfa_params_it.get("collection_rate"),
                years=years,
                name="collection_rate",
                default=0.4,
            )
            collection_multiplier = (
                coupled.indicators_ts["Coupling_collection_multiplier"].reindex(years).to_numpy(dtype=float)
            )
            mfa_params_it["collection_rate"] = np.clip(base_collection_rate * collection_multiplier, 0.0, 1.0)

            # Rebuild detailed MFA stock tensor (t,r,e) for plotting by end-use.
            demand_te = _split_end_use_demand_by_year(coupled.sd.demand.to_numpy(dtype=float), sh_te)
            service_demand_tre = demand_te[:, None, :]
            rec_disrupt_mult = _shock_multiplier_series(years, shocks.get("recycling_disruption"))

            mfa_system, _ = run_flodym_mfa(
                years=years,
                regions=[region],
                end_uses=dims.end_uses,
                service_demand_tre=service_demand_tre,
                params=mfa_params_it,
                mfa_graph=cfg.mfa_graph.model_dump(by_alias=True) if cfg.mfa_graph is not None else None,
                strategy=strategy_it,
                shocks={"recycling_disruption_multiplier": rec_disrupt_mult},
            )
            stock_te = mfa_system.parameters["__stock_in_use"].values[:, 0, :]

            long = pd.DataFrame(stock_te, columns=dims.end_uses)
            long["year"] = years
            long = long.melt(id_vars=["year"], var_name="end_use", value_name="stock_in_use")
            long["scenario"] = variant_name
            long["material"] = material
            long["region"] = region
            rows.append(long[["scenario", "material", "region", "end_use", "year", "stock_in_use"]])

    if not rows:
        return pd.DataFrame(columns=["scenario", "material", "region", "end_use", "year", "stock_in_use"])
    return pd.concat(rows, ignore_index=True)


def _plot_material_stacked_lines(
    *,
    data: pd.DataFrame,
    material: str,
    regions: Sequence[str],
    end_uses: Sequence[str],
    scenario_order: Sequence[str],
    out_path: Path,
) -> None:
    sub_m = data[data["material"] == material].copy()
    n_rows = len(scenario_order)
    n_cols = len(regions)
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(4.3 * n_cols, 2.3 * n_rows), sharex=True)

    if n_rows == 1 and n_cols == 1:
        axes = np.array([[axes]])
    elif n_rows == 1:
        axes = np.array([axes])
    elif n_cols == 1:
        axes = np.array([[ax] for ax in axes])

    cmap = plt.get_cmap("tab20")
    colors = {eu: cmap(i % 20) for i, eu in enumerate(end_uses)}

    for i, scenario in enumerate(scenario_order):
        for j, region in enumerate(regions):
            ax = axes[i, j]
            sub = sub_m[(sub_m["scenario"] == scenario) & (sub_m["region"] == region)].copy()
            if sub.empty:
                if i == 0:
                    ax.set_title(region, fontsize=9)
                if j == 0:
                    ax.set_ylabel(f"{scenario}\nStock [t]", fontsize=8)
                ax.grid(alpha=0.25)
                continue

            piv = (
                sub.pivot_table(index="year", columns="end_use", values="stock_in_use", aggfunc="sum")
                .reindex(columns=list(end_uses))
                .fillna(0.0)
                .sort_index()
            )

            years_arr = piv.index.to_numpy(dtype=float)
            vals = piv.to_numpy(dtype=float)
            cumulative = np.cumsum(vals, axis=1)
            lower = np.hstack([np.zeros((len(years_arr), 1), dtype=float), cumulative[:, :-1]])

            for k, end_use in enumerate(end_uses):
                y_top = cumulative[:, k]
                y_low = lower[:, k]
                ax.fill_between(years_arr, y_low, y_top, color=colors.get(end_use, "#999999"), alpha=0.12, linewidth=0.0)
                ax.plot(
                    years_arr,
                    y_top,
                    linewidth=1.0,
                    color=colors.get(end_use, "#666666"),
                )

            if cumulative.shape[1] > 0:
                ax.plot(years_arr, cumulative[:, -1], color="#111111", linewidth=1.25, linestyle="-")

            if i == 0:
                ax.set_title(region, fontsize=9)
            if j == 0:
                ax.set_ylabel(f"{scenario}\nStock [t]", fontsize=8)
            if i == n_rows - 1:
                ax.set_xlabel("Year")
            ax.grid(alpha=0.25)
            ax.tick_params(axis="both", labelsize=8)

    end_use_handles = [
        Line2D([0], [0], color=colors.get(eu, "#666666"), linewidth=2, label=eu.replace("_", " "))
        for eu in end_uses
    ]
    end_use_handles.append(Line2D([0], [0], color="#111111", linewidth=2, label="total stock"))
    fig.legend(
        end_use_handles,
        [h.get_label() for h in end_use_handles],
        loc="upper center",
        ncol=min(4, len(end_use_handles)),
        frameon=False,
        bbox_to_anchor=(0.5, 1.02),
        fontsize=8,
    )
    fig.suptitle(f"Stacked end-use stock-in-use lines by scenario and region | material={material}", y=1.06, fontsize=12)
    fig.tight_layout()
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description="Plot stock-in-use by end-use and region across scenarios.")
    ap.add_argument("--config", default="configs/runs/mvp.yml")
    ap.add_argument("--phase", choices=["reporting", "calibration"], default="reporting")
    ap.add_argument("--variants", nargs="*", default=None, help="Scenario variants to include. Default: all.")
    ap.add_argument("--materials", nargs="*", default=None, help="Materials to include. Default: all.")
    ap.add_argument("--year-start", type=int, default=None)
    ap.add_argument("--year-end", type=int, default=None)
    ap.add_argument("--outdir", default="outputs/analysis/stock_in_use_by_end_use_region_scenarios")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = load_run_config(cfg_path)
    repo_root = resolve_repo_root_from_config(cfg_path)

    time = cfg.time
    dims = cfg.dimensions
    assert time is not None and dims is not None

    if args.phase == "calibration":
        years = list(time.calibration_years)
        report_years: List[int] = []
    else:
        years = list(time.years)
        report_years = list(time.report_years)

    if args.variants:
        bad = [v for v in args.variants if v not in cfg.variants]
        if bad:
            raise ValueError(f"Unknown variants: {bad}. Available: {list(cfg.variants.keys())}")
        variant_order = list(args.variants)
    else:
        variant_order = list(cfg.variants.keys())

    material_filter = set(args.materials) if args.materials else None
    selected_materials = [m.name for m in dims.materials if material_filter is None or m.name in material_filter]
    if material_filter is not None and len(selected_materials) == 0:
        raise ValueError(f"No configured materials matched --materials={sorted(material_filter)}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = (repo_root / args.outdir / stamp).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    all_rows: List[pd.DataFrame] = []
    for variant_name in variant_order:
        print(f"[run] variant={variant_name}")
        df_v = _collect_stock_rows(
            cfg=cfg,
            repo_root=repo_root,
            years=years,
            report_years=report_years,
            variant_name=variant_name,
        )
        all_rows.append(df_v)

    long_df = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
    if material_filter is not None:
        long_df = long_df[long_df["material"].isin(selected_materials)]
    if args.year_start is not None:
        long_df = long_df[long_df["year"] >= int(args.year_start)]
    if args.year_end is not None:
        long_df = long_df[long_df["year"] <= int(args.year_end)]
    long_df = long_df.sort_values(["scenario", "material", "region", "end_use", "year"]).reset_index(drop=True)

    csv_path = out_dir / "stock_in_use_by_end_use_region_scenario.csv"
    long_df.to_csv(csv_path, index=False)

    for material in selected_materials:
        fig_path = out_dir / f"stock_in_use_by_end_use_region__{material}.png"
        _plot_material_stacked_lines(
            data=long_df,
            material=material,
            regions=list(dims.regions),
            end_uses=list(dims.end_uses),
            scenario_order=variant_order,
            out_path=fig_path,
        )

    selection = pd.DataFrame(
        [
            {
                "config_path": str(cfg_path),
                "phase": args.phase,
                "variants": ",".join(variant_order),
                "materials": ",".join(selected_materials),
                "year_start": args.year_start,
                "year_end": args.year_end,
                "generated_at": stamp,
            }
        ]
    )
    selection.to_csv(out_dir / "selection.csv", index=False)

    moved = archive_old_timestamped_runs((repo_root / args.outdir).resolve(), keep_last=3)
    if moved:
        print(f"Archived {len(moved)} older run(s) to: {(repo_root / args.outdir).resolve() / '_archive'}")

    print(f"Wrote package: {out_dir}")
    print(f"Long CSV: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
