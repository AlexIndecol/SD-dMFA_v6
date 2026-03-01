#!/usr/bin/env python
"""Build scenario comparison tables from latest saved run per variant."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd

from crm_model.common.io import load_run_config
from crm_model.common.run_layout import (
    latest_timestamp_from_candidate_roots,
    scenario_variant_root,
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


def _load_latest_variant_summaries(
    *,
    output_root: Path,
    config_stem: str,
    variant_names: List[str],
    allow_legacy_layout: bool,
) -> pd.DataFrame:
    rows: List[pd.DataFrame] = []
    for variant in variant_names:
        if allow_legacy_layout:
            candidate_roots = scenario_variant_root_candidates(output_root, config_stem, variant)
        else:
            candidate_roots = [scenario_variant_root(output_root, config_stem, variant)]
        latest = latest_timestamp_from_candidate_roots(candidate_roots)
        if latest is None:
            continue
        summary_path = latest / "summary.csv"
        if not summary_path.exists():
            continue
        df = pd.read_csv(summary_path)
        df["variant"] = variant
        df["run_dir"] = str(latest)
        rows.append(df)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def _build_delta_vs_baseline(summary_df: pd.DataFrame) -> pd.DataFrame:
    key_cols = ["material", "region"]
    base = (
        summary_df[summary_df["variant"] == "baseline"][
            key_cols
            + [
                "final_service_stress_signal",
                "final_circular_supply_stress_signal",
                "final_stress_multiplier",
            ]
        ]
        .rename(
            columns={
                "final_service_stress_signal": "baseline_service_stress",
                "final_circular_supply_stress_signal": "baseline_circular_supply_stress",
                "final_stress_multiplier": "baseline_stress_multiplier",
            }
        )
        .copy()
    )
    merged = summary_df.merge(base, on=key_cols, how="left")
    merged["delta_service_stress"] = (
        merged["final_service_stress_signal"] - merged["baseline_service_stress"]
    )
    merged["delta_circular_supply_stress"] = (
        merged["final_circular_supply_stress_signal"] - merged["baseline_circular_supply_stress"]
    )
    merged["delta_stress_multiplier"] = (
        merged["final_stress_multiplier"] - merged["baseline_stress_multiplier"]
    )
    return merged


def _build_variant_kpis(summary_df: pd.DataFrame) -> pd.DataFrame:
    return (
        summary_df.groupby("variant", as_index=False)
        .agg(
            avg_final_stress_multiplier=("final_stress_multiplier", "mean"),
            max_final_stress_multiplier=("final_stress_multiplier", "max"),
            avg_service_stress=("final_service_stress_signal", "mean"),
            avg_circular_supply_stress=("final_circular_supply_stress_signal", "mean"),
            converged_all=("coupling_converged", "all"),
        )
        .sort_values("avg_final_stress_multiplier")
        .reset_index(drop=True)
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Create scenario comparison CSV package from latest variant runs.")
    ap.add_argument("--config", default="configs/runs/mvp.yml")
    ap.add_argument("--output-root", default="outputs/runs")
    ap.add_argument(
        "--outdir",
        default="",
        help=(
            "Output directory. Default: outputs/analysis/scenario_comparison/<config_stem>/latest"
        ),
    )
    ap.add_argument(
        "--allow-legacy-layout",
        action="store_true",
        help="Also scan legacy/ad-hoc run folder layouts. Default is strict current layout only.",
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
    variant_names = list(cfg.variants.keys())
    config_stem = cfg_path.stem

    output_root = Path(args.output_root).resolve()
    if str(args.outdir).strip():
        out_dir = Path(args.outdir).resolve()
    else:
        out_dir = (Path("outputs/analysis/scenario_comparison") / config_stem / "latest").resolve()
    if args.archive_existing:
        _archive_existing_dir(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_df = _load_latest_variant_summaries(
        output_root=output_root,
        config_stem=config_stem,
        variant_names=variant_names,
        allow_legacy_layout=bool(args.allow_legacy_layout),
    )
    if summary_df.empty:
        raise SystemExit("No scenario summary.csv files found for configured variants.")

    keep_cols = [
        "variant",
        "phase",
        "material",
        "region",
        "coupling_iterations",
        "final_service_stress_signal",
        "final_circular_supply_stress_signal",
        "final_stress_multiplier",
        "coupling_converged",
        "stock_rmse_calibration",
        "run_dir",
    ]
    keep_cols = [c for c in keep_cols if c in summary_df.columns]
    summary_out = summary_df[keep_cols].sort_values(["variant", "material", "region"]).reset_index(drop=True)

    delta_out = _build_delta_vs_baseline(summary_out)
    kpis_out = _build_variant_kpis(summary_out)

    summary_path = out_dir / "summary_comparison.csv"
    delta_path = out_dir / "delta_vs_baseline.csv"
    kpis_path = out_dir / "scenario_kpis.csv"

    summary_out.to_csv(summary_path, index=False)
    delta_out.to_csv(delta_path, index=False)
    kpis_out.to_csv(kpis_path, index=False)

    meta = pd.DataFrame(
        [
            {
                "config_path": str(cfg_path),
                "config_stem": config_stem,
                "variant_count": len(variant_names),
                "variants": ",".join(variant_names),
                "summary_comparison_csv": str(summary_path),
                "delta_vs_baseline_csv": str(delta_path),
                "scenario_kpis_csv": str(kpis_path),
            }
        ]
    )
    meta.to_csv(out_dir / "selection.csv", index=False)

    print(f"Wrote: {summary_path}")
    print(f"Wrote: {delta_path}")
    print(f"Wrote: {kpis_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
