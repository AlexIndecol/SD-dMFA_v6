from __future__ import annotations

from pathlib import Path
from typing import Dict, Sequence

import numpy as np
import pandas as pd


def normalize_material(x: str) -> str:
    return str(x).strip().lower()


def normalize_region(x: str) -> str:
    """Normalize region codes using a small alias set.

    Canonical region codes in this template are defined in configs/regions.yml:
    - EU27
    - China
    - RoW

    Accepted aliases include (case-insensitive):
    - EU-27, EU 27, EU_27 -> EU27
    - Rest of the World, ROW -> RoW
    """
    raw = str(x).strip()
    key = ''.join([c for c in raw.lower() if c.isalnum()])

    if key == 'eu27':
        return 'EU27'
    if key in {'china', 'prc', 'peoplesrepublicofchina'}:
        return 'China'
    if key in {'row', 'restoftheworld', 'restofworld'}:
        return 'RoW'

    return raw


def _as_path(p: str | Path) -> Path:
    return p if isinstance(p, Path) else Path(p)


def _read_csv(path: str | Path, required_cols: set[str]) -> pd.DataFrame:
    df = pd.read_csv(_as_path(path))
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"{Path(path)} is missing columns: {sorted(missing)}")
    return df


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Apply canonicalization for known dimension columns.

    This makes the template robust to minor naming variations in exogenous datasets.
    """
    out = df.copy()
    if 'material' in out.columns:
        out['material'] = out['material'].astype(str).map(normalize_material)
    if 'region' in out.columns:
        out['region'] = out['region'].astype(str).map(normalize_region)
    return out

# -------------------------
# End-use shares
# -------------------------

def load_end_use_shares(path: str | Path) -> pd.DataFrame:
    """Long format with `value` as share."""
    df = _normalize_df(_read_csv(path, {"year", "material", "region", "end_use", "value"})).copy()
    df["year"] = df["year"].astype(int)
    df["material"] = df["material"].astype(str)
    df["region"] = df["region"].astype(str)
    df["end_use"] = df["end_use"].astype(str)
    df["value"] = pd.to_numeric(df["value"], errors="coerce").astype(float)

    if df["value"].isna().any():
        bad = df[df["value"].isna()].head(10)
        raise ValueError("End-use shares contain non-numeric values. Examples:\n" + bad.to_string(index=False))
    if (df["value"] < 0).any():
        bad = df[df["value"] < 0].head(10)
        raise ValueError("End-use shares contain negative values. Examples:\n" + bad.to_string(index=False))
    return df


def end_use_shares_te(
    shares_df: pd.DataFrame,
    *,
    years: Sequence[int],
    material: str,
    region: str,
    end_uses: Sequence[str],
    fill_method: str = "ffill",
) -> np.ndarray:
    """Return (t,e) shares. Missing end-uses -> 0, then normalize per year."""
    material = normalize_material(material)
    region = normalize_region(region)
    df = shares_df[(shares_df["material"] == material) & (shares_df["region"] == region)].copy()
    p = len(end_uses) if len(end_uses) else 1

    if df.empty:
        return np.ones((len(years), p), dtype=float) / p

    piv = (
        df.pivot_table(index="year", columns="end_use", values="value", aggfunc="mean")
        .reindex(index=list(years), columns=list(end_uses))
    )
    if fill_method:
        piv = piv.ffill().bfill()
    piv = piv.fillna(0.0)

    arr = piv.to_numpy(dtype=float)
    row_sums = arr.sum(axis=1)
    for i in range(arr.shape[0]):
        if row_sums[i] > 0:
            arr[i, :] = arr[i, :] / row_sums[i]
        else:
            arr[i, :] = np.ones(p, dtype=float) / p
    return arr


# -------------------------
# Simple year-series vars
# -------------------------

def load_year_material_region_series(path: str | Path, *, allow_negative: bool = False) -> pd.DataFrame:
    df = _normalize_df(_read_csv(path, {"year", "material", "region", "value"})).copy()
    df["year"] = df["year"].astype(int)
    df["material"] = df["material"].astype(str)
    df["region"] = df["region"].astype(str)
    df["value"] = pd.to_numeric(df["value"], errors="coerce").astype(float)
    if df["value"].isna().any():
        bad = df[df["value"].isna()].head(10)
        raise ValueError("Series contains non-numeric values. Examples:\n" + bad.to_string(index=False))
    if (not allow_negative) and (df["value"] < 0).any():
        bad = df[df["value"] < 0].head(10)
        raise ValueError("Series contains negative values. Examples:\n" + bad.to_string(index=False))
    return df


def series_t(
    df: pd.DataFrame,
    *,
    years: Sequence[int],
    material: str,
    region: str,
    fill_method: str = "ffill",
) -> np.ndarray:
    material = normalize_material(material)
    region = normalize_region(region)
    sub = df[(df["material"] == material) & (df["region"] == region)].copy()
    if sub.empty:
        raise ValueError(f"Missing exogenous series for material={material}, region={region}")

    s = sub.groupby("year", as_index=True)["value"].mean().reindex(list(years))
    if fill_method:
        s = s.ffill().bfill()
    s = s.fillna(0.0)
    return s.to_numpy(dtype=float)


def load_final_demand(path: str | Path) -> pd.DataFrame:
    return load_year_material_region_series(path)


def load_service_activity(path: str | Path) -> pd.DataFrame:
    return load_year_material_region_series(path)


def load_material_intensity(path: str | Path) -> pd.DataFrame:
    return load_year_material_region_series(path)


def final_demand_t(
    demand_df: pd.DataFrame,
    *,
    years: Sequence[int],
    material: str,
    region: str,
    fill_method: str = "ffill",
) -> np.ndarray:
    return series_t(demand_df, years=years, material=material, region=region, fill_method=fill_method)


def service_activity_t(
    service_activity_df: pd.DataFrame,
    *,
    years: Sequence[int],
    material: str,
    region: str,
    fill_method: str = "ffill",
) -> np.ndarray:
    return series_t(
        service_activity_df,
        years=years,
        material=material,
        region=region,
        fill_method=fill_method,
    )


def material_intensity_t(
    material_intensity_df: pd.DataFrame,
    *,
    years: Sequence[int],
    material: str,
    region: str,
    fill_method: str = "ffill",
) -> np.ndarray:
    return series_t(
        material_intensity_df,
        years=years,
        material=material,
        region=region,
        fill_method=fill_method,
    )


def load_primary_refined_output(path: str | Path) -> pd.DataFrame:
    return load_year_material_region_series(path, allow_negative=False)


def load_primary_refined_net_imports(path: str | Path) -> pd.DataFrame:
    # Net imports may be negative (net exporter), so negatives are valid.
    return load_year_material_region_series(path, allow_negative=True)


def load_stage_yields_losses(path: str | Path) -> pd.DataFrame:
    req = {
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
    }
    df = _normalize_df(_read_csv(path, req)).copy()
    df["year"] = df["year"].astype(int)
    df["material"] = df["material"].astype(str)
    df["region"] = df["region"].astype(str)
    numeric_cols = [
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
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
        if df[col].isna().any():
            bad = df[df[col].isna()].head(10)
            raise ValueError(
                f"Stage yields/losses contain non-numeric values in '{col}'. Examples:\n"
                + bad.to_string(index=False)
            )
    dup_mask = df.duplicated(subset=["year", "material", "region"], keep=False)
    if dup_mask.any():
        bad = df.loc[dup_mask, ["year", "material", "region"]].head(10)
        raise ValueError(
            "Stage yields/losses contain duplicate (year, material, region) rows. "
            "Duplicates are not allowed.\nExamples:\n"
            + bad.to_string(index=False)
        )
    return df


def load_collection_routing_rates(path: str | Path) -> pd.DataFrame:
    req = {"year", "material", "region", "recycling_rate", "remanufacturing_rate", "disposal_rate"}
    df = _normalize_df(_read_csv(path, req)).copy()
    df["year"] = df["year"].astype(int)
    df["material"] = df["material"].astype(str)
    df["region"] = df["region"].astype(str)

    for col in ["recycling_rate", "remanufacturing_rate", "disposal_rate"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
        if df[col].isna().any():
            bad = df[df[col].isna()].head(10)
            raise ValueError(f"Collection routing rates contain non-numeric values in '{col}'. Examples:\n" + bad.to_string(index=False))

    dup_mask = df.duplicated(subset=["year", "material", "region"], keep=False)
    if dup_mask.any():
        bad = df.loc[dup_mask, ["year", "material", "region"]].head(10)
        raise ValueError(
            "Collection routing rates contain duplicate (year, material, region) rows. "
            "Duplicates are not allowed.\nExamples:\n"
            + bad.to_string(index=False)
        )
    return df


def load_remanufacturing_end_use_eligibility(path: str | Path) -> pd.DataFrame:
    """High-level end-use reman eligibility in [0,1].

    Expected columns: year, region, end_use, value
    """
    req = {"year", "region", "end_use", "value"}
    df = _normalize_df(_read_csv(path, req)).copy()
    df["year"] = df["year"].astype(int)
    df["region"] = df["region"].astype(str)
    df["end_use"] = df["end_use"].astype(str)
    df["value"] = pd.to_numeric(df["value"], errors="coerce").astype(float)
    if df["value"].isna().any():
        bad = df[df["value"].isna()].head(10)
        raise ValueError(
            "Remanufacturing end-use eligibility contains non-numeric values. Examples:\n"
            + bad.to_string(index=False)
        )
    if (df["value"] < 0).any() or (df["value"] > 1).any():
        bad = df[(df["value"] < 0) | (df["value"] > 1)].head(10)
        raise ValueError(
            "Remanufacturing end-use eligibility must be in [0,1]. Examples:\n"
            + bad.to_string(index=False)
        )
    return df


def primary_refined_output_tr(
    refined_df: pd.DataFrame,
    *,
    years: Sequence[int],
    material: str,
    regions: Sequence[str],
    fill_method: str = "ffill",
) -> np.ndarray:
    out = np.zeros((len(years), len(regions)), dtype=float)
    for j, region in enumerate(regions):
        out[:, j] = series_t(refined_df, years=years, material=material, region=region, fill_method=fill_method)
    return out


def primary_refined_net_imports_tr(
    net_imp_df: pd.DataFrame,
    *,
    years: Sequence[int],
    material: str,
    regions: Sequence[str],
    fill_method: str = "ffill",
) -> np.ndarray:
    out = np.zeros((len(years), len(regions)), dtype=float)
    for j, region in enumerate(regions):
        out[:, j] = series_t(net_imp_df, years=years, material=material, region=region, fill_method=fill_method)
    return out


def stage_yields_losses_t(
    stage_df: pd.DataFrame,
    *,
    years: Sequence[int],
    material: str,
    region: str,
    fill_method: str = "ffill",
) -> Dict[str, np.ndarray]:
    material = normalize_material(material)
    region = normalize_region(region)
    sub = stage_df[(stage_df["material"] == material) & (stage_df["region"] == region)].copy()
    if sub.empty:
        raise ValueError(f"Missing stage_yields_losses for material={material}, region={region}")

    sub = sub.sort_values("year")
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
    out: Dict[str, np.ndarray] = {}
    defaults = {
        "extraction_yield": 1.0,
        "beneficiation_yield": 1.0,
        "refining_yield": 1.0,
        "sorting_yield": 1.0,
        "extraction_loss_to_sysenv_share": 1.0,
        "beneficiation_loss_to_sysenv_share": 1.0,
        "refining_loss_to_sysenv_share": 1.0,
        "sorting_reject_to_disposal_share": 1.0,
        "sorting_reject_to_sysenv_share": 0.0,
    }
    for col in cols:
        s = sub.groupby("year", as_index=True)[col].mean().reindex(list(years))
        if fill_method:
            s = s.ffill().bfill()
        s = s.fillna(defaults[col])
        out[col] = s.to_numpy(dtype=float)
    return out


def collection_routing_rates_t(
    routing_df: pd.DataFrame,
    *,
    years: Sequence[int],
    material: str,
    region: str,
    fill_method: str = "ffill",
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    material = normalize_material(material)
    region = normalize_region(region)
    sub = routing_df[(routing_df["material"] == material) & (routing_df["region"] == region)].copy()
    if sub.empty:
        raise ValueError(f"Missing collection routing rates for material={material}, region={region}")

    sub = sub.sort_values("year")
    out: list[np.ndarray] = []
    for col in ["recycling_rate", "remanufacturing_rate", "disposal_rate"]:
        s = sub.groupby("year", as_index=True)[col].mean().reindex(list(years))
        if fill_method:
            s = s.ffill().bfill()
        s = s.fillna(0.0)
        out.append(s.to_numpy(dtype=float))
    return (out[0], out[1], out[2])


def remanufacturing_eligibility_tre(
    eligibility_df: pd.DataFrame,
    *,
    years: Sequence[int],
    regions: Sequence[str],
    end_uses: Sequence[str],
    fill_method: str = "ffill",
) -> np.ndarray:
    """Return remanufacturing end-use eligibility with shape (t,r,e)."""
    out = np.zeros((len(years), len(regions), len(end_uses)), dtype=float)
    for r_idx, region in enumerate(regions):
        region_norm = normalize_region(region)
        sub_r = eligibility_df[eligibility_df["region"] == region_norm].copy()
        if sub_r.empty:
            raise ValueError(f"Missing remanufacturing end-use eligibility for region={region_norm}")

        for e_idx, end_use in enumerate(end_uses):
            sub = sub_r[sub_r["end_use"] == str(end_use)].copy()
            if sub.empty:
                raise ValueError(
                    f"Missing remanufacturing end-use eligibility for region={region_norm}, end_use={end_use}"
                )
            s = sub.groupby("year", as_index=True)["value"].mean().reindex(list(years))
            if fill_method:
                s = s.ffill().bfill()
            s = s.fillna(0.0)
            out[:, r_idx, e_idx] = s.to_numpy(dtype=float)
    return out


# -------------------------
# Stock-in-use (observations)
# -------------------------

def load_stock_in_use(path: str | Path) -> pd.DataFrame:
    df = _normalize_df(_read_csv(path, {"year", "material", "region", "end_use", "value"})).copy()
    df["year"] = df["year"].astype(int)
    df["material"] = df["material"].astype(str)
    df["region"] = df["region"].astype(str)
    df["end_use"] = df["end_use"].astype(str)
    df["value"] = pd.to_numeric(df["value"], errors="coerce").astype(float)
    if df["value"].isna().any():
        bad = df[df["value"].isna()].head(10)
        raise ValueError("Stock-in-use contains non-numeric values. Examples:\n" + bad.to_string(index=False))
    if (df["value"] < 0).any():
        bad = df[df["value"] < 0].head(10)
        raise ValueError("Stock-in-use contains negative values. Examples:\n" + bad.to_string(index=False))
    return df


def stock_in_use_t(
    stock_df: pd.DataFrame,
    *,
    years: Sequence[int],
    material: str,
    region: str,
    end_uses: Sequence[str],
    fill_method: str = "ffill",
) -> np.ndarray:
    material = normalize_material(material)
    region = normalize_region(region)
    df = stock_df[(stock_df["material"] == material) & (stock_df["region"] == region)].copy()
    if df.empty:
        return np.full(len(years), np.nan, dtype=float)

    piv = (
        df.pivot_table(index="year", columns="end_use", values="value", aggfunc="mean")
        .reindex(index=list(years), columns=list(end_uses))
    )
    if fill_method:
        piv = piv.ffill().bfill()
    arr = piv.to_numpy(dtype=float)
    out = np.nansum(arr, axis=1)
    all_nan = np.isnan(arr).all(axis=1)
    out[all_nan] = np.nan
    return out


# -------------------------
# Lifetime distributions
# -------------------------

def load_lifetime_distributions(path: str | Path) -> pd.DataFrame:
    """Long format: cohort_year, material, region, end_use, dist, param, value."""
    df = _normalize_df(_read_csv(path, {"cohort_year", "material", "region", "end_use", "dist", "param", "value"})).copy()
    df["cohort_year"] = df["cohort_year"].astype(int)
    df["material"] = df["material"].astype(str)
    df["region"] = df["region"].astype(str)
    df["end_use"] = df["end_use"].astype(str)
    df["dist"] = df["dist"].astype(str).str.lower()
    df["param"] = df["param"].astype(str).str.lower()
    df["value"] = pd.to_numeric(df["value"], errors="coerce").astype(float)

    if df["value"].isna().any():
        bad = df[df["value"].isna()].head(10)
        raise ValueError("Lifetime distributions contain non-numeric values. Examples:\n" + bad.to_string(index=False))

    bad_dist = ~df["dist"].isin(["weibull", "fixed", "lognormal"])
    if bad_dist.any():
        bad = df.loc[bad_dist, ["cohort_year", "material", "region", "end_use", "dist"]].head(10)
        raise ValueError("Unsupported dist type(s). Supported: weibull, fixed, lognormal. Examples:\n" + bad.to_string(index=False))

    dup_mask = df.duplicated(
        subset=["cohort_year", "material", "region", "end_use", "dist", "param"], keep=False
    )
    if dup_mask.any():
        bad = df.loc[dup_mask, ["cohort_year", "material", "region", "end_use", "dist", "param"]].head(10)
        raise ValueError(
            "Lifetime distributions contain duplicate parameter rows for the same cohort/material/region/end_use/dist. "
            "Duplicates are not allowed.\nExamples:\n" + bad.to_string(index=False)
        )

    # Every cohort/material/region/end_use must map to exactly one distribution family.
    dist_mix = (
        df.groupby(["cohort_year", "material", "region", "end_use"], as_index=False)["dist"]
        .nunique()
        .rename(columns={"dist": "n_dist"})
    )
    bad_mix = dist_mix[dist_mix["n_dist"] != 1]
    if not bad_mix.empty:
        raise ValueError(
            "Lifetime distributions must define exactly one dist per "
            "(cohort_year, material, region, end_use)."
        )

    # Strict parameterization checks per distribution family.
    allowed_params = {
        "fixed": {"mean_years"},
        "weibull": {"mean_years", "shape", "scale"},
        "lognormal": {"mean_years", "mu", "sigma"},
    }
    req_one_of = {
        "fixed": [{"mean_years"}],
        "weibull": [{"scale"}, {"mean_years"}],
        "lognormal": [{"mu"}, {"mean_years"}],
    }
    req_all = {
        "fixed": set(),
        "weibull": {"shape"},
        "lognormal": {"sigma"},
    }

    grp = df.groupby(["cohort_year", "material", "region", "end_use", "dist"], sort=False)
    for key, g in grp:
        dist = str(key[-1])
        params_present = set(g["param"].astype(str).tolist())
        unknown = sorted(list(params_present - allowed_params[dist]))
        if unknown:
            raise ValueError(f"Unsupported parameter(s) for dist={dist}: {unknown}. Row key={key}")

        if not req_all[dist].issubset(params_present):
            missing = sorted(list(req_all[dist] - params_present))
            raise ValueError(f"Missing required parameter(s) for dist={dist}: {missing}. Row key={key}")

        if not any(cond.issubset(params_present) for cond in req_one_of[dist]):
            raise ValueError(
                f"Missing required parameterization for dist={dist}. Need one of {req_one_of[dist]}. Row key={key}"
            )

        vals = {str(r["param"]): float(r["value"]) for _, r in g.iterrows()}
        if dist == "fixed":
            if vals.get("mean_years", np.nan) <= 0:
                raise ValueError(f"fixed mean_years must be > 0. Row key={key}")
        elif dist == "weibull":
            if vals.get("shape", np.nan) <= 0:
                raise ValueError(f"weibull shape must be > 0. Row key={key}")
            if ("scale" in vals) and (vals["scale"] <= 0):
                raise ValueError(f"weibull scale must be > 0 when provided. Row key={key}")
            if ("mean_years" in vals) and (vals["mean_years"] <= 0):
                raise ValueError(f"weibull mean_years must be > 0 when provided. Row key={key}")
        elif dist == "lognormal":
            if vals.get("sigma", np.nan) <= 0:
                raise ValueError(f"lognormal sigma must be > 0. Row key={key}")
            if ("mean_years" in vals) and (vals["mean_years"] <= 0):
                raise ValueError(f"lognormal mean_years must be > 0 when provided. Row key={key}")

    return df
