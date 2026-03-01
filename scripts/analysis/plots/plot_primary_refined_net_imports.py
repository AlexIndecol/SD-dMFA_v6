#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Plot harmonized primary_refined_net_imports time series.")
    p.add_argument(
        "--input",
        type=Path,
        default=Path("data/exogenous/primary_refined_net_imports.csv"),
        help="Primary net imports CSV path.",
    )
    p.add_argument(
        "--extrapolation-meta",
        type=Path,
        default=Path("data/exogenous/diagnostics/primary_refined_net_imports_baci/extrapolation_models.csv"),
        help="Extrapolation metadata CSV for observed window shading.",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/analysis/figures/primary_refined_net_imports"),
        help="Directory to write plots.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # Keep matplotlib cache writable inside repository.
    if "MPLCONFIGDIR" not in os.environ:
        cache_dir = Path(".cache/matplotlib").resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ["MPLCONFIGDIR"] = str(cache_dir)
    os.environ.setdefault("XDG_CACHE_HOME", str(Path(".cache").resolve()))

    import matplotlib.pyplot as plt

    df = pd.read_csv(args.input)
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype(int)
    df["value"] = pd.to_numeric(df["value"], errors="coerce").astype(float)
    df["material"] = df["material"].astype(str).str.lower().str.strip()
    df["region"] = df["region"].astype(str).str.strip()

    if args.extrapolation_meta.exists():
        meta = pd.read_csv(args.extrapolation_meta)
        meta["material"] = meta["material"].astype(str).str.lower().str.strip()
    else:
        meta = pd.DataFrame(columns=["material", "observed_min_year", "observed_max_year"])

    materials = sorted(df["material"].unique().tolist())
    regions = ["EU27", "China", "RoW"]
    colors = {"EU27": "#1f77b4", "China": "#d62728", "RoW": "#2ca02c"}

    args.output_dir.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(len(materials), 1, figsize=(13, 3.8 * len(materials)), sharex=True)
    if len(materials) == 1:
        axes = [axes]

    for ax, material in zip(axes, materials, strict=True):
        sub = df[df["material"] == material].copy()
        for region in regions:
            s = (
                sub[sub["region"] == region]
                .sort_values("year")[["year", "value"]]
                .set_index("year")["value"]
            )
            if len(s) == 0:
                continue
            ax.plot(s.index, s.values, label=region, color=colors[region], linewidth=1.6)

        row = meta[meta["material"] == material]
        if not row.empty:
            obs_min = int(float(row.iloc[0]["observed_min_year"]))
            obs_max = int(float(row.iloc[0]["observed_max_year"]))
            ax.axvspan(obs_min, obs_max, color="#999999", alpha=0.15, label="Observed window")

        ax.axhline(0.0, color="black", linewidth=0.8, alpha=0.6)
        ax.set_ylabel(f"{material.capitalize()} (kt)")
        ax.grid(alpha=0.25)
        ax.legend(loc="upper left", ncol=4, frameon=False)

    axes[-1].set_xlabel("Year")
    fig.suptitle("Primary Net Imports by Material and Region (Contained Metal, kt)", y=0.995, fontsize=13)
    fig.tight_layout()
    out_all = args.output_dir / "primary_refined_net_imports_timeseries.png"
    fig.savefig(out_all, dpi=180)
    plt.close(fig)

    # Near-horizon view for scenario interpretation.
    recent = df[df["year"] >= 1990].copy()
    fig2, axes2 = plt.subplots(len(materials), 1, figsize=(13, 3.8 * len(materials)), sharex=True)
    if len(materials) == 1:
        axes2 = [axes2]

    for ax, material in zip(axes2, materials, strict=True):
        sub = recent[recent["material"] == material].copy()
        for region in regions:
            s = (
                sub[sub["region"] == region]
                .sort_values("year")[["year", "value"]]
                .set_index("year")["value"]
            )
            if len(s) == 0:
                continue
            ax.plot(s.index, s.values, label=region, color=colors[region], linewidth=1.8)

        row = meta[meta["material"] == material]
        if not row.empty:
            obs_min = int(float(row.iloc[0]["observed_min_year"]))
            obs_max = int(float(row.iloc[0]["observed_max_year"]))
            ax.axvspan(obs_min, obs_max, color="#999999", alpha=0.15, label="Observed window")
            ax.axvline(obs_max, color="#555555", linestyle="--", linewidth=1.0, alpha=0.7)

        ax.axhline(0.0, color="black", linewidth=0.8, alpha=0.6)
        ax.set_ylabel(f"{material.capitalize()} (kt)")
        ax.grid(alpha=0.25)
        ax.legend(loc="upper left", ncol=4, frameon=False)

    axes2[-1].set_xlabel("Year")
    fig2.suptitle("Primary Net Imports (1990-2100): Observed vs Extrapolated", y=0.995, fontsize=13)
    fig2.tight_layout()
    out_recent = args.output_dir / "primary_refined_net_imports_1990_2100.png"
    fig2.savefig(out_recent, dpi=180)
    plt.close(fig2)

    print(f"Wrote: {out_all}")
    print(f"Wrote: {out_recent}")


if __name__ == "__main__":
    main()
