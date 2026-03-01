from __future__ import annotations

from pathlib import Path
from typing import List

import numpy as np
import pandas as pd

from crm_model.config.io import resolve_repo_root_from_config
from crm_model.config.models import RunConfig
from crm_model.data.io import load_lifetime_distributions, normalize_material, normalize_region


def _repo_root_from_config_path(config_path: Path) -> Path:
    return resolve_repo_root_from_config(config_path)


def validate_exogenous_inputs(cfg: RunConfig, *, repo_root: Path) -> List[str]:
    """Validate exogenous inputs referenced in cfg.variables.

    This is intentionally strict: if required inputs are missing or malformed, stop the run.
    """

    warnings: List[str] = []

    dims = cfg.dimensions
    assert dims is not None
    years = cfg.time.years  # type: ignore[union-attr]

    materials = {m.name for m in dims.materials}
    regions = set(dims.regions)
    end_uses = set(dims.end_uses)
    for var_name, meta in (cfg.variables or {}).items():
        path = (repo_root / meta.path).resolve()
        if meta.required and not path.exists():
            raise FileNotFoundError(f"Required exogenous input missing: {var_name} -> {meta.path}")
        if not path.exists():
            continue

        df = pd.read_csv(path)
        missing_cols = set(meta.columns) - set(df.columns)
        if missing_cols:
            raise ValueError(f"{var_name} is missing columns {sorted(missing_cols)} in {meta.path}")

        # normalize dimension codes (aliases)
        if "material" in df.columns:
            df["material"] = df["material"].astype(str).map(normalize_material)
        if "region" in df.columns:
            df["region"] = df["region"].astype(str).map(normalize_region)

        # basic value checks
        if "value" in df.columns:
            if pd.to_numeric(df["value"], errors="coerce").isna().any():
                raise ValueError(f"{var_name} contains non-numeric values in column 'value' ({meta.path})")

        # dimension member checks
        if "material" in df.columns:
            bad = set(df["material"].astype(str).unique()) - materials
            if bad:
                warnings.append(f"{var_name}: contains materials not in configured dimensions: {sorted(bad)}")
        if "region" in df.columns:
            bad = set(df["region"].astype(str).unique()) - regions
            if bad:
                warnings.append(f"{var_name}: contains regions not in configured dimensions: {sorted(bad)}")
        if "end_use" in df.columns:
            bad = set(df["end_use"].astype(str).unique()) - end_uses
            # we allow extra end uses (e.g., a richer dataset) but warn
            if bad:
                warnings.append(f"{var_name}: contains end_uses not in configured dimensions: {sorted(bad)}")

        # coverage checks
        if var_name in {
            "final_demand",
            "primary_refined_output",
            "primary_refined_net_imports",
            "stage_yields_losses",
            "collection_routing_rates",
            "remanufacturing_end_use_eligibility",
            "end_use_shares",
            "service_activity",
            "material_intensity",
        }:
            ycol = "year"
            ymin = int(df[ycol].min())
            ymax = int(df[ycol].max())
            if ymin > years[0] or ymax < years[-1]:
                raise ValueError(
                    f"{var_name} year coverage {ymin}-{ymax} does not cover scenario years {years[0]}-{years[-1]}"
                )

        if var_name == "stock_in_use":
            ycol = "year"
            ymin = int(df[ycol].min())
            ymax = int(df[ycol].max())
            cal_end = int(cfg.time.calibration_end_year)  # type: ignore[union-attr]
            if ymin > years[0] or ymax < cal_end:
                raise ValueError(
                    f"stock_in_use year coverage {ymin}-{ymax} does not cover calibration years {years[0]}-{cal_end}"
                )

        if var_name == "lifetime_distributions":
            # Reuse the strict lifetime loader checks (duplicates and parameterization).
            lt_df = load_lifetime_distributions(path)
            ymin = int(lt_df["cohort_year"].min())
            ymax = int(lt_df["cohort_year"].max())
            if ymin > years[0] or ymax < years[-1]:
                raise ValueError(
                    f"lifetime_distributions cohort_year coverage {ymin}-{ymax} does not cover scenario years {years[0]}-{years[-1]}"
                )

        # variable-specific constraints
        if var_name == "end_use_shares":
            # nonnegative + at least some positive mass per (year, material, region)
            sub = df.copy()
            sub["value"] = pd.to_numeric(sub["value"], errors="coerce")
            if (sub["value"] < 0).any():
                raise ValueError(f"end_use_shares contains negative values ({meta.path})")
            grp = sub.groupby(["year", "material", "region"], as_index=False)["value"].sum()
            if (grp["value"] <= 0).any():
                raise ValueError(
                    "end_use_shares has year/material/region groups that sum to 0; cannot normalize safely."
                )

        if var_name == "collection_routing_rates":
            sub = df.copy()
            for col in ["recycling_rate", "remanufacturing_rate", "disposal_rate"]:
                sub[col] = pd.to_numeric(sub[col], errors="coerce")
                if sub[col].isna().any():
                    raise ValueError(f"collection_routing_rates contains non-numeric values in '{col}' ({meta.path})")
                if (sub[col] < 0).any() or (sub[col] > 1).any():
                    raise ValueError(f"collection_routing_rates.{col} must be in [0,1] for all rows ({meta.path})")

            sums = (
                sub["recycling_rate"].astype(float)
                + sub["remanufacturing_rate"].astype(float)
                + sub["disposal_rate"].astype(float)
            )
            bad_sum = sub.loc[(sums - 1.0).abs() > 1e-9, ["year", "material", "region"]].head(10)
            if not bad_sum.empty:
                raise ValueError(
                    "collection_routing_rates must satisfy recycling_rate + remanufacturing_rate + disposal_rate = 1 "
                    "per (year,material,region). Examples:\n"
                    + bad_sum.to_string(index=False)
                )

        if var_name == "stage_yields_losses":
            sub = df.copy()
            cols = [
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
            for col in cols:
                sub[col] = pd.to_numeric(sub[col], errors="coerce")
                if sub[col].isna().any():
                    raise ValueError(f"stage_yields_losses contains non-numeric values in '{col}' ({meta.path})")
                if (sub[col] < 0).any() or (sub[col] > 1).any():
                    raise ValueError(f"stage_yields_losses.{col} must be in [0,1] for all rows ({meta.path})")

            reject_sum = (
                sub["sorting_reject_to_disposal_share"].astype(float)
                + sub["sorting_reject_to_sysenv_share"].astype(float)
            )
            bad_reject = sub.loc[(reject_sum - 1.0).abs() > 1e-9, ["year", "material", "region"]].head(10)
            if not bad_reject.empty:
                raise ValueError(
                    "stage_yields_losses must satisfy sorting_reject_to_disposal_share + "
                    "sorting_reject_to_sysenv_share = 1 per (year,material,region). Examples:\n"
                    + bad_reject.to_string(index=False)
                )

            # Stage-throughput reconstruction sanity against refining anchor.
            # Uses primary_refined_output (+ optional primary_refined_net_imports) if available.
            vars_map = cfg.variables or {}
            refined_meta = vars_map.get("primary_refined_output")
            if refined_meta is not None:
                refined_path = (repo_root / refined_meta.path).resolve()
                if refined_path.exists():
                    refined = pd.read_csv(refined_path)
                    for c in ["year", "material", "region", "value"]:
                        if c not in refined.columns:
                            raise ValueError(
                                "primary_refined_output must contain columns "
                                "year, material, region, value for stage reconstruction checks."
                            )
                    refined["material"] = refined["material"].astype(str).map(normalize_material)
                    refined["region"] = refined["region"].astype(str).map(normalize_region)
                    refined["value"] = pd.to_numeric(refined["value"], errors="coerce").astype(float)

                    net = None
                    net_meta = vars_map.get("primary_refined_net_imports")
                    if net_meta is not None:
                        net_path = (repo_root / net_meta.path).resolve()
                        if net_path.exists():
                            net = pd.read_csv(net_path)
                            for c in ["year", "material", "region", "value"]:
                                if c not in net.columns:
                                    raise ValueError(
                                        "primary_refined_net_imports must contain columns "
                                        "year, material, region, value for stage reconstruction checks."
                                    )
                            net["material"] = net["material"].astype(str).map(normalize_material)
                            net["region"] = net["region"].astype(str).map(normalize_region)
                            net["value"] = pd.to_numeric(net["value"], errors="coerce").astype(float)

                    sub["key_year"] = sub["year"].astype(int)
                    merge = refined.rename(columns={"value": "primary_refined_output"}).copy()
                    if net is not None:
                        merge = merge.merge(
                            net.rename(columns={"value": "primary_refined_net_imports"}),
                            on=["year", "material", "region"],
                            how="left",
                        )
                        merge["primary_refined_net_imports"] = merge["primary_refined_net_imports"].fillna(0.0)
                    else:
                        merge["primary_refined_net_imports"] = 0.0

                    merged = merge.merge(
                        sub[
                            [
                                "year",
                                "material",
                                "region",
                                "extraction_yield",
                                "beneficiation_yield",
                                "refining_yield",
                            ]
                        ],
                        on=["year", "material", "region"],
                        how="inner",
                    )
                    if not merged.empty:
                        eps = 1.0e-12
                        avail = np.maximum(
                            merged["primary_refined_output"].to_numpy(dtype=float)
                            + merged["primary_refined_net_imports"].to_numpy(dtype=float),
                            0.0,
                        )
                        ry = np.maximum(merged["refining_yield"].to_numpy(dtype=float), eps)
                        by = np.maximum(merged["beneficiation_yield"].to_numpy(dtype=float), eps)
                        ey = np.maximum(merged["extraction_yield"].to_numpy(dtype=float), eps)
                        refining_input = avail / ry
                        beneficiation_input = refining_input / by
                        extraction_input = beneficiation_input / ey
                        if not np.isfinite(refining_input).all() or not np.isfinite(beneficiation_input).all() or not np.isfinite(extraction_input).all():
                            raise ValueError("stage_yields_losses reconstruction produced non-finite upstream throughput values.")

        if var_name == "remanufacturing_end_use_eligibility":
            sub = df.copy()
            sub["value"] = pd.to_numeric(sub["value"], errors="coerce")
            if sub["value"].isna().any():
                raise ValueError(
                    f"remanufacturing_end_use_eligibility contains non-numeric values in 'value' ({meta.path})"
                )
            if (sub["value"] < 0).any() or (sub["value"] > 1).any():
                raise ValueError(
                    "remanufacturing_end_use_eligibility.value must be in [0,1] for all rows "
                    f"({meta.path})"
                )

    return warnings
