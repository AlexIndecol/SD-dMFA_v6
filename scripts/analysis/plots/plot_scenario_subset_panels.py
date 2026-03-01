#!/usr/bin/env python
"""Visual comparison of precomputed scenario outputs by indicator subsets.

Outputs:
1) subset panel series: one panel per subset (regional detail only)
2) indicator panel series: one panel per indicator (material + regional detail),
   organized in one subfolder per subset
"""

from __future__ import annotations

import argparse
from datetime import datetime
import os
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

# Keep matplotlib caches writable in restricted/sandboxed environments.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CACHE_ROOT = _REPO_ROOT / ".cache"
(_CACHE_ROOT / "matplotlib").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_CACHE_ROOT / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_CACHE_ROOT))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from crm_model.common.io import load_run_config
from crm_model.common.run_layout import (
    latest_timestamp_from_candidate_roots,
    scenario_variant_root_candidates,
)


def _archive_existing_dir(out_dir: Path) -> None:
    """Move an existing populated output dir to sibling archives/<timestamp>."""
    if not out_dir.exists() or not out_dir.is_dir():
        return
    if not any(out_dir.iterdir()):
        return

    archive_root = out_dir.parent / "archives"
    archive_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_dir = archive_root / stamp
    k = 1
    while archive_dir.exists():
        archive_dir = archive_root / f"{stamp}-{k:02d}"
        k += 1
    out_dir.rename(archive_dir)


def _safe_slug(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in text).strip("_")


def _collect_subset_map(cfg) -> Dict[str, List[str]]:
    subset_map: Dict[str, List[str]] = {}
    for group_name in ("mfa_state_and_flow_metrics", "resilience_service_indicators"):
        group = getattr(cfg.indicators, group_name)
        for subset_name, indicators in group.logical_subsets.items():
            subset_map[subset_name] = list(indicators)
    return subset_map


def _prefer_reporting_phase(df: pd.DataFrame, *, phase_col: str = "phase") -> pd.DataFrame:
    if phase_col not in df.columns or df.empty:
        return df
    phases = set(df[phase_col].dropna().astype(str).unique().tolist())
    if "reporting" in phases:
        sub = df[df[phase_col] == "reporting"].copy()
        if not sub.empty:
            return sub
    return df


def _load_latest_precomputed_outputs(
    *,
    output_root: Path,
    config_stem: str,
    variants: List[str],
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ts_rows: List[pd.DataFrame] = []
    scalar_rows: List[pd.DataFrame] = []
    source_rows: List[Dict[str, str]] = []

    for variant in variants:
        candidate_roots = scenario_variant_root_candidates(output_root, config_stem, variant)
        run_dir = latest_timestamp_from_candidate_roots(candidate_roots)
        if run_dir is None:
            continue

        ts_path = run_dir / "indicators" / "timeseries.csv"
        scalar_path = run_dir / "indicators" / "scalar_metrics.csv"

        if ts_path.exists():
            dft = pd.read_csv(ts_path)
            dft["variant"] = variant
            ts_rows.append(dft)
        if scalar_path.exists():
            dfs = pd.read_csv(scalar_path)
            dfs["variant"] = variant
            scalar_rows.append(dfs)

        source_rows.append(
            {
                "variant": variant,
                "run_dir": str(run_dir),
                "timeseries_csv": str(ts_path if ts_path.exists() else ""),
                "scalar_metrics_csv": str(scalar_path if scalar_path.exists() else ""),
            }
        )

    ts_df = pd.concat(ts_rows, ignore_index=True) if ts_rows else pd.DataFrame()
    scalar_df = pd.concat(scalar_rows, ignore_index=True) if scalar_rows else pd.DataFrame()
    source_df = pd.DataFrame(source_rows)
    return ts_df, scalar_df, source_df


def _indicator_source(indicator: str, ts_df: pd.DataFrame, scalar_df: pd.DataFrame) -> str:
    if not ts_df.empty and indicator in set(ts_df["indicator"].astype(str).unique()):
        return "timeseries"
    if not scalar_df.empty and indicator in set(scalar_df["metric"].astype(str).unique()):
        return "scalar"
    return "missing"


def _subset_cell_timeseries(
    *,
    indicator: str,
    region: str,
    ts_df: pd.DataFrame,
    scalar_df: pd.DataFrame,
    year_min: int,
    year_max: int,
) -> Tuple[str, pd.DataFrame]:
    """Return (source, dataframe) for one subset grid cell.

    source:
    - "timeseries": df has columns [variant, year, value]
    - "scalar": df has columns [variant, value] (will be drawn as flat lines)
    - "missing": empty df
    """
    ts_sub = ts_df[(ts_df["indicator"] == indicator) & (ts_df["region"] == region)].copy() if not ts_df.empty else pd.DataFrame()
    if not ts_sub.empty:
        ts_sub = _prefer_reporting_phase(ts_sub, phase_col="phase")
        ts_sub = (
            ts_sub.groupby(["variant", "year"], as_index=False)["value"]
            .mean()
            .sort_values(["variant", "year"])
        )
        return "timeseries", ts_sub

    sc_sub = scalar_df[(scalar_df["metric"] == indicator) & (scalar_df["region"] == region)].copy() if not scalar_df.empty else pd.DataFrame()
    if not sc_sub.empty:
        sc_sub = _prefer_reporting_phase(sc_sub, phase_col="phase")
        sc_sub = sc_sub.groupby(["variant"], as_index=False)["value"].mean()
        sc_sub["year_start"] = year_min
        sc_sub["year_end"] = year_max
        return "scalar", sc_sub

    return "missing", pd.DataFrame()


def _plot_subset_panel_series(
    *,
    subset_map: Dict[str, List[str]],
    ts_df: pd.DataFrame,
    scalar_df: pd.DataFrame,
    variants: List[str],
    regions: List[str],
    year_min: int,
    year_max: int,
    out_dir: Path,
) -> pd.DataFrame:
    out_dir.mkdir(parents=True, exist_ok=True)
    coverage_rows: List[Dict[str, object]] = []

    for subset_name, indicators in subset_map.items():
        if not indicators:
            coverage_rows.append(
                {
                    "subset": subset_name,
                    "configured_indicator_count": 0,
                    "plotted_indicator_count": 0,
                    "panel_png": "",
                    "matrix_raw_csv": "",
                    "matrix_normalized_csv": "",
                }
            )
            continue

        subset_slug = _safe_slug(subset_name)
        panel_png = out_dir / f"subset_panel__{subset_slug}.png"
        raw_csv = out_dir / f"subset_panel__{subset_slug}__matrix_raw.csv"
        norm_csv = out_dir / f"subset_panel__{subset_slug}__matrix_normalized.csv"

        # Requested structure: rows=indicators, cols=regions, scenario lines in each cell.
        fig, axes = plt.subplots(
            nrows=len(indicators),
            ncols=len(regions),
            figsize=(4.3 * len(regions), max(2.0 * len(indicators), 6.0)),
            squeeze=False,
            sharex=False,
        )
        cmap = plt.get_cmap("tab10")
        color_by_variant = {v: cmap(i % 10) for i, v in enumerate(variants)}

        # Also build matrix snapshots (mean over time) for diagnostics.
        raw_rows: List[Dict[str, object]] = []
        norm_rows: List[Dict[str, object]] = []
        plotted_count = 0

        for i, indicator in enumerate(indicators):
            for j, region in enumerate(regions):
                ax = axes[i][j]
                source, cell = _subset_cell_timeseries(
                    indicator=indicator,
                    region=region,
                    ts_df=ts_df,
                    scalar_df=scalar_df,
                    year_min=year_min,
                    year_max=year_max,
                )
                if source == "missing" or cell.empty:
                    ax.text(0.5, 0.5, "NA", ha="center", va="center", transform=ax.transAxes, fontsize=8)
                    ax.set_xticks([])
                    ax.grid(alpha=0.18)
                    continue

                plotted_count += 1
                values_for_norm: List[float] = []
                by_variant_mean: Dict[str, float] = {}
                for variant in variants:
                    if source == "timeseries":
                        d = cell[cell["variant"] == variant]
                        if d.empty:
                            continue
                        ax.plot(
                            d["year"],
                            d["value"],
                            linewidth=1.25,
                            label=variant,
                            color=color_by_variant[variant],
                        )
                        m = float(d["value"].mean())
                    else:
                        d = cell[cell["variant"] == variant]
                        if d.empty:
                            continue
                        yv = float(d["value"].iloc[0])
                        ax.plot(
                            [year_min, year_max],
                            [yv, yv],
                            linewidth=1.25,
                            label=variant,
                            color=color_by_variant[variant],
                        )
                        m = yv
                    by_variant_mean[variant] = m
                    values_for_norm.append(m)

                # Diagnostics matrices (mean over time if timeseries).
                if values_for_norm:
                    vmin = min(values_for_norm)
                    vmax = max(values_for_norm)
                else:
                    vmin = 0.0
                    vmax = 0.0

                for variant in variants:
                    m = by_variant_mean.get(variant, np.nan)
                    if np.isfinite(m) and vmax > vmin:
                        m_norm = (m - vmin) / (vmax - vmin)
                    elif np.isfinite(m):
                        m_norm = 0.0
                    else:
                        m_norm = np.nan
                    raw_rows.append({"indicator": indicator, "region": region, "variant": variant, "value": m})
                    norm_rows.append({"indicator": indicator, "region": region, "variant": variant, "value": m_norm})

                if i == 0:
                    ax.set_title(region, fontsize=9)
                if j == 0:
                    ax.set_ylabel(indicator, fontsize=8)
                if i == len(indicators) - 1:
                    ax.set_xlabel("Year")
                ax.grid(alpha=0.2)

        raw_df = pd.DataFrame(raw_rows)
        norm_df = pd.DataFrame(norm_rows)
        if not raw_df.empty:
            raw_wide = raw_df.pivot_table(index="indicator", columns=["region", "variant"], values="value", aggfunc="mean")
            raw_wide.to_csv(raw_csv)
        else:
            pd.DataFrame().to_csv(raw_csv)
        if not norm_df.empty:
            norm_wide = norm_df.pivot_table(index="indicator", columns=["region", "variant"], values="value", aggfunc="mean")
            norm_wide.to_csv(norm_csv)
        else:
            pd.DataFrame().to_csv(norm_csv)

        handles, labels = axes[0][0].get_legend_handles_labels()
        # Keep title and legend separated; reserve top space explicitly to avoid overlap.
        fig.suptitle(
            f"{subset_name}: rows=indicators, cols=regions, scenario lines",
            y=0.995,
            fontsize=11,
        )
        if handles:
            fig.legend(
                handles,
                labels,
                loc="upper center",
                bbox_to_anchor=(0.5, 0.962),
                ncol=min(len(labels), 6),
                frameon=False,
            )
        fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.90])
        fig.savefig(panel_png, dpi=180, bbox_inches="tight")
        plt.close(fig)

        coverage_rows.append(
            {
                "subset": subset_name,
                "configured_indicator_count": len(indicators),
                "plotted_indicator_count": plotted_count,
                "panel_png": str(panel_png),
                "matrix_raw_csv": str(raw_csv),
                "matrix_normalized_csv": str(norm_csv),
            }
        )

    return pd.DataFrame(coverage_rows)


def _plot_timeseries_indicator_panel(
    *,
    indicator: str,
    df: pd.DataFrame,
    variants: List[str],
    materials: List[str],
    regions: List[str],
    out_path: Path,
) -> None:
    fig, axes = plt.subplots(
        nrows=len(materials),
        ncols=len(regions),
        figsize=(4.1 * len(regions), 2.7 * len(materials)),
        squeeze=False,
        sharex=True,
    )
    cmap = plt.get_cmap("tab10")
    color_by_variant = {v: cmap(i % 10) for i, v in enumerate(variants)}

    for i, material in enumerate(materials):
        for j, region in enumerate(regions):
            ax = axes[i][j]
            cell = df[(df["material"] == material) & (df["region"] == region)].copy()
            for variant in variants:
                d = cell[cell["variant"] == variant]
                if d.empty:
                    continue
                ax.plot(
                    d["year"],
                    d["value"],
                    linewidth=1.35,
                    label=variant,
                    color=color_by_variant[variant],
                )
            if i == 0:
                ax.set_title(region, fontsize=9)
            if j == 0:
                ax.set_ylabel(material, fontsize=9)
            if i == len(materials) - 1:
                ax.set_xlabel("Year")
            ax.grid(alpha=0.2)

    handles, labels = axes[0][0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="upper center", ncol=min(len(labels), 6), frameon=False)
    fig.suptitle(f"{indicator} (timeseries) | material + regional detail", y=1.01, fontsize=11)
    fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.95])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=170, bbox_inches="tight")
    plt.close(fig)


def _plot_scalar_indicator_panel(
    *,
    indicator: str,
    df: pd.DataFrame,
    variants: List[str],
    materials: List[str],
    regions: List[str],
    out_path: Path,
) -> None:
    fig, axes = plt.subplots(
        nrows=len(materials),
        ncols=len(regions),
        figsize=(3.7 * len(regions), 2.7 * len(materials)),
        squeeze=False,
        sharex=True,
    )
    cmap = plt.get_cmap("tab10")
    color_by_variant = {v: cmap(i % 10) for i, v in enumerate(variants)}
    x = np.arange(len(variants), dtype=float)

    for i, material in enumerate(materials):
        for j, region in enumerate(regions):
            ax = axes[i][j]
            vals = []
            for variant in variants:
                hit = df[(df["material"] == material) & (df["region"] == region) & (df["variant"] == variant)]
                vals.append(float(hit["value"].mean()) if not hit.empty else np.nan)
            bars = ax.bar(x, vals, color=[color_by_variant[v] for v in variants], width=0.72)
            if i == 0:
                ax.set_title(region, fontsize=9)
            if j == 0:
                ax.set_ylabel(material, fontsize=9)
            if i == len(materials) - 1:
                ax.set_xticks(x)
                ax.set_xticklabels(variants, rotation=25, ha="right", fontsize=7)
            else:
                ax.set_xticks([])
            ax.grid(alpha=0.2, axis="y")
            # Avoid bars disappearing when all values are nan.
            if all(np.isnan(v) for v in vals):
                ax.text(0.5, 0.5, "NA", ha="center", va="center", transform=ax.transAxes, fontsize=8)
            for b in bars:
                b.set_alpha(0.95)

    fig.suptitle(f"{indicator} (scalar) | material + regional detail", y=1.01, fontsize=11)
    fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.95])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=170, bbox_inches="tight")
    plt.close(fig)


def _plot_indicator_panel_series(
    *,
    subset_map: Dict[str, List[str]],
    ts_df: pd.DataFrame,
    scalar_df: pd.DataFrame,
    variants: List[str],
    materials: List[str],
    regions: List[str],
    out_dir: Path,
) -> pd.DataFrame:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, object]] = []

    for subset_name, indicators in subset_map.items():
        subset_slug = _safe_slug(subset_name)
        subset_dir = out_dir / subset_slug
        subset_dir.mkdir(parents=True, exist_ok=True)

        for indicator in indicators:
            source = _indicator_source(indicator, ts_df=ts_df, scalar_df=scalar_df)
            out_path = subset_dir / f"{_safe_slug(indicator)}.png"
            if source == "timeseries":
                d = ts_df[ts_df["indicator"] == indicator].copy()
                d = _prefer_reporting_phase(d, phase_col="phase")
                _plot_timeseries_indicator_panel(
                    indicator=indicator,
                    df=d,
                    variants=variants,
                    materials=materials,
                    regions=regions,
                    out_path=out_path,
                )
            elif source == "scalar":
                d = scalar_df[scalar_df["metric"] == indicator].copy()
                d = _prefer_reporting_phase(d, phase_col="phase")
                _plot_scalar_indicator_panel(
                    indicator=indicator,
                    df=d,
                    variants=variants,
                    materials=materials,
                    regions=regions,
                    out_path=out_path,
                )
            rows.append(
                {
                    "subset": subset_name,
                    "indicator": indicator,
                    "source": source,
                    "panel_png": str(out_path) if source != "missing" else "",
                }
            )

    return pd.DataFrame(rows)


def _plot_optional_end_use_detail(
    *,
    path: Path,
    variants: List[str],
    out_dir: Path,
) -> int:
    if not path.exists():
        return 0
    df = pd.read_csv(path)
    required = {"scenario", "material", "region", "end_use", "year", "stock_in_use"}
    if not required.issubset(set(df.columns)):
        return 0

    mats = sorted(df["material"].dropna().unique().tolist())
    regs = sorted(df["region"].dropna().unique().tolist())
    end_uses = sorted(df["end_use"].dropna().unique().tolist())
    if not mats or not regs or not end_uses:
        return 0

    count = 0
    for material in mats:
        sub_m = df[df["material"] == material].copy()
        fig, axes = plt.subplots(
            nrows=len(regs),
            ncols=len(end_uses),
            figsize=(2.6 * len(end_uses), 2.2 * len(regs)),
            squeeze=False,
            sharex=True,
        )
        for i, region in enumerate(regs):
            for j, end_use in enumerate(end_uses):
                ax = axes[i][j]
                cell = sub_m[(sub_m["region"] == region) & (sub_m["end_use"] == end_use)]
                for variant in variants:
                    d = cell[cell["scenario"] == variant]
                    if d.empty:
                        continue
                    ax.plot(d["year"], d["stock_in_use"], linewidth=1.15, label=variant)
                if i == 0:
                    ax.set_title(end_use, fontsize=8)
                if j == 0:
                    ax.set_ylabel(region, fontsize=8)
                if i == len(regs) - 1:
                    ax.set_xlabel("Year")
                ax.grid(alpha=0.2)
        handles, labels = axes[0][0].get_legend_handles_labels()
        if handles:
            fig.legend(handles, labels, loc="upper center", ncol=min(len(labels), 6), frameon=False)
        fig.suptitle(f"Stock_in_use end-use detail | material={material}", y=1.01, fontsize=11)
        fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.95])
        out_path = out_dir / f"end_use_detail__stock_in_use__{_safe_slug(material)}.png"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=170, bbox_inches="tight")
        plt.close(fig)
        count += 1
    return count


def main() -> int:
    ap = argparse.ArgumentParser(description="Plot scenario subset panels from precomputed outputs.")
    ap.add_argument("--config", default="configs/runs/mvp.yml")
    ap.add_argument("--output-root", default="outputs/runs")
    ap.add_argument(
        "--outdir",
        default="",
        help=(
            "Output directory. Default: "
            "outputs/analysis/scenario_comparison/<config_stem>/latest/plots"
        ),
    )
    ap.add_argument(
        "--end-use-source",
        default=None,
        help="Optional precomputed end-use CSV (e.g., outputs/analysis/stock_in_use_by_end_use_region_scenarios/<ts>/stock_in_use_by_end_use_region_scenario.csv).",
    )
    ap.add_argument(
        "--archive-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Archive existing output directory into sibling archives/<timestamp> before writing new outputs.",
    )
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = load_run_config(cfg_path)
    config_stem = cfg_path.stem
    variants = list(cfg.variants.keys())
    regions = list(cfg.dimensions.regions)
    materials = [m.name for m in cfg.dimensions.materials]
    subset_map = _collect_subset_map(cfg)

    output_root = Path(args.output_root).resolve()
    if str(args.outdir).strip():
        out_dir = Path(args.outdir).resolve()
    else:
        out_dir = (
            Path("outputs/analysis/scenario_comparison") / config_stem / "latest" / "plots"
        ).resolve()
    if args.archive_existing:
        _archive_existing_dir(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Keep output deterministic: remove prior panel series artifacts in this target folder.
    for p in [out_dir / "subset_panels", out_dir / "indicator_panels", out_dir / "end_use_detail"]:
        if p.exists() and p.is_dir():
            shutil.rmtree(p)
    # Remove legacy artifacts from previous script layout if present.
    for p in [out_dir / "subset_overview_panels.png", out_dir / "subset_coverage.csv"]:
        if p.exists() and p.is_file():
            p.unlink()
    legacy_dir = out_dir / "timeseries_detail"
    if legacy_dir.exists() and legacy_dir.is_dir():
        shutil.rmtree(legacy_dir)

    ts_df, scalar_df, source_df = _load_latest_precomputed_outputs(
        output_root=output_root,
        config_stem=config_stem,
        variants=variants,
    )
    if ts_df.empty and scalar_df.empty:
        raise SystemExit("No precomputed scenario indicator outputs found.")

    year_min = int(min(cfg.time.report_years))
    year_max = int(max(cfg.time.report_years))

    subset_coverage_df = _plot_subset_panel_series(
        subset_map=subset_map,
        ts_df=ts_df,
        scalar_df=scalar_df,
        variants=variants,
        regions=regions,
        year_min=year_min,
        year_max=year_max,
        out_dir=out_dir / "subset_panels",
    )

    indicator_coverage_df = _plot_indicator_panel_series(
        subset_map=subset_map,
        ts_df=ts_df,
        scalar_df=scalar_df,
        variants=variants,
        materials=materials,
        regions=regions,
        out_dir=out_dir / "indicator_panels",
    )

    end_use_count = 0
    end_use_path = None
    if args.end_use_source:
        end_use_path = Path(args.end_use_source).resolve()
        end_use_count = _plot_optional_end_use_detail(
            path=end_use_path,
            variants=variants,
            out_dir=out_dir / "end_use_detail",
        )

    source_df.to_csv(out_dir / "source_runs.csv", index=False)
    subset_coverage_df.to_csv(out_dir / "subset_panel_coverage.csv", index=False)
    indicator_coverage_df.to_csv(out_dir / "indicator_panel_coverage.csv", index=False)
    meta = pd.DataFrame(
        [
            {
                "config_path": str(cfg_path),
                "variants": ",".join(variants),
                "subset_count": len(subset_map),
                "timeseries_rows": len(ts_df),
                "scalar_rows": len(scalar_df),
                "subset_panel_dir": str((out_dir / "subset_panels").resolve()),
                "indicator_panel_dir": str((out_dir / "indicator_panels").resolve()),
                "end_use_source": str(end_use_path) if end_use_path else "",
                "end_use_detail_plot_count": end_use_count,
            }
        ]
    )
    meta.to_csv(out_dir / "selection.csv", index=False)

    print(f"Wrote subset panel series: {out_dir / 'subset_panels'}")
    print(f"Wrote indicator panel series: {out_dir / 'indicator_panels'}")
    if args.end_use_source:
        print(f"Wrote end-use detail plots: {end_use_count}")
    else:
        print("End-use detail skipped (no --end-use-source provided).")
    print(f"Wrote metadata package: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
