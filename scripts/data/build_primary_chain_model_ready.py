#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def _read(path: Path, required: list[str]) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = sorted(list(set(required) - set(df.columns)))
    if missing:
        raise ValueError(f"{path} is missing required columns: {missing}")
    return df


def _fill_year_panel(df: pd.DataFrame, value_cols: list[str], years: np.ndarray) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for (material, region), g in df.groupby(["material", "region"], as_index=False):
        g = g.sort_values("year")
        base = pd.DataFrame({"year": years})
        base["material"] = material
        base["region"] = region
        merged = base.merge(g[["year", *value_cols]], on="year", how="left")
        for col in value_cols:
            merged[col] = pd.to_numeric(merged[col], errors="coerce")
            merged[col] = merged[col].interpolate(method="linear", limit_direction="both")
            merged[col] = merged[col].ffill().bfill()
        pieces.append(merged)
    return pd.concat(pieces, ignore_index=True)


def main() -> int:
    p = argparse.ArgumentParser(description="Build model-ready primary-chain exogenous inputs with reconciliation diagnostics.")
    p.add_argument("--primary-refined-output", default="data/exogenous/primary_refined_output.csv")
    p.add_argument("--primary-refined-net-imports", default="data/exogenous/primary_refined_net_imports.csv")
    p.add_argument("--stage-yields-losses", default="data/exogenous/stage_yields_losses.csv")
    p.add_argument("--start-year", type=int, default=1870)
    p.add_argument("--end-year", type=int, default=2100)
    p.add_argument("--output-dir", default="data/exogenous/diagnostics/primary_chain_model_ready")
    p.add_argument("--write-model-ready", action="store_true", help="Overwrite canonical exogenous files with reconciled full-horizon tables.")
    args = p.parse_args()

    refined_path = Path(args.primary_refined_output)
    netimp_path = Path(args.primary_refined_net_imports)
    stage_path = Path(args.stage_yields_losses)

    refined = _read(refined_path, ["year", "material", "region", "value"]).copy()
    netimp = _read(netimp_path, ["year", "material", "region", "value"]).copy()
    stage = _read(
        stage_path,
        [
            "year",
            "material",
            "region",
            "extraction_yield",
            "beneficiation_yield",
            "refining_yield",
            "sorting_yield",
            "extraction_loss_to_sysenv_share",
            "beneficiation_loss_to_sysenv_share",
            "refining_loss_to_sysenv_share",
            "sorting_reject_to_disposal_share",
            "sorting_reject_to_sysenv_share",
        ],
    ).copy()

    for df in [refined, netimp, stage]:
        df["year"] = pd.to_numeric(df["year"], errors="raise").astype(int)
        df["material"] = df["material"].astype(str).str.strip().str.lower()
        df["region"] = df["region"].astype(str).str.strip()

    years = np.arange(int(args.start_year), int(args.end_year) + 1, dtype=int)

    refined_full = _fill_year_panel(refined, ["value"], years)
    netimp_full = _fill_year_panel(netimp, ["value"], years)
    stage_cols = [
        "extraction_yield",
        "beneficiation_yield",
        "refining_yield",
        "sorting_yield",
        "extraction_loss_to_sysenv_share",
        "beneficiation_loss_to_sysenv_share",
        "refining_loss_to_sysenv_share",
        "sorting_reject_to_disposal_share",
        "sorting_reject_to_sysenv_share",
    ]
    stage_full = _fill_year_panel(stage, stage_cols, years)

    # Enforce bounds/normalization for shares and yields.
    for col in stage_cols:
        stage_full[col] = np.clip(stage_full[col].astype(float), 0.0, 1.0)
    reject_sum = stage_full["sorting_reject_to_disposal_share"] + stage_full["sorting_reject_to_sysenv_share"]
    reject_sum = reject_sum.replace(0.0, 1.0)
    stage_full["sorting_reject_to_disposal_share"] = stage_full["sorting_reject_to_disposal_share"] / reject_sum
    stage_full["sorting_reject_to_sysenv_share"] = stage_full["sorting_reject_to_sysenv_share"] / reject_sum

    merged = (
        refined_full.rename(columns={"value": "primary_refined_output"})
        .merge(
            netimp_full.rename(columns={"value": "primary_refined_net_imports"}),
            on=["year", "material", "region"],
            how="left",
        )
        .merge(stage_full, on=["year", "material", "region"], how="left")
    )
    merged["primary_refined_net_imports"] = merged["primary_refined_net_imports"].fillna(0.0)

    eps = 1.0e-12
    merged["primary_available_to_refining"] = np.maximum(
        merged["primary_refined_output"] + merged["primary_refined_net_imports"],
        0.0,
    )
    merged["refining_input_primary"] = merged["primary_available_to_refining"] / np.maximum(merged["refining_yield"], eps)
    merged["beneficiation_output_required"] = merged["refining_input_primary"]
    merged["beneficiation_input_required"] = merged["beneficiation_output_required"] / np.maximum(
        merged["beneficiation_yield"], eps
    )
    merged["extraction_output_required"] = merged["beneficiation_input_required"]
    merged["extraction_input_required"] = merged["extraction_output_required"] / np.maximum(
        merged["extraction_yield"], eps
    )

    merged["extraction_losses"] = merged["extraction_input_required"] - merged["extraction_output_required"]
    merged["beneficiation_losses"] = merged["beneficiation_input_required"] - merged["beneficiation_output_required"]
    merged["refining_losses"] = merged["refining_input_primary"] - merged["primary_available_to_refining"]
    merged["closure_gap"] = np.abs(
        merged["primary_available_to_refining"]
        - merged["refining_input_primary"] * merged["refining_yield"]
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    merged.to_csv(out_dir / "primary_chain_reconciliation.csv", index=False)

    if args.write_model_ready:
        refined_full[["year", "material", "region", "value"]].to_csv(refined_path, index=False)
        netimp_full[["year", "material", "region", "value"]].to_csv(netimp_path, index=False)
        stage_full[["year", "material", "region", *stage_cols]].to_csv(stage_path, index=False)

    print(f"Wrote diagnostics: {out_dir / 'primary_chain_reconciliation.csv'}")
    if args.write_model_ready:
        print(f"Updated model-ready files: {refined_path}, {netimp_path}, {stage_path}")
    else:
        print("Model-ready file overwrite disabled (use --write-model-ready).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
