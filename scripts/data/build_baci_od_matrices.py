from __future__ import annotations

import importlib.util
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


DATA_ROOT = Path("/Users/alexcolloricchio/Desktop/CRMs/Data")
OUT_DIR = DATA_ROOT / "processed" / "trade_od"
TRADE_OBSERVED_SCRIPT = DATA_ROOT / "processed" / "trade_observed" / "build_trade_observed.py"

REGIONS = ["EU27", "China", "RoW"]
MATERIALS = ["nickel", "tin", "zinc"]
COMMODITIES = ["concentrates", "refined_metal", "scrap"]
YEARS = list(range(1995, 2025))

WEIGHT_WINDOW_YEARS = 3
CAP_WINDOW_YEARS = 5
CAP_QUANTILE = 0.75
ALLOCATOR_REALLOCATION_PASSES = 1
CHUNK_SIZE = 1_000_000


OBSERVED_COLUMNS = [
    "year",
    "material",
    "commodity",
    "origin_region",
    "destination_region",
    "flow_kt",
]
WEIGHT_COLUMNS = [
    "year",
    "material",
    "commodity",
    "origin_region",
    "destination_region",
    "weight_0_1",
]
CONSTRAINT_COLUMNS = [
    "year",
    "material",
    "commodity",
    "region",
    "supply_avail_kt",
    "import_need_kt",
    "export_cap_raw_kt",
    "exportable_kt",
]
CONSTRAINED_COLUMNS = OBSERVED_COLUMNS.copy()
SHARE_COLUMNS = [
    "mode",
    "year",
    "material",
    "commodity",
    "destination_region",
    "origin_region",
    "share_origin_frac",
]
DIAG_COLUMNS = [
    "year",
    "material",
    "commodity",
    "origin_region",
    "destination_region",
    "x0_kt",
    "x1_kt",
    "x_final_kt",
    "residual_export_kt",
    "residual_import_need_kt",
    "pass_id",
]


def load_trade_observed_module():
    spec = importlib.util.spec_from_file_location("trade_observed_module", TRADE_OBSERVED_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {TRADE_OBSERVED_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_code_split_map(module) -> pd.DataFrame:
    rows: List[dict] = []
    for code, (material, commodity, _, _) in module.BACI_STRICT_CODES.items():
        rows.append(
            {
                "k": str(code).zfill(6),
                "material": material,
                "commodity": commodity,
                "share": 1.0,
                "mapping_type": "strict",
            }
        )

    for code, (material, alloc, _) in module.BACI_AMBIGUOUS_CODES.items():
        for commodity, share in zip(COMMODITIES, alloc):
            if share <= 0:
                continue
            rows.append(
                {
                    "k": str(code).zfill(6),
                    "material": material,
                    "commodity": commodity,
                    "share": float(share),
                    "mapping_type": "ambiguous",
                }
            )

    out = pd.DataFrame(rows)
    if out.empty:
        raise AssertionError("No BACI code mappings found")
    return out


def build_year_source_map(module) -> Dict[int, Tuple[str, Path, str]]:
    hs92_files = module.list_baci_year_files(module.BACI_ZIP_HS92)
    hs22_files = module.list_baci_year_files(module.BACI_ZIP_HS22)

    year_map: Dict[int, Tuple[str, Path, str]] = {}
    for y in sorted(hs92_files):
        if 1995 <= y <= 2021:
            year_map[y] = ("HS92", module.BACI_ZIP_HS92, hs92_files[y])
    for y in sorted(hs22_files):
        if 2022 <= y <= 2024:
            if y in year_map:
                raise RuntimeError(f"BACI overlap between HS92 and HS22 for year {y}")
            year_map[y] = ("HS22", module.BACI_ZIP_HS22, hs22_files[y])
    return year_map


def _full_od_grid() -> pd.DataFrame:
    idx = pd.MultiIndex.from_product(
        [YEARS, MATERIALS, COMMODITIES, REGIONS, REGIONS],
        names=["year", "material", "commodity", "origin_region", "destination_region"],
    )
    return idx.to_frame(index=False)


def _full_constraint_grid() -> pd.DataFrame:
    idx = pd.MultiIndex.from_product(
        [YEARS, MATERIALS, COMMODITIES, REGIONS],
        names=["year", "material", "commodity", "region"],
    )
    return idx.to_frame(index=False)


def build_observed_od(module) -> Tuple[pd.DataFrame, Dict[int, str]]:
    country_region = module.load_baci_country_region_map()
    year_source = build_year_source_map(module)
    code_map = build_code_split_map(module)
    target_codes = set(code_map["k"].tolist())

    grouped_rows: List[pd.DataFrame] = []

    # Group work per zip to avoid repeated open/close.
    zip_to_years: Dict[Path, List[int]] = defaultdict(list)
    for year, (_, zpath, _) in year_source.items():
        zip_to_years[zpath].append(year)

    for zpath, years in zip_to_years.items():
        years = sorted(years)
        files = module.list_baci_year_files(zpath)
        with zipfile.ZipFile(zpath) as zf:
            for year in years:
                file_name = files[year]
                print(f"[OD] Processing {zpath.name} year {year} ({file_name})")
                reader = pd.read_csv(
                    zf.open(file_name),
                    usecols=["t", "i", "j", "k", "q"],
                    chunksize=CHUNK_SIZE,
                )
                for chunk in reader:
                    chunk["k"] = chunk["k"].astype(str).str.zfill(6)
                    chunk = chunk[chunk["k"].isin(target_codes)].copy()
                    if chunk.empty:
                        continue
                    chunk["q"] = pd.to_numeric(chunk["q"], errors="coerce")
                    chunk = chunk[chunk["q"].notna() & (chunk["q"] >= 0)].copy()
                    if chunk.empty:
                        continue

                    chunk["origin_region"] = chunk["i"].map(country_region).fillna("RoW")
                    chunk["destination_region"] = chunk["j"].map(country_region).fillna("RoW")
                    chunk = chunk.rename(columns={"t": "year"})
                    chunk["year"] = chunk["year"].astype(int)
                    chunk = chunk[
                        chunk["origin_region"].isin(REGIONS) & chunk["destination_region"].isin(REGIONS)
                    ].copy()
                    if chunk.empty:
                        continue

                    merged = chunk.merge(code_map, on="k", how="inner", copy=False)
                    merged["flow_kt"] = merged["q"] * merged["share"]
                    g = (
                        merged.groupby(
                            ["year", "material", "commodity", "origin_region", "destination_region"],
                            as_index=False,
                        )["flow_kt"]
                        .sum()
                    )
                    grouped_rows.append(g)

    if grouped_rows:
        observed_sparse = pd.concat(grouped_rows, ignore_index=True)
        observed_sparse = (
            observed_sparse.groupby(
                ["year", "material", "commodity", "origin_region", "destination_region"], as_index=False
            )["flow_kt"]
            .sum()
        )
    else:
        observed_sparse = pd.DataFrame(columns=OBSERVED_COLUMNS)

    observed = _full_od_grid().merge(
        observed_sparse,
        on=["year", "material", "commodity", "origin_region", "destination_region"],
        how="left",
    )
    observed["flow_kt"] = observed["flow_kt"].fillna(0.0)
    observed = observed.sort_values(
        ["year", "material", "commodity", "origin_region", "destination_region"]
    ).reset_index(drop=True)

    source_by_year = {y: year_source[y][0] for y in sorted(year_source)}
    return observed, source_by_year


def compute_rolling_weights(observed: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    origin_tot = (
        observed.groupby(["year", "material", "commodity", "origin_region"], as_index=False)["flow_kt"]
        .sum()
        .rename(columns={"flow_kt": "origin_total_kt"})
    )
    with_share = observed.merge(origin_tot, on=["year", "material", "commodity", "origin_region"], how="left")
    with_share["share_raw"] = np.where(
        with_share["origin_total_kt"] > 0,
        with_share["flow_kt"] / with_share["origin_total_kt"],
        np.nan,
    )

    share_lookup = {
        (int(r.year), r.material, r.commodity, r.origin_region, r.destination_region): float(r.share_raw)
        for r in with_share.itertuples(index=False)
    }
    global_dest = (
        observed.groupby(["year", "material", "commodity", "destination_region"], as_index=False)["flow_kt"]
        .sum()
        .rename(columns={"flow_kt": "global_dest_kt"})
    )
    global_lookup = {
        (int(r.year), r.material, r.commodity, r.destination_region): float(r.global_dest_kt)
        for r in global_dest.itertuples(index=False)
    }

    weight_rows: List[dict] = []
    fallback_rows: List[dict] = []

    for year in YEARS:
        y0 = max(YEARS[0], year - WEIGHT_WINDOW_YEARS + 1)
        window_years = [y for y in YEARS if y0 <= y <= year]
        for material in MATERIALS:
            for commodity in COMMODITIES:
                # same-year global destination fallback mix for (year, material, commodity)
                global_vec = np.array(
                    [global_lookup.get((year, material, commodity, d), 0.0) for d in REGIONS], dtype=float
                )
                global_sum = float(global_vec.sum())
                if global_sum > 0:
                    global_mix = global_vec / global_sum
                else:
                    global_mix = np.full(len(REGIONS), 1.0 / len(REGIONS), dtype=float)

                for origin in REGIONS:
                    window_vecs: List[np.ndarray] = []
                    for wy in window_years:
                        vec = np.array(
                            [
                                share_lookup.get((wy, material, commodity, origin, dest), np.nan)
                                for dest in REGIONS
                            ],
                            dtype=float,
                        )
                        if np.isfinite(vec).any():
                            # All three should be finite for valid origin shares.
                            if np.isfinite(vec).all() and vec.sum() > 0:
                                window_vecs.append(vec)
                    if window_vecs:
                        w = np.mean(window_vecs, axis=0)
                        w_sum = float(w.sum())
                        if w_sum > 0:
                            w = w / w_sum
                        else:
                            w = global_mix.copy()
                            fallback_rows.append(
                                {
                                    "year": year,
                                    "material": material,
                                    "commodity": commodity,
                                    "origin_region": origin,
                                    "fallback_type": "global_zero_after_rolling",
                                }
                            )
                    else:
                        w = global_mix.copy()
                        fallback_type = "global_mix" if global_sum > 0 else "uniform"
                        fallback_rows.append(
                            {
                                "year": year,
                                "material": material,
                                "commodity": commodity,
                                "origin_region": origin,
                                "fallback_type": fallback_type,
                            }
                        )

                    for dest, val in zip(REGIONS, w.tolist()):
                        weight_rows.append(
                            {
                                "year": year,
                                "material": material,
                                "commodity": commodity,
                                "origin_region": origin,
                                "destination_region": dest,
                                "weight_0_1": float(val),
                            }
                        )

    weights = pd.DataFrame(weight_rows, columns=WEIGHT_COLUMNS).sort_values(
        ["year", "material", "commodity", "origin_region", "destination_region"]
    )
    fallback_log = pd.DataFrame(
        fallback_rows, columns=["year", "material", "commodity", "origin_region", "fallback_type"]
    )
    return weights.reset_index(drop=True), fallback_log.reset_index(drop=True)


def build_constraints(observed: pd.DataFrame) -> pd.DataFrame:
    supply = (
        observed.groupby(["year", "material", "commodity", "origin_region"], as_index=False)["flow_kt"]
        .sum()
        .rename(columns={"origin_region": "region", "flow_kt": "supply_avail_kt"})
    )
    need = (
        observed.groupby(["year", "material", "commodity", "destination_region"], as_index=False)["flow_kt"]
        .sum()
        .rename(columns={"destination_region": "region", "flow_kt": "import_need_kt"})
    )
    constraints = _full_constraint_grid().merge(
        supply, on=["year", "material", "commodity", "region"], how="left"
    ).merge(need, on=["year", "material", "commodity", "region"], how="left")
    constraints["supply_avail_kt"] = constraints["supply_avail_kt"].fillna(0.0)
    constraints["import_need_kt"] = constraints["import_need_kt"].fillna(0.0)
    constraints["export_cap_raw_kt"] = 0.0

    # Rolling historical quantile cap by (material, commodity, region/origin), excluding future years.
    for (material, commodity, region), g_idx in constraints.groupby(
        ["material", "commodity", "region"], sort=False
    ).groups.items():
        g = constraints.loc[g_idx].sort_values("year")
        supplies = g["supply_avail_kt"].to_numpy(dtype=float)
        years = g["year"].to_numpy(dtype=int)
        caps = np.zeros_like(supplies, dtype=float)
        for i, year in enumerate(years):
            y0 = year - CAP_WINDOW_YEARS + 1
            mask = (years >= y0) & (years <= year)
            hist = supplies[mask]
            if hist.size == 0:
                caps[i] = supplies[i]
            else:
                caps[i] = float(np.quantile(hist, CAP_QUANTILE))
        constraints.loc[g.index, "export_cap_raw_kt"] = caps

    constraints["exportable_kt"] = np.minimum(
        constraints["supply_avail_kt"].to_numpy(dtype=float),
        constraints["export_cap_raw_kt"].to_numpy(dtype=float),
    )
    constraints = constraints[CONSTRAINT_COLUMNS].sort_values(
        ["year", "material", "commodity", "region"]
    ).reset_index(drop=True)
    return constraints


def _matrix_from_series(
    df: pd.DataFrame,
    value_col: str,
    row_col: str,
    col_col: str,
    row_order: List[str],
    col_order: List[str],
) -> np.ndarray:
    p = (
        df.pivot_table(index=row_col, columns=col_col, values=value_col, aggfunc="sum", fill_value=0.0)
        .reindex(index=row_order, columns=col_order, fill_value=0.0)
    )
    return p.to_numpy(dtype=float)


def allocate_one(
    exportable: np.ndarray,
    import_need: np.ndarray,
    weights: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    # Pass 0: proposal and destination absorption.
    x0 = exportable[:, None] * weights
    demand = x0.sum(axis=0)
    ratio = np.divide(import_need, demand, out=np.zeros_like(import_need, dtype=float), where=demand > 0)
    scale = np.minimum(1.0, ratio)
    x1 = x0 * scale[None, :]

    residual_export = np.maximum(exportable - x1.sum(axis=1), 0.0)
    residual_need = np.maximum(import_need - x1.sum(axis=0), 0.0)

    # Pass 1: reallocate residual export to destinations with residual need.
    y0 = np.zeros_like(x0)
    eligible_dest = residual_need > 0
    for oi in range(len(REGIONS)):
        if residual_export[oi] <= 0:
            continue
        row_w = weights[oi, :].copy()
        row_w = np.where(eligible_dest, row_w, 0.0)
        denom = row_w.sum()
        if denom <= 0:
            continue
        row_w = row_w / denom
        y0[oi, :] = residual_export[oi] * row_w

    need_for_pass1 = residual_need.copy()
    demand_pass1 = y0.sum(axis=0)
    ratio_pass1 = np.divide(
        need_for_pass1,
        demand_pass1,
        out=np.zeros_like(need_for_pass1, dtype=float),
        where=demand_pass1 > 0,
    )
    scale_pass1 = np.minimum(1.0, ratio_pass1)
    y1 = y0 * scale_pass1[None, :]

    x_final = x1 + y1
    residual_export_final = np.maximum(exportable - x_final.sum(axis=1), 0.0)
    residual_need_final = np.maximum(import_need - x_final.sum(axis=0), 0.0)
    return x0, x1, y0, y1, x_final, residual_export_final, residual_need_final


def build_constrained_flows_and_diagnostics(
    observed: pd.DataFrame,
    weights: pd.DataFrame,
    constraints: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    constrained_rows: List[dict] = []
    diag_rows: List[dict] = []

    for year in YEARS:
        for material in MATERIALS:
            for commodity in COMMODITIES:
                obs_sub = observed[
                    (observed["year"] == year)
                    & (observed["material"] == material)
                    & (observed["commodity"] == commodity)
                ]
                w_sub = weights[
                    (weights["year"] == year)
                    & (weights["material"] == material)
                    & (weights["commodity"] == commodity)
                ]
                c_sub = constraints[
                    (constraints["year"] == year)
                    & (constraints["material"] == material)
                    & (constraints["commodity"] == commodity)
                ]

                if obs_sub.empty or w_sub.empty or c_sub.empty:
                    continue

                w_mat = _matrix_from_series(
                    w_sub, "weight_0_1", "origin_region", "destination_region", REGIONS, REGIONS
                )
                exportable = (
                    c_sub.set_index("region").reindex(REGIONS)["exportable_kt"].fillna(0.0).to_numpy(dtype=float)
                )
                import_need = (
                    c_sub.set_index("region").reindex(REGIONS)["import_need_kt"].fillna(0.0).to_numpy(dtype=float)
                )

                x0, x1, y0, y1, x_final, res_exp_final, res_need_final = allocate_one(
                    exportable, import_need, w_mat
                )

                # Residuals after pass0 for diagnostics.
                res_exp_pass0 = np.maximum(exportable - x1.sum(axis=1), 0.0)
                res_need_pass0 = np.maximum(import_need - x1.sum(axis=0), 0.0)

                for oi, origin in enumerate(REGIONS):
                    for di, dest in enumerate(REGIONS):
                        constrained_rows.append(
                            {
                                "year": year,
                                "material": material,
                                "commodity": commodity,
                                "origin_region": origin,
                                "destination_region": dest,
                                "flow_kt": float(x_final[oi, di]),
                            }
                        )
                        diag_rows.append(
                            {
                                "year": year,
                                "material": material,
                                "commodity": commodity,
                                "origin_region": origin,
                                "destination_region": dest,
                                "x0_kt": float(x0[oi, di]),
                                "x1_kt": float(x1[oi, di]),
                                "x_final_kt": float(x1[oi, di]),
                                "residual_export_kt": float(res_exp_pass0[oi]),
                                "residual_import_need_kt": float(res_need_pass0[di]),
                                "pass_id": 0,
                            }
                        )
                        diag_rows.append(
                            {
                                "year": year,
                                "material": material,
                                "commodity": commodity,
                                "origin_region": origin,
                                "destination_region": dest,
                                "x0_kt": float(y0[oi, di]),
                                "x1_kt": float(y1[oi, di]),
                                "x_final_kt": float(x_final[oi, di]),
                                "residual_export_kt": float(res_exp_final[oi]),
                                "residual_import_need_kt": float(res_need_final[di]),
                                "pass_id": 1,
                            }
                        )

    constrained = pd.DataFrame(constrained_rows, columns=CONSTRAINED_COLUMNS).sort_values(
        ["year", "material", "commodity", "origin_region", "destination_region"]
    )
    diagnostics = pd.DataFrame(diag_rows, columns=DIAG_COLUMNS).sort_values(
        ["year", "material", "commodity", "pass_id", "origin_region", "destination_region"]
    )
    return constrained.reset_index(drop=True), diagnostics.reset_index(drop=True)


def build_supplier_shares(observed: pd.DataFrame, constrained: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for mode, df in [("observed", observed), ("constrained", constrained)]:
        t = df.copy()
        dest_total = (
            t.groupby(["year", "material", "commodity", "destination_region"], as_index=False)["flow_kt"]
            .sum()
            .rename(columns={"flow_kt": "dest_total_kt"})
        )
        t = t.merge(dest_total, on=["year", "material", "commodity", "destination_region"], how="left")
        t["share_origin_frac"] = np.where(t["dest_total_kt"] > 0, t["flow_kt"] / t["dest_total_kt"], 0.0)
        t["mode"] = mode
        frames.append(
            t[
                [
                    "mode",
                    "year",
                    "material",
                    "commodity",
                    "destination_region",
                    "origin_region",
                    "share_origin_frac",
                ]
            ]
        )

    shares = pd.concat(frames, ignore_index=True).sort_values(
        ["mode", "year", "material", "commodity", "destination_region", "origin_region"]
    )
    return shares.reset_index(drop=True)


def validate_outputs(
    observed: pd.DataFrame,
    weights: pd.DataFrame,
    constraints: pd.DataFrame,
    constrained: pd.DataFrame,
    shares: pd.DataFrame,
    diagnostics: pd.DataFrame,
    source_by_year: Dict[int, str],
) -> pd.DataFrame:
    # Schema checks.
    if list(observed.columns) != OBSERVED_COLUMNS:
        raise AssertionError(f"Observed schema mismatch: {observed.columns.tolist()}")
    if list(weights.columns) != WEIGHT_COLUMNS:
        raise AssertionError(f"Weights schema mismatch: {weights.columns.tolist()}")
    if list(constraints.columns) != CONSTRAINT_COLUMNS:
        raise AssertionError(f"Constraints schema mismatch: {constraints.columns.tolist()}")
    if list(constrained.columns) != CONSTRAINED_COLUMNS:
        raise AssertionError(f"Constrained schema mismatch: {constrained.columns.tolist()}")
    if list(shares.columns) != SHARE_COLUMNS:
        raise AssertionError(f"Shares schema mismatch: {shares.columns.tolist()}")
    if list(diagnostics.columns) != DIAG_COLUMNS:
        raise AssertionError(f"Diagnostics schema mismatch: {diagnostics.columns.tolist()}")

    # Domain checks.
    for df_name, df in [("observed", observed), ("constrained", constrained)]:
        if not set(df["material"]).issubset(set(MATERIALS)):
            raise AssertionError(f"{df_name}: invalid material domain")
        if not set(df["commodity"]).issubset(set(COMMODITIES)):
            raise AssertionError(f"{df_name}: invalid commodity domain")
        if not set(df["origin_region"]).issubset(set(REGIONS)):
            raise AssertionError(f"{df_name}: invalid origin domain")
        if not set(df["destination_region"]).issubset(set(REGIONS)):
            raise AssertionError(f"{df_name}: invalid destination domain")
        if df[["year", "material", "commodity", "origin_region", "destination_region"]].isna().any().any():
            raise AssertionError(f"{df_name}: null key values")
        if (df["flow_kt"] < -1e-12).any():
            raise AssertionError(f"{df_name}: negative flow detected")

    # Year coverage and bridge integrity.
    expected_years = set(YEARS)
    if set(observed["year"]) != expected_years:
        raise AssertionError("Observed year coverage is not exactly 1995-2024")
    if set(constrained["year"]) != expected_years:
        raise AssertionError("Constrained year coverage is not exactly 1995-2024")
    if set(weights["year"]) != expected_years:
        raise AssertionError("Weights year coverage is not exactly 1995-2024")
    for year in YEARS:
        src = source_by_year.get(year)
        if year <= 2021 and src != "HS92":
            raise AssertionError(f"HS bridge violation at year {year}: expected HS92")
        if year >= 2022 and src != "HS22":
            raise AssertionError(f"HS bridge violation at year {year}: expected HS22")

    # Weight sums.
    wsum = (
        weights.groupby(["year", "material", "commodity", "origin_region"], as_index=False)["weight_0_1"]
        .sum()
        .rename(columns={"weight_0_1": "w_sum"})
    )
    if not np.allclose(wsum["w_sum"].to_numpy(dtype=float), 1.0, rtol=0, atol=1e-9):
        bad = wsum.loc[~np.isclose(wsum["w_sum"], 1.0, atol=1e-9)].head(10)
        raise AssertionError(f"Weight sums do not equal 1 for all groups. Examples:\n{bad}")

    # Observed consistency with supply/import aggregates.
    obs_supply = (
        observed.groupby(["year", "material", "commodity", "origin_region"], as_index=False)["flow_kt"]
        .sum()
        .rename(columns={"origin_region": "region", "flow_kt": "obs_supply"})
    )
    obs_need = (
        observed.groupby(["year", "material", "commodity", "destination_region"], as_index=False)["flow_kt"]
        .sum()
        .rename(columns={"destination_region": "region", "flow_kt": "obs_need"})
    )
    chk = (
        constraints.merge(obs_supply, on=["year", "material", "commodity", "region"], how="left")
        .merge(obs_need, on=["year", "material", "commodity", "region"], how="left")
        .fillna(0.0)
    )
    if not np.allclose(chk["supply_avail_kt"], chk["obs_supply"], atol=1e-9):
        raise AssertionError("Observed supply consistency check failed")
    if not np.allclose(chk["import_need_kt"], chk["obs_need"], atol=1e-9):
        raise AssertionError("Observed import-need consistency check failed")

    # Constrained feasibility.
    con_supply = (
        constrained.groupby(["year", "material", "commodity", "origin_region"], as_index=False)["flow_kt"]
        .sum()
        .rename(columns={"origin_region": "region", "flow_kt": "con_export"})
    )
    con_need = (
        constrained.groupby(["year", "material", "commodity", "destination_region"], as_index=False)["flow_kt"]
        .sum()
        .rename(columns={"destination_region": "region", "flow_kt": "con_import"})
    )
    con_chk = (
        constraints.merge(con_supply, on=["year", "material", "commodity", "region"], how="left")
        .merge(con_need, on=["year", "material", "commodity", "region"], how="left")
        .fillna(0.0)
    )
    if (con_chk["con_export"] - con_chk["exportable_kt"] > 1e-8).any():
        bad = con_chk.loc[con_chk["con_export"] - con_chk["exportable_kt"] > 1e-8].head(10)
        raise AssertionError(f"Constrained export exceeds exportable cap. Examples:\n{bad}")
    if (con_chk["con_import"] - con_chk["import_need_kt"] > 1e-8).any():
        bad = con_chk.loc[con_chk["con_import"] - con_chk["import_need_kt"] > 1e-8].head(10)
        raise AssertionError(f"Constrained import exceeds need. Examples:\n{bad}")

    # Supplier share integrity.
    share_sum = (
        shares.groupby(
            ["mode", "year", "material", "commodity", "destination_region"], as_index=False
        )["share_origin_frac"]
        .sum()
        .rename(columns={"share_origin_frac": "share_sum"})
    )
    totals = pd.concat(
        [
            observed.assign(mode="observed"),
            constrained.assign(mode="constrained"),
        ],
        ignore_index=True,
    )
    totals = (
        totals.groupby(["mode", "year", "material", "commodity", "destination_region"], as_index=False)["flow_kt"]
        .sum()
        .rename(columns={"flow_kt": "dest_total"})
    )
    share_chk = share_sum.merge(
        totals, on=["mode", "year", "material", "commodity", "destination_region"], how="left"
    )
    pos = share_chk["dest_total"] > 0
    if not np.allclose(share_chk.loc[pos, "share_sum"], 1.0, atol=1e-9):
        bad = share_chk.loc[pos & ~np.isclose(share_chk["share_sum"], 1.0, atol=1e-9)].head(10)
        raise AssertionError(f"Supplier share sum != 1 for positive imports. Examples:\n{bad}")
    if not np.allclose(share_chk.loc[~pos, "share_sum"], 0.0, atol=1e-9):
        bad = share_chk.loc[(~pos) & (np.abs(share_chk["share_sum"]) > 1e-9)].head(10)
        raise AssertionError(f"Supplier share sum != 0 for zero imports. Examples:\n{bad}")

    # Sensitivity sanity: constrained totals should be <= observed totals by (year, material, commodity).
    obs_tot = (
        observed.groupby(["year", "material", "commodity"], as_index=False)["flow_kt"]
        .sum()
        .rename(columns={"flow_kt": "obs_total_kt"})
    )
    con_tot = (
        constrained.groupby(["year", "material", "commodity"], as_index=False)["flow_kt"]
        .sum()
        .rename(columns={"flow_kt": "con_total_kt"})
    )
    dev = obs_tot.merge(con_tot, on=["year", "material", "commodity"], how="left")
    dev["con_total_kt"] = dev["con_total_kt"].fillna(0.0)
    if (dev["con_total_kt"] - dev["obs_total_kt"] > 1e-8).any():
        bad = dev.loc[dev["con_total_kt"] - dev["obs_total_kt"] > 1e-8].head(10)
        raise AssertionError(f"Constrained total exceeds observed total. Examples:\n{bad}")

    return dev


def build_assumptions_md(
    source_by_year: Dict[int, str],
    fallback_log: pd.DataFrame,
    dev: pd.DataFrame,
    observed: pd.DataFrame,
    constrained: pd.DataFrame,
) -> str:
    fallback_counts = (
        fallback_log.groupby("fallback_type", as_index=False).size().sort_values("size", ascending=False)
        if not fallback_log.empty
        else pd.DataFrame(columns=["fallback_type", "size"])
    )
    fallback_lines = []
    if fallback_counts.empty:
        fallback_lines.append("- No weight fallback events were needed.")
    else:
        fallback_lines.append("- Weight fallback events (logged):")
        for r in fallback_counts.itertuples(index=False):
            fallback_lines.append(f"  - `{r.fallback_type}`: {int(r.size)} origin-year-material-commodity cases")

    dev = dev.copy()
    dev["delta_kt"] = dev["obs_total_kt"] - dev["con_total_kt"]
    dev["delta_pct"] = np.where(dev["obs_total_kt"] > 0, 100.0 * dev["delta_kt"] / dev["obs_total_kt"], 0.0)
    top_dev = dev.sort_values("delta_kt", ascending=False).head(12)
    top_lines = []
    for r in top_dev.itertuples(index=False):
        top_lines.append(
            f"- {r.year} | {r.material} | {r.commodity}: delta={r.delta_kt:,.2f} t ({r.delta_pct:.2f}%)"
        )
    if not top_lines:
        top_lines = ["- No deviations found."]

    hs92_years = sorted([y for y, src in source_by_year.items() if src == "HS92"])
    hs22_years = sorted([y for y, src in source_by_year.items() if src == "HS22"])

    obs_total = float(observed["flow_kt"].sum())
    con_total = float(constrained["flow_kt"].sum())

    return f"""# BACI OD Matrices Assumptions and Diagnostics

## Scope
- Region OD matrix level: `EU27`, `China`, `RoW` (3x3).
- Materials: `nickel`, `tin`, `zinc`.
- Commodities: `concentrates`, `refined_metal`, `scrap`.
- Units: metric tons (`flow_kt`, annual flow semantics).

## BACI period bridge
- HS92 years: {hs92_years[0]}-{hs92_years[-1]}.
- HS22 years: {hs22_years[0]}-{hs22_years[-1]}.
- No year overlap between HS sources.

## Mapping reuse
- HS code mapping reused from:
  - `/Users/alexcolloricchio/Desktop/CRMs/Data/processed/trade_observed/build_trade_observed.py`
- Includes strict codes + targeted ambiguous/intermediate codes with deterministic split shares.

## Weighting
- Annual OD share per origin: `s[t,o->d,m,c] = x_obs / sum_d x_obs`.
- Rolling preference weights: trailing {WEIGHT_WINDOW_YEARS}-year mean over available annual shares.
- Fallback hierarchy:
  1. same-year global destination mix for `(t,m,c)`
  2. uniform `[1/3, 1/3, 1/3]` when global mix unavailable

{chr(10).join(fallback_lines)}

## Export ceiling and allocator
- Export cap quantile: q={CAP_QUANTILE}, trailing window={CAP_WINDOW_YEARS} years.
- `exportable = min(supply_avail, export_cap_raw)`.
- Allocator:
  - pass 0: `x0 = exportable * w`, then destination absorption scaling to `x1`
  - pass 1: one residual reallocation pass (`{ALLOCATOR_REALLOCATION_PASSES}` pass total) to produce `x_final`

## Aggregate effect of constraints
- Total observed OD flow: {obs_total:,.2f} t
- Total constrained OD flow: {con_total:,.2f} t
- Total reduction: {obs_total - con_total:,.2f} t ({(100.0*(obs_total-con_total)/obs_total) if obs_total else 0.0:.2f}%)

## Largest cap-induced deviations by year/material/commodity
{chr(10).join(top_lines)}
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    module = load_trade_observed_module()

    print("[1/6] Building observed OD flows from BACI...")
    observed, source_by_year = build_observed_od(module)

    print("[2/6] Computing rolling OD preference weights...")
    weights, fallback_log = compute_rolling_weights(observed)

    print("[3/6] Building supply/need/cap constraints...")
    constraints = build_constraints(observed)

    print("[4/6] Running constrained OD allocator...")
    constrained, diagnostics = build_constrained_flows_and_diagnostics(observed, weights, constraints)

    print("[5/6] Building supplier shares + validations...")
    shares = build_supplier_shares(observed, constrained)
    dev = validate_outputs(observed, weights, constraints, constrained, shares, diagnostics, source_by_year)

    print("[6/6] Writing outputs...")
    observed_out = OUT_DIR / "baci_od_flow_observed.csv"
    weights_out = OUT_DIR / "baci_od_weights_rolling3.csv"
    constraints_out = OUT_DIR / "baci_od_constraints_inputs.csv"
    constrained_out = OUT_DIR / "baci_od_flow_constrained.csv"
    shares_out = OUT_DIR / "baci_od_supplier_shares.csv"
    diag_out = OUT_DIR / "baci_od_allocator_diagnostics.csv"
    assumptions_out = OUT_DIR / "baci_od_assumptions.md"

    observed.to_csv(observed_out, index=False)
    weights.to_csv(weights_out, index=False)
    constraints.to_csv(constraints_out, index=False)
    constrained.to_csv(constrained_out, index=False)
    shares.to_csv(shares_out, index=False)
    diagnostics.to_csv(diag_out, index=False)

    assumptions_out.write_text(
        build_assumptions_md(source_by_year, fallback_log, dev, observed, constrained),
        encoding="utf-8",
    )

    print("Done. Files written:")
    print(f"- {observed_out}")
    print(f"- {weights_out}")
    print(f"- {constraints_out}")
    print(f"- {constrained_out}")
    print(f"- {shares_out}")
    print(f"- {diag_out}")
    print(f"- {assumptions_out}")


if __name__ == "__main__":
    main()
