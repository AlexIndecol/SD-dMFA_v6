#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from crm_model.common.io import load_run_config
from crm_model.common.run_layout import latest_timestamp_from_candidate_roots, scenario_variant_root_candidates


def _load_latest_outputs_for_config(
    *,
    config_path: Path,
    output_root: Path,
    allow_legacy_layout: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    cfg = load_run_config(config_path)
    config_stem = config_path.stem

    summary_rows: List[pd.DataFrame] = []
    scalar_rows: List[pd.DataFrame] = []
    for variant in cfg.variants.keys():
        candidate_roots = scenario_variant_root_candidates(output_root, config_stem, variant)
        latest = latest_timestamp_from_candidate_roots(candidate_roots)
        if latest is None:
            continue

        summary_path = latest / "summary.csv"
        if summary_path.exists():
            summary_df = pd.read_csv(summary_path)
            summary_df["variant"] = variant
            summary_df["config_stem"] = config_stem
            summary_df["run_dir"] = str(latest)
            summary_rows.append(summary_df)

        scalar_path = latest / "indicators" / "scalar_metrics.csv"
        if scalar_path.exists():
            scalar_df = pd.read_csv(scalar_path)
            scalar_df["variant"] = variant
            scalar_df["config_stem"] = config_stem
            scalar_df["run_dir"] = str(latest)
            scalar_rows.append(scalar_df)

    out_summary = pd.concat(summary_rows, ignore_index=True) if summary_rows else pd.DataFrame()
    out_scalar = pd.concat(scalar_rows, ignore_index=True) if scalar_rows else pd.DataFrame()
    return out_summary, out_scalar


def _to_gate_row(
    *,
    gate_id: str,
    passed: bool,
    observed: Any,
    threshold: str,
    details: str,
) -> Dict[str, Any]:
    return {
        "gate_id": gate_id,
        "passed": bool(passed),
        "observed": observed,
        "threshold": threshold,
        "details": details,
    }


def evaluate_realism_gates(summary_df: pd.DataFrame, scalar_df: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []

    summary = summary_df.copy()
    if "phase" in summary.columns:
        summary = summary[summary["phase"] == "reporting"].copy()

    scalar = scalar_df.copy()
    if "phase" in scalar.columns:
        scalar = scalar[scalar["phase"] == "reporting"].copy()

    baseline = summary[summary["variant"] == "baseline"].copy()
    if baseline.empty:
        rows.append(
            _to_gate_row(
                gate_id="baseline_stress_cap",
                passed=False,
                observed="NA",
                threshold="max final_stress_multiplier <= 3.2",
                details="No baseline reporting rows found.",
            )
        )
    else:
        max_stress = float(baseline["final_stress_multiplier"].max())
        rows.append(
            _to_gate_row(
                gate_id="baseline_stress_cap",
                passed=max_stress <= 3.2,
                observed=round(max_stress, 6),
                threshold="max final_stress_multiplier <= 3.2",
                details="Baseline maximum stress multiplier.",
            )
        )

    # Baseline chronic under-service check for tin-EU27 and nickel-EU27.
    chronic_metric = "Years_below_service_threshold"
    chronic = scalar[(scalar["variant"] == "baseline") & (scalar["metric"] == chronic_metric)].copy()
    chronic_targets = [("tin", "EU27"), ("nickel", "EU27")]
    chronic_parts: List[str] = []
    chronic_ok = True
    for material, region in chronic_targets:
        hit = chronic[(chronic["material"] == material) & (chronic["region"] == region)]
        if hit.empty:
            chronic_ok = False
            chronic_parts.append(f"{material}-{region}=missing")
            continue
        value = float(hit["value"].iloc[-1])
        chronic_ok = chronic_ok and (value <= 60.0)
        chronic_parts.append(f"{material}-{region}={value:.3g}")
    rows.append(
        _to_gate_row(
            gate_id="baseline_chronic_under_service",
            passed=chronic_ok,
            observed="; ".join(chronic_parts) if chronic_parts else "NA",
            threshold="tin-EU27 and nickel-EU27 Years_below_service_threshold <= 60",
            details="Baseline chronic under-service screen.",
        )
    )

    strategic = summary[summary["variant"] == "strategic_reserve_build_release"].copy()
    if strategic.empty:
        rows.append(
            _to_gate_row(
                gate_id="strategic_reserve_iterations",
                passed=False,
                observed="NA",
                threshold="max iterations <= 9",
                details="No strategic_reserve_build_release reporting rows found.",
            )
        )
    else:
        max_iter = int(strategic["iterations"].max())
        rows.append(
            _to_gate_row(
                gate_id="strategic_reserve_iterations",
                passed=max_iter <= 9,
                observed=max_iter,
                threshold="max iterations <= 9",
                details="Convergence iterations in strategic reserve scenario.",
            )
        )

    low = summary[summary["variant"] == "r36_lifetime_reman_low"][["material", "region", "final_stress_multiplier"]].copy()
    high = summary[summary["variant"] == "r36_lifetime_reman_high"][["material", "region", "final_stress_multiplier"]].copy()
    if low.empty or high.empty:
        rows.append(
            _to_gate_row(
                gate_id="r36_monotonicity",
                passed=False,
                observed="NA",
                threshold="high better than low in >= 8/9 slices",
                details="Missing r36_low/high reporting rows.",
            )
        )
    else:
        cmp = high.merge(low, on=["material", "region"], suffixes=("_high", "_low"))
        good = int((cmp["final_stress_multiplier_high"] < cmp["final_stress_multiplier_low"]).sum())
        total = int(len(cmp))
        rows.append(
            _to_gate_row(
                gate_id="r36_monotonicity",
                passed=(good >= 8) and (total >= 9),
                observed=f"{good}/{total}",
                threshold="high better than low in >= 8/9 slices",
                details="Lower final_stress_multiplier is considered better.",
            )
        )

    r_variants = summary[(summary["variant"] != "baseline") & (summary["variant"].str.startswith("r"))].copy()
    if r_variants.empty or "final_bottleneck_pressure_mean" not in r_variants.columns:
        rows.append(
            _to_gate_row(
                gate_id="r_strategy_bottleneck_activation",
                passed=False,
                observed="NA",
                threshold=">=1 variant with mean final_bottleneck_pressure_mean > 0.01",
                details="Missing r-strategies reporting rows or bottleneck metric.",
            )
        )
    else:
        by_variant = (
            r_variants.groupby("variant", as_index=False)["final_bottleneck_pressure_mean"]
            .mean()
            .sort_values("final_bottleneck_pressure_mean", ascending=False)
        )
        max_mean = float(by_variant["final_bottleneck_pressure_mean"].max())
        best_variant = str(by_variant.iloc[0]["variant"])
        rows.append(
            _to_gate_row(
                gate_id="r_strategy_bottleneck_activation",
                passed=max_mean > 0.01,
                observed=f"{best_variant}={max_mean:.6f}",
                threshold=">=1 variant with mean final_bottleneck_pressure_mean > 0.01",
                details="Checks whether bottleneck channel activates in at least one r-strategy.",
            )
        )

    if summary.empty or "coupling_converged" not in summary.columns:
        rows.append(
            _to_gate_row(
                gate_id="all_converged",
                passed=False,
                observed="NA",
                threshold="all reporting slices coupling_converged == True",
                details="No reporting summary rows or missing convergence column.",
            )
        )
    else:
        converged = bool(summary["coupling_converged"].fillna(False).astype(bool).all())
        rows.append(
            _to_gate_row(
                gate_id="all_converged",
                passed=converged,
                observed=str(converged),
                threshold="all reporting slices coupling_converged == True",
                details="Global convergence gate.",
            )
        )

    return pd.DataFrame(rows)


def _render_markdown(audit_df: pd.DataFrame) -> str:
    lines: List[str] = ["# Scenario Realism Audit", ""]
    passed = int(audit_df["passed"].astype(bool).sum()) if not audit_df.empty else 0
    total = int(len(audit_df))
    lines.append(f"- Passed gates: **{passed}/{total}**")
    lines.append("")
    lines.append("| Gate | Passed | Observed | Threshold |")
    lines.append("|---|---:|---|---|")
    for row in audit_df.itertuples(index=False):
        mark = "yes" if bool(row.passed) else "no"
        lines.append(f"| {row.gate_id} | {mark} | {row.observed} | {row.threshold} |")
    lines.append("")
    failed = audit_df[~audit_df["passed"].astype(bool)].copy()
    if not failed.empty:
        lines.append("## Failing Gates")
        for row in failed.itertuples(index=False):
            lines.append(f"- `{row.gate_id}`: {row.details}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit realism/stability gates from latest scenario runs.")
    ap.add_argument("--config", action="append", required=True, help="Run config path. Repeat for multiple configs.")
    ap.add_argument("--output-root", default="outputs/runs", help="Root path for run artifacts.")
    ap.add_argument(
        "--outdir",
        default="outputs/analysis/scenario_realism/latest",
        help="Output directory for realism audit artifacts.",
    )
    args = ap.parse_args()

    output_root = Path(args.output_root).resolve()
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    all_summary: List[pd.DataFrame] = []
    all_scalar: List[pd.DataFrame] = []
    for cfg in args.config:
        cfg_path = Path(cfg).resolve()
        summary_df, scalar_df = _load_latest_outputs_for_config(
            config_path=cfg_path,
            output_root=output_root,
            allow_legacy_layout=True,
        )
        if not summary_df.empty:
            all_summary.append(summary_df)
        if not scalar_df.empty:
            all_scalar.append(scalar_df)

    summary = pd.concat(all_summary, ignore_index=True) if all_summary else pd.DataFrame()
    scalar = pd.concat(all_scalar, ignore_index=True) if all_scalar else pd.DataFrame()
    audit = evaluate_realism_gates(summary, scalar)

    csv_path = outdir / "realism_audit.csv"
    md_path = outdir / "realism_summary.md"
    audit.to_csv(csv_path, index=False)
    md_path.write_text(_render_markdown(audit), encoding="utf-8")

    print(f"Wrote {csv_path}")
    print(f"Wrote {md_path}")
    if audit.empty:
        return 1
    return 0 if bool(audit["passed"].astype(bool).all()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
