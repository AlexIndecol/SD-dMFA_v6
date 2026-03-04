#!/usr/bin/env python
"""Warn on scenario-vs-baseline drift before report_start_year.

This checker is warning-only: it always exits with code 0.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd

from crm_model.common.io import load_run_config, resolve_repo_root_from_config
from crm_model.common.run_layout import (
    archive_old_timestamped_runs,
    latest_timestamp_from_candidate_roots,
    scenario_variant_root_candidates,
)


def _load_timeseries(run_dir: Path) -> pd.DataFrame:
    ts_path = run_dir / "indicators" / "timeseries.csv"
    if not ts_path.exists():
        raise FileNotFoundError(f"Missing timeseries CSV: {ts_path}")
    df = pd.read_csv(ts_path)
    required = {"year", "material", "region", "indicator", "value"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in {ts_path}: {sorted(missing)}")
    return df


def _runtime_impact_mask(indicator: pd.Series) -> pd.Series:
    # Keep model-runtime indicators, drop observed/reference overlays.
    return ~indicator.astype(str).str.startswith("Observed_")


def _latest_run_dir_for_variant(
    *,
    base_runs_root: Path,
    config_stem: str,
    variant: str,
) -> Path | None:
    candidates = scenario_variant_root_candidates(base_runs_root, config_stem, variant)
    return latest_timestamp_from_candidate_roots(candidates)


def _collect_drift_rows(
    *,
    scenario_ts: pd.DataFrame,
    baseline_ts: pd.DataFrame,
    report_start_year: int,
    tolerance: float,
    scenario: str,
    scenario_run_id: str,
    baseline_run_id: str,
) -> pd.DataFrame:
    key_cols = ["year", "material", "region", "indicator"]
    scen_pre = scenario_ts[scenario_ts["year"] < int(report_start_year)][key_cols + ["value"]].rename(
        columns={"value": "scenario_value"}
    )
    base_pre = baseline_ts[baseline_ts["year"] < int(report_start_year)][key_cols + ["value"]].rename(
        columns={"value": "baseline_value"}
    )
    merged = scen_pre.merge(base_pre, on=key_cols, how="inner")
    if merged.empty:
        return pd.DataFrame(
            columns=key_cols
            + ["scenario_value", "baseline_value", "abs_diff", "scenario", "scenario_run_id", "baseline_run_id"]
        )

    merged = merged[_runtime_impact_mask(merged["indicator"])].copy()
    if merged.empty:
        return merged

    merged["abs_diff"] = (merged["scenario_value"].astype(float) - merged["baseline_value"].astype(float)).abs()
    merged = merged[merged["abs_diff"] > float(tolerance)].copy()
    if merged.empty:
        return merged

    merged["scenario"] = str(scenario)
    merged["scenario_run_id"] = str(scenario_run_id)
    merged["baseline_run_id"] = str(baseline_run_id)
    return merged.sort_values("abs_diff", ascending=False).reset_index(drop=True)


def _summarize_drift(drift_rows: pd.DataFrame) -> pd.DataFrame:
    if drift_rows.empty:
        return pd.DataFrame(
            columns=[
                "scenario",
                "max_abs_diff",
                "rows_over_tolerance",
                "worst_indicator",
                "worst_material",
                "worst_region",
                "worst_year",
            ]
        )

    out_rows: List[Dict[str, object]] = []
    for scenario, grp in drift_rows.groupby("scenario", sort=True):
        worst = grp.sort_values("abs_diff", ascending=False).iloc[0]
        out_rows.append(
            {
                "scenario": scenario,
                "max_abs_diff": float(worst["abs_diff"]),
                "rows_over_tolerance": int(len(grp)),
                "worst_indicator": str(worst["indicator"]),
                "worst_material": str(worst["material"]),
                "worst_region": str(worst["region"]),
                "worst_year": int(worst["year"]),
            }
        )
    return pd.DataFrame(out_rows).sort_values("max_abs_diff", ascending=False).reset_index(drop=True)


def _variant_ids(cfg) -> Iterable[str]:
    return list(cfg.variants.keys())


def main() -> int:
    ap = argparse.ArgumentParser(description="Warning-only checker for reporting pre-period drift.")
    ap.add_argument("--config", default="configs/runs/mvp.yml")
    ap.add_argument("--run-root", default="outputs/runs")
    ap.add_argument("--output-root", default="outputs/analysis/preperiod_drift_warnings")
    ap.add_argument("--baseline-variant", default="baseline")
    ap.add_argument("--tolerance", type=float, default=1e-9)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = load_run_config(cfg_path)
    repo_root = resolve_repo_root_from_config(cfg_path)
    config_stem = cfg_path.stem

    report_start_year = int(cfg.time.report_start_year)
    base_runs_root = (repo_root / args.run_root).resolve()

    baseline_variant = str(args.baseline_variant)
    baseline_run = _latest_run_dir_for_variant(
        base_runs_root=base_runs_root,
        config_stem=config_stem,
        variant=baseline_variant,
    )
    if baseline_run is None:
        print(
            f"WARNING: baseline run not found for variant={baseline_variant!r} under {base_runs_root}; "
            "skipping drift check."
        )
        return 0

    baseline_ts = _load_timeseries(baseline_run)
    all_rows: List[pd.DataFrame] = []
    missing_variants: List[str] = []
    for variant in _variant_ids(cfg):
        if variant == baseline_variant:
            continue
        run_dir = _latest_run_dir_for_variant(
            base_runs_root=base_runs_root,
            config_stem=config_stem,
            variant=variant,
        )
        if run_dir is None:
            missing_variants.append(variant)
            continue
        scenario_ts = _load_timeseries(run_dir)
        rows = _collect_drift_rows(
            scenario_ts=scenario_ts,
            baseline_ts=baseline_ts,
            report_start_year=report_start_year,
            tolerance=float(args.tolerance),
            scenario=variant,
            scenario_run_id=run_dir.name,
            baseline_run_id=baseline_run.name,
        )
        if not rows.empty:
            all_rows.append(rows)

    drift_rows = (
        pd.concat(all_rows, ignore_index=True)
        if all_rows
        else pd.DataFrame(
            columns=[
                "year",
                "material",
                "region",
                "indicator",
                "scenario_value",
                "baseline_value",
                "abs_diff",
                "scenario",
                "scenario_run_id",
                "baseline_run_id",
            ]
        )
    )
    summary = _summarize_drift(drift_rows)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = (repo_root / args.output_root / config_stem / stamp).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    drift_csv = out_dir / "preperiod_drift_rows.csv"
    summary_csv = out_dir / "preperiod_drift_summary.csv"
    meta_csv = out_dir / "selection.csv"
    drift_rows.to_csv(drift_csv, index=False)
    summary.to_csv(summary_csv, index=False)
    pd.DataFrame(
        [
            {
                "config": str(cfg_path),
                "runs_root": str(base_runs_root),
                "baseline_variant": baseline_variant,
                "baseline_run_id": baseline_run.name,
                "report_start_year": report_start_year,
                "tolerance": float(args.tolerance),
                "missing_variants": ",".join(missing_variants),
            }
        ]
    ).to_csv(meta_csv, index=False)

    moved = archive_old_timestamped_runs((repo_root / args.output_root / config_stem).resolve(), keep_last=10)
    if moved:
        print(f"Archived {len(moved)} older diagnostics run(s).")

    if missing_variants:
        print(f"WARNING: {len(missing_variants)} variant(s) had no run folder: {', '.join(sorted(missing_variants))}")

    if drift_rows.empty:
        print(
            "OK: no pre-report drift above tolerance "
            f"(year < {report_start_year}, tolerance={float(args.tolerance):.3g})."
        )
    else:
        scenarios_with_drift = int(summary["scenario"].nunique())
        print(
            "WARNING: pre-report drift detected "
            f"for {scenarios_with_drift} scenario(s); see diagnostics CSV."
        )
        top = drift_rows.sort_values("abs_diff", ascending=False).head(max(int(args.top), 1))
        cols = ["scenario", "indicator", "material", "region", "year", "abs_diff"]
        print(top[cols].to_string(index=False))

    print(f"Wrote: {drift_csv}")
    print(f"Wrote: {summary_csv}")
    print(f"Wrote: {meta_csv}")
    # Warning-only checker by design.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
