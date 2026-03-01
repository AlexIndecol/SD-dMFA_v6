from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = ("variant", "block", "key", "year", "value")
OPTIONAL_COLUMNS = ("material", "region", "before")


def load_reporting_profile_csv(path: str | Path) -> pd.DataFrame:
    csv_path = Path(path)
    df = pd.read_csv(csv_path)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"{csv_path}: missing required columns {missing}; required={list(REQUIRED_COLUMNS)}"
        )
    for c in OPTIONAL_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan

    out = df.copy()
    out["variant"] = out["variant"].astype(str).str.strip()
    out["block"] = out["block"].astype(str).str.strip()
    out["key"] = out["key"].astype(str).str.strip()
    out["material"] = out["material"].fillna("").astype(str).str.strip()
    out["region"] = out["region"].fillna("").astype(str).str.strip()
    out["year"] = out["year"].astype(int)
    out["value"] = out["value"].astype(float)
    out["before"] = pd.to_numeric(out["before"], errors="coerce")

    if (out["variant"] == "").any():
        raise ValueError(f"{csv_path}: column 'variant' contains empty values.")
    if (out["block"] == "").any():
        raise ValueError(f"{csv_path}: column 'block' contains empty values.")
    if (out["key"] == "").any():
        raise ValueError(f"{csv_path}: column 'key' contains empty values.")

    dup_cols = ["variant", "block", "key", "year", "material", "region"]
    dup = out[out.duplicated(subset=dup_cols, keep=False)]
    if not dup.empty:
        raise ValueError(
            f"{csv_path}: duplicated rows for unique key {dup_cols}; first duplicate={dup.iloc[0].to_dict()}"
        )

    return out


def expand_reporting_profile_series(
    *,
    years: Iterable[int],
    report_start_year: int,
    year_values: Dict[int, float],
    before_value: float | None = None,
) -> List[float]:
    years_list = [int(y) for y in years]
    report_years = [y for y in years_list if y >= int(report_start_year)]
    if not report_years:
        raise ValueError("No reporting years found in provided horizon.")
    if not year_values:
        raise ValueError("year_values is empty.")

    min_input_year = min(year_values.keys())
    if min_input_year < int(report_start_year):
        raise ValueError(
            f"Profile year {min_input_year} is before report_start_year={int(report_start_year)}."
        )

    x = np.array(sorted(int(y) for y in year_values.keys()), dtype=float)
    y = np.array([float(year_values[int(yr)]) for yr in x], dtype=float)
    xq = np.array(report_years, dtype=float)
    # Piecewise linear interpolation with edge hold for uncovered tails.
    yq = np.interp(xq, x, y, left=float(y[0]), right=float(y[-1]))

    if before_value is None:
        before = float(yq[0])
    else:
        before = float(before_value)

    full = np.full(len(years_list), before, dtype=float)
    report_idx = [i for i, yr in enumerate(years_list) if yr >= int(report_start_year)]
    full[np.array(report_idx, dtype=int)] = yq
    return full.tolist()


def _set_nested(d: Dict[str, Any], path: Tuple[str, ...], value: Any) -> None:
    cur = d
    for key in path[:-1]:
        if key not in cur or not isinstance(cur[key], dict):
            cur[key] = {}
        cur = cur[key]
    cur[path[-1]] = value


def build_variant_payload_from_profiles(
    *,
    profiles: pd.DataFrame,
    years: Iterable[int],
    report_start_year: int,
) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}

    group_cols = ["variant", "block", "key", "material", "region"]
    for (variant, block, key, material, region), grp in profiles.groupby(group_cols, sort=True):
        year_values = {int(r.year): float(r.value) for r in grp.itertuples(index=False)}
        before_vals = grp["before"].dropna().astype(float).unique().tolist()
        before_value = float(before_vals[0]) if before_vals else None
        series = expand_reporting_profile_series(
            years=years,
            report_start_year=report_start_year,
            year_values=year_values,
            before_value=before_value,
        )

        variant_node = out.setdefault(variant, {})
        if material == "" and region == "":
            _set_nested(variant_node, (str(block), str(key)), series)
            continue

        ovs = variant_node.setdefault("dimension_overrides", [])
        ov_name = f"profile_{material or 'all_materials'}_{region or 'all_regions'}"
        match = None
        for ov in ovs:
            if ov.get("name") == ov_name:
                match = ov
                break
        if match is None:
            match = {"name": ov_name}
            if material:
                match["materials"] = [material]
            if region:
                match["regions"] = [region]
            ovs.append(match)
        _set_nested(match, (str(block), str(key)), series)

    return out

