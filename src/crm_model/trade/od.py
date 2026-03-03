from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np
import pandas as pd


@dataclass
class TradeODArtifacts:
    flows: pd.DataFrame
    supplier_shares: pd.DataFrame
    supplier_diversification: pd.DataFrame
    diagnostics: pd.DataFrame
    imports_exports: pd.DataFrame


def _normalize_weights_for_origins(weights_od: np.ndarray) -> np.ndarray:
    out = np.array(weights_od, dtype=float)
    if out.ndim != 2:
        raise ValueError(f"weights_od must be 2D; got shape {out.shape}")
    o_len, d_len = out.shape
    for oi in range(o_len):
        row = out[oi, :]
        row = np.clip(row, 0.0, np.inf)
        row_sum = float(row.sum())
        if row_sum > 0:
            out[oi, :] = row / row_sum
        else:
            out[oi, :] = np.full(d_len, 1.0 / max(d_len, 1), dtype=float)
    return out


def _shock_multiplier_series(years: Sequence[int], event: Mapping[str, Any] | None) -> np.ndarray:
    mult = np.ones(len(years), dtype=float)
    if not event:
        return mult
    start_year = int(event["start_year"])
    duration_years = int(event["duration_years"])
    shock_mult = float(event["multiplier"])
    if duration_years < 0:
        raise ValueError("trade shock duration_years must be >= 0.")
    end_year = start_year + duration_years
    for i, y in enumerate(years):
        if start_year <= int(y) < end_year:
            mult[i] = shock_mult
    return mult


def _resolve_trade_need_multiplier(
    *,
    years: Sequence[int],
    shocks: Mapping[str, Any] | None,
    key: str,
) -> np.ndarray:
    shocks_map = shocks or {}
    event = shocks_map.get(key)
    if hasattr(event, "model_dump"):
        event = event.model_dump(exclude_none=True, exclude_unset=True)
    if event is not None and not isinstance(event, Mapping):
        raise ValueError(f"Unsupported trade shock event type for '{key}': {type(event)}")
    return _shock_multiplier_series(years, event)


def prepare_trade_weights_for_runtime(
    *,
    weights: pd.DataFrame,
    years: Sequence[int],
    materials: Sequence[str],
    regions: Sequence[str],
    commodities: Sequence[str],
    policy: str = "clamp_normalize",
) -> pd.DataFrame:
    required_w = {
        "year",
        "material",
        "commodity",
        "origin_region",
        "destination_region",
        "weight_0_1",
    }
    if not required_w.issubset(set(weights.columns)):
        raise ValueError("trade_od weights source missing required columns.")
    if str(policy).strip() != "clamp_normalize":
        raise ValueError("Unsupported trade_od weight extrapolation policy. Expected 'clamp_normalize'.")

    years_sorted = [int(y) for y in sorted({int(y) for y in years})]
    mats = [str(m) for m in materials]
    regs = [str(r) for r in regions]
    comms = [str(c) for c in commodities]

    base = weights.copy()
    base["year"] = pd.to_numeric(base["year"], errors="coerce").astype("Int64")
    base = base.dropna(subset=["year"]).copy()
    base["year"] = base["year"].astype(int)
    base["material"] = base["material"].astype(str)
    base["commodity"] = base["commodity"].astype(str)
    base["origin_region"] = base["origin_region"].astype(str)
    base["destination_region"] = base["destination_region"].astype(str)
    base["weight_0_1"] = pd.to_numeric(base["weight_0_1"], errors="coerce").fillna(0.0).astype(float)

    rows: List[dict] = []
    for material in mats:
        for commodity in comms:
            sub_mc = base[(base["material"] == material) & (base["commodity"] == commodity)]
            for origin in regs:
                sub_mco = sub_mc[sub_mc["origin_region"] == origin]
                if sub_mco.empty:
                    uniform = 1.0 / max(len(regs), 1)
                    for year in years_sorted:
                        for destination in regs:
                            rows.append(
                                {
                                    "year": int(year),
                                    "material": material,
                                    "commodity": commodity,
                                    "origin_region": origin,
                                    "destination_region": destination,
                                    "weight_0_1": float(uniform),
                                }
                            )
                    continue

                piv = (
                    sub_mco.pivot_table(
                        index="year",
                        columns="destination_region",
                        values="weight_0_1",
                        aggfunc="mean",
                    )
                    .reindex(columns=regs)
                    .sort_index()
                )
                piv = piv.reindex(index=years_sorted).ffill().bfill()
                piv = piv.fillna(0.0)
                for year in years_sorted:
                    row_arr = np.clip(piv.loc[int(year)].to_numpy(dtype=float), 0.0, np.inf)
                    row_sum = float(row_arr.sum())
                    if row_sum <= 0.0:
                        row_arr = np.full(len(regs), 1.0 / max(len(regs), 1), dtype=float)
                    else:
                        row_arr = row_arr / row_sum
                    for idx, destination in enumerate(regs):
                        rows.append(
                            {
                                "year": int(year),
                                "material": material,
                                "commodity": commodity,
                                "origin_region": origin,
                                "destination_region": destination,
                                "weight_0_1": float(row_arr[idx]),
                            }
                        )

    return pd.DataFrame(
        rows,
        columns=[
            "year",
            "material",
            "commodity",
            "origin_region",
            "destination_region",
            "weight_0_1",
        ],
    ).sort_values(["year", "material", "commodity", "origin_region", "destination_region"]).reset_index(drop=True)


def allocate_with_capacity_caps(
    *,
    exportable_o: np.ndarray,
    import_need_d: np.ndarray,
    weights_od: np.ndarray,
    max_reallocation_passes: int = 1,
) -> Tuple[np.ndarray, List[dict]]:
    """Allocate OD trade flows using weighted proposals + destination absorption + limited reallocation."""
    exportable = np.maximum(np.array(exportable_o, dtype=float), 0.0)
    import_need = np.maximum(np.array(import_need_d, dtype=float), 0.0)
    weights = _normalize_weights_for_origins(weights_od)
    o_len, d_len = weights.shape
    x = np.zeros((o_len, d_len), dtype=float)
    diagnostics: List[dict] = []

    # Pass 0: baseline weighted proposal.
    x0 = exportable[:, None] * weights
    demand0 = x0.sum(axis=0)
    scale0 = np.minimum(1.0, np.divide(import_need, demand0, out=np.zeros_like(import_need), where=demand0 > 0))
    x1 = x0 * scale0[None, :]
    x = x1.copy()
    residual_export = np.maximum(exportable - x.sum(axis=1), 0.0)
    residual_need = np.maximum(import_need - x.sum(axis=0), 0.0)
    for oi in range(o_len):
        for di in range(d_len):
            diagnostics.append(
                {
                    "pass_id": 0,
                    "origin_idx": oi,
                    "destination_idx": di,
                    "x0_kt": float(x0[oi, di]),
                    "x1_kt": float(x1[oi, di]),
                    "x_final_kt": float(x[oi, di]),
                    "residual_export_kt": float(residual_export[oi]),
                    "residual_import_need_kt": float(residual_need[di]),
                }
            )

    # Additional pass(es): redistribute residual export only to destinations still needing imports.
    for pass_id in range(1, max_reallocation_passes + 1):
        residual_export = np.maximum(exportable - x.sum(axis=1), 0.0)
        residual_need = np.maximum(import_need - x.sum(axis=0), 0.0)
        if float(residual_export.sum()) <= 1.0e-12 or float(residual_need.sum()) <= 1.0e-12:
            break

        proposal = np.zeros_like(x)
        eligible_dest = residual_need > 0
        for oi in range(o_len):
            exp_left = float(residual_export[oi])
            if exp_left <= 0:
                continue
            row_w = np.where(eligible_dest, weights[oi, :], 0.0)
            denom = float(row_w.sum())
            if denom <= 0:
                continue
            proposal[oi, :] = exp_left * (row_w / denom)

        demand = proposal.sum(axis=0)
        scale = np.minimum(1.0, np.divide(residual_need, demand, out=np.zeros_like(residual_need), where=demand > 0))
        accepted = proposal * scale[None, :]
        x = x + accepted
        residual_export = np.maximum(exportable - x.sum(axis=1), 0.0)
        residual_need = np.maximum(import_need - x.sum(axis=0), 0.0)
        for oi in range(o_len):
            for di in range(d_len):
                diagnostics.append(
                    {
                        "pass_id": pass_id,
                        "origin_idx": oi,
                        "destination_idx": di,
                        "x0_kt": float(proposal[oi, di]),
                        "x1_kt": float(accepted[oi, di]),
                        "x_final_kt": float(x[oi, di]),
                        "residual_export_kt": float(residual_export[oi]),
                        "residual_import_need_kt": float(residual_need[di]),
                    }
                )
    return x, diagnostics


def _normalize_supplier_governance_risk(
    *,
    supplier_governance_risk: pd.DataFrame,
    years: Sequence[int],
    origins: Sequence[str],
) -> pd.DataFrame:
    if supplier_governance_risk.empty:
        return pd.DataFrame(columns=["year", "origin_region", "value"])
    df = supplier_governance_risk.copy()
    df = df[["year", "origin_region", "value"]].copy()
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["origin_region"] = df["origin_region"].astype(str)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["year", "origin_region", "value"]).copy()
    if df.empty:
        return pd.DataFrame(columns=["year", "origin_region", "value"])
    df["year"] = df["year"].astype(int)
    df = (
        df.groupby(["year", "origin_region"], as_index=False)["value"]
        .mean()
        .sort_values(["origin_region", "year"])
        .reset_index(drop=True)
    )

    y_sorted = sorted({int(y) for y in years})
    rows: List[dict] = []
    for origin in [str(o) for o in origins]:
        sub = df[df["origin_region"] == origin].set_index("year")["value"].sort_index()
        if sub.empty:
            continue
        s = sub.reindex(y_sorted).ffill().bfill()
        if s.isna().any():
            s = s.fillna(float(sub.mean()))
        for y in y_sorted:
            rows.append({"year": int(y), "origin_region": origin, "value": float(s.loc[int(y)])})
    out = pd.DataFrame(rows, columns=["year", "origin_region", "value"])
    if out.empty:
        return out
    out["value"] = np.clip(out["value"].to_numpy(dtype=float), 0.0, 1.0)
    return out


def compute_supplier_diversification_indices(
    *,
    flows: pd.DataFrame,
    supplier_governance_risk: pd.DataFrame | None = None,
) -> pd.DataFrame:
    cols = [
        "year",
        "material",
        "region",
        "imports_total_kt",
        "supplier_hhi_0_1",
        "supplier_diversification_0_1",
        "effective_supplier_count",
        "top_supplier_share_0_1",
        "supplier_governance_risk_weighted_0_1",
    ]
    if flows.empty:
        return pd.DataFrame(columns=cols)

    by_origin = (
        flows.groupby(["year", "material", "destination_region", "origin_region"], as_index=False)["flow_kt"]
        .sum()
        .rename(columns={"flow_kt": "imports_from_origin_kt"})
    )
    totals = (
        by_origin.groupby(["year", "material", "destination_region"], as_index=False)["imports_from_origin_kt"]
        .sum()
        .rename(columns={"imports_from_origin_kt": "imports_total_kt"})
    )
    base = by_origin.merge(totals, on=["year", "material", "destination_region"], how="left")
    base["share_origin_frac"] = np.where(
        base["imports_total_kt"] > 0.0,
        base["imports_from_origin_kt"] / base["imports_total_kt"],
        0.0,
    )

    hhi = (
        base.assign(share_sq=base["share_origin_frac"] ** 2)
        .groupby(["year", "material", "destination_region"], as_index=False)["share_sq"]
        .sum()
        .rename(columns={"share_sq": "supplier_hhi_0_1"})
    )
    top1 = (
        base.groupby(["year", "material", "destination_region"], as_index=False)["share_origin_frac"]
        .max()
        .rename(columns={"share_origin_frac": "top_supplier_share_0_1"})
    )
    out = (
        totals.merge(hhi, on=["year", "material", "destination_region"], how="left")
        .merge(top1, on=["year", "material", "destination_region"], how="left")
        .rename(columns={"destination_region": "region"})
    )
    out["supplier_hhi_0_1"] = out["supplier_hhi_0_1"].fillna(0.0)
    out["supplier_diversification_0_1"] = np.clip(1.0 - out["supplier_hhi_0_1"], 0.0, 1.0)
    out["effective_supplier_count"] = np.where(
        out["supplier_hhi_0_1"] > 0.0,
        1.0 / out["supplier_hhi_0_1"],
        0.0,
    )
    out["top_supplier_share_0_1"] = out["top_supplier_share_0_1"].fillna(0.0)
    out["supplier_governance_risk_weighted_0_1"] = np.nan

    if supplier_governance_risk is not None and not supplier_governance_risk.empty:
        risk = _normalize_supplier_governance_risk(
            supplier_governance_risk=supplier_governance_risk,
            years=out["year"].astype(int).unique().tolist(),
            origins=base["origin_region"].astype(str).unique().tolist(),
        )
        if not risk.empty:
            wr = base.merge(risk, on=["year", "origin_region"], how="left")
            wr["value"] = wr["value"].fillna(float(risk["value"].mean()))
            wr["risk_x_share"] = wr["share_origin_frac"] * wr["value"]
            wgi = (
                wr.groupby(["year", "material", "destination_region"], as_index=False)["risk_x_share"]
                .sum()
                .rename(columns={"risk_x_share": "supplier_governance_risk_weighted_0_1"})
            )
            wgi = wgi.rename(columns={"destination_region": "region"})
            out = out.merge(
                wgi,
                on=["year", "material", "region"],
                how="left",
                suffixes=("", "_wgi"),
            )
            out["supplier_governance_risk_weighted_0_1"] = out[
                "supplier_governance_risk_weighted_0_1_wgi"
            ].fillna(out["supplier_governance_risk_weighted_0_1"])
            out = out.drop(columns=["supplier_governance_risk_weighted_0_1_wgi"])

    return out[cols].sort_values(["year", "material", "region"]).reset_index(drop=True)


def build_endogenous_trade_constraints(
    *,
    years: Sequence[int],
    material: str,
    regions: Sequence[str],
    commodities: Sequence[str],
    mfa_diagnostics_by_region: Mapping[str, Mapping[str, np.ndarray]],
    shocks_by_region: Mapping[str, Mapping[str, Any]] | None,
    concentrate_to_refined_coeff: float,
    scrap_to_secondary_coeff: float,
) -> pd.DataFrame:
    years_arr = np.array([int(y) for y in years], dtype=int)
    regions_list = [str(r) for r in regions]
    commodities_set = {str(c) for c in commodities}
    rows: List[dict] = []

    for region in regions_list:
        diag = mfa_diagnostics_by_region.get(region)
        if diag is None:
            raise ValueError(f"Missing MFA diagnostics for endogenous trade constraints: region={region}")

        refined_input_required = np.maximum(
            np.array(diag.get("refined_input_required_pre_cap", np.zeros(len(years_arr))), dtype=float),
            0.0,
        )
        primary_available = np.maximum(
            np.array(diag.get("primary_available_to_refining", np.zeros(len(years_arr))), dtype=float),
            0.0,
        )
        secondary_gap = np.maximum(
            np.array(diag.get("secondary_feed_gap_proxy", np.zeros(len(years_arr))), dtype=float),
            0.0,
        )
        secondary_surplus = np.maximum(
            np.array(diag.get("secondary_feed_surplus_proxy", np.zeros(len(years_arr))), dtype=float),
            0.0,
        )
        upstream_gap_refined_eq = np.maximum(
            np.array(
                diag.get("upstream_concentrate_gap_refined_equiv_proxy", np.zeros(len(years_arr))),
                dtype=float,
            ),
            0.0,
        )
        upstream_surplus_refined_eq = np.maximum(
            np.array(
                diag.get("upstream_concentrate_surplus_refined_equiv_proxy", np.zeros(len(years_arr))),
                dtype=float,
            ),
            0.0,
        )

        shocks_region = (shocks_by_region or {}).get(region, {})
        refined_need_mult = _resolve_trade_need_multiplier(
            years=years_arr,
            shocks=shocks_region,
            key="trade_refined_import_need_multiplier",
        )
        conc_need_mult = _resolve_trade_need_multiplier(
            years=years_arr,
            shocks=shocks_region,
            key="trade_concentrate_import_need_multiplier",
        )
        scrap_need_mult = _resolve_trade_need_multiplier(
            years=years_arr,
            shocks=shocks_region,
            key="trade_scrap_import_need_multiplier",
        )
        export_cap_mult = _resolve_trade_need_multiplier(
            years=years_arr,
            shocks=shocks_region,
            key="trade_export_capacity_multiplier",
        )

        refined_need = np.maximum(refined_input_required - primary_available, 0.0) * refined_need_mult
        refined_supply = np.maximum(primary_available - refined_input_required, 0.0)
        refined_cap = np.maximum(refined_supply * export_cap_mult, 0.0)

        conc_need = (upstream_gap_refined_eq / float(concentrate_to_refined_coeff)) * conc_need_mult
        conc_supply = upstream_surplus_refined_eq / float(concentrate_to_refined_coeff)
        conc_cap = np.maximum(conc_supply * export_cap_mult, 0.0)

        scrap_need = (secondary_gap / float(scrap_to_secondary_coeff)) * scrap_need_mult
        scrap_supply = secondary_surplus / float(scrap_to_secondary_coeff)
        scrap_cap = np.maximum(scrap_supply * export_cap_mult, 0.0)

        for yi, year in enumerate(years_arr):
            if "refined_metal" in commodities_set:
                rows.append(
                    {
                        "year": int(year),
                        "material": str(material),
                        "commodity": "refined_metal",
                        "region": str(region),
                        "supply_avail_kt": float(max(refined_supply[yi], 0.0)),
                        "import_need_kt": float(max(refined_need[yi], 0.0)),
                        "export_cap_raw_kt": float(max(refined_cap[yi], 0.0)),
                        "exportable_kt": float(max(refined_supply[yi], 0.0)),
                    }
                )
            if "concentrates" in commodities_set:
                rows.append(
                    {
                        "year": int(year),
                        "material": str(material),
                        "commodity": "concentrates",
                        "region": str(region),
                        "supply_avail_kt": float(max(conc_supply[yi], 0.0)),
                        "import_need_kt": float(max(conc_need[yi], 0.0)),
                        "export_cap_raw_kt": float(max(conc_cap[yi], 0.0)),
                        "exportable_kt": float(max(conc_supply[yi], 0.0)),
                    }
                )
            if "scrap" in commodities_set:
                rows.append(
                    {
                        "year": int(year),
                        "material": str(material),
                        "commodity": "scrap",
                        "region": str(region),
                        "supply_avail_kt": float(max(scrap_supply[yi], 0.0)),
                        "import_need_kt": float(max(scrap_need[yi], 0.0)),
                        "export_cap_raw_kt": float(max(scrap_cap[yi], 0.0)),
                        "exportable_kt": float(max(scrap_supply[yi], 0.0)),
                    }
                )

    return pd.DataFrame(
        rows,
        columns=[
            "year",
            "material",
            "commodity",
            "region",
            "supply_avail_kt",
            "import_need_kt",
            "export_cap_raw_kt",
            "exportable_kt",
        ],
    ).sort_values(["year", "material", "commodity", "region"]).reset_index(drop=True)


def compute_net_trade_imports_by_commodity_region(
    *,
    imports_exports: pd.DataFrame,
    years: Sequence[int],
    material: str,
    regions: Sequence[str],
    commodities: Sequence[str],
) -> Dict[str, np.ndarray]:
    out: Dict[str, np.ndarray] = {
        str(c): np.zeros((len(years), len(regions)), dtype=float) for c in commodities
    }
    if imports_exports.empty:
        return out

    years_list = [int(y) for y in years]
    year_to_idx = {int(y): i for i, y in enumerate(years_list)}
    region_to_idx = {str(r): i for i, r in enumerate(regions)}
    sub = imports_exports[imports_exports["material"].astype(str) == str(material)].copy()
    if sub.empty:
        return out
    for row in sub.itertuples(index=False):
        commodity = str(getattr(row, "commodity"))
        if commodity not in out:
            continue
        year = int(getattr(row, "year"))
        region = str(getattr(row, "region"))
        yi = year_to_idx.get(year)
        ri = region_to_idx.get(region)
        if yi is None or ri is None:
            continue
        imports_v = float(getattr(row, "imports_kt", 0.0))
        exports_v = float(getattr(row, "exports_kt", 0.0))
        out[commodity][yi, ri] = imports_v - exports_v
    return out


def run_trade_od_allocator(
    *,
    years: Sequence[int],
    materials: Sequence[str],
    regions: Sequence[str],
    commodities: Sequence[str],
    observed_flows: pd.DataFrame | None,
    weights: pd.DataFrame,
    constraints: pd.DataFrame,
    sd_capacity_envelope_by_material_region: Mapping[Tuple[str, str], np.ndarray],
    supplier_governance_risk: pd.DataFrame | None = None,
    historical_window_start_year: int,
    historical_window_end_year: int,
    capacity_cap_hybrid_mode: str,
    capacity_cap_sd_multiplier: float,
    coupling_relax_lambda_0_1: float,
    max_reallocation_passes: int,
) -> TradeODArtifacts:
    """Run constrained OD allocator for the provided years."""
    reg_list = [str(r) for r in regions]
    years_list = [int(y) for y in years]
    year_to_idx = {int(y): i for i, y in enumerate(years_list)}
    active_years = sorted({int(y) for y in years_list})

    flow_rows: List[dict] = []
    diag_rows: List[dict] = []
    cap_prev: Dict[Tuple[str, str, str], float] = {}

    for year in active_years:
        for material in materials:
            for commodity in commodities:
                csub = constraints[
                    (constraints["year"] == year)
                    & (constraints["material"] == material)
                    & (constraints["commodity"] == commodity)
                ]
                if csub.empty:
                    continue

                wsub = weights[
                    (weights["year"] == year)
                    & (weights["material"] == material)
                    & (weights["commodity"] == commodity)
                ]
                if wsub.empty:
                    # Conservative fallback when no weights are available for this slice.
                    w_mat = np.full((len(reg_list), len(reg_list)), 1.0 / max(len(reg_list), 1), dtype=float)
                else:
                    p = (
                        wsub.pivot_table(
                            index="origin_region",
                            columns="destination_region",
                            values="weight_0_1",
                            aggfunc="mean",
                            fill_value=0.0,
                        )
                        .reindex(index=reg_list, columns=reg_list, fill_value=0.0)
                    )
                    w_mat = p.to_numpy(dtype=float)
                w_mat = _normalize_weights_for_origins(w_mat)

                by_region = csub.set_index("region").reindex(reg_list)
                supply = by_region["supply_avail_kt"].fillna(0.0).to_numpy(dtype=float)
                import_need = by_region["import_need_kt"].fillna(0.0).to_numpy(dtype=float)
                empirical_cap = by_region["export_cap_raw_kt"].fillna(0.0).to_numpy(dtype=float)

                sd_cap = np.zeros_like(supply, dtype=float)
                for oi, origin in enumerate(reg_list):
                    cap_ts = sd_capacity_envelope_by_material_region.get((str(material), str(origin)))
                    cap_factor = 1.0
                    if cap_ts is not None and len(cap_ts) == len(years):
                        y_idx = year_to_idx[int(year)]
                        cap_factor = max(float(cap_ts[y_idx]), 0.0)
                    sd_cap[oi] = max(supply[oi] * cap_factor * float(capacity_cap_sd_multiplier), 0.0)

                if capacity_cap_hybrid_mode == "empirical_only":
                    cap_raw = empirical_cap
                elif capacity_cap_hybrid_mode == "sd_only":
                    cap_raw = sd_cap
                else:
                    cap_raw = np.minimum(empirical_cap, sd_cap)

                cap_smoothed = np.zeros_like(cap_raw)
                alpha = float(coupling_relax_lambda_0_1)
                for oi, origin in enumerate(reg_list):
                    key = (str(material), str(commodity), str(origin))
                    prev = cap_prev.get(key)
                    if prev is None:
                        cap_smoothed[oi] = cap_raw[oi]
                    else:
                        cap_smoothed[oi] = (1.0 - alpha) * float(prev) + alpha * float(cap_raw[oi])
                    cap_prev[key] = float(cap_smoothed[oi])

                exportable = np.minimum(supply, np.maximum(cap_smoothed, 0.0))
                x, diag = allocate_with_capacity_caps(
                    exportable_o=exportable,
                    import_need_d=import_need,
                    weights_od=w_mat,
                    max_reallocation_passes=max_reallocation_passes,
                )

                for oi, origin in enumerate(reg_list):
                    for di, dest in enumerate(reg_list):
                        flow_rows.append(
                            {
                                "year": int(year),
                                "material": str(material),
                                "commodity": str(commodity),
                                "origin_region": str(origin),
                                "destination_region": str(dest),
                                "flow_kt": float(x[oi, di]),
                            }
                        )
                for row in diag:
                    row_out = {
                        "year": int(year),
                        "material": str(material),
                        "commodity": str(commodity),
                        "origin_region": str(reg_list[int(row["origin_idx"])]),
                        "destination_region": str(reg_list[int(row["destination_idx"])]),
                        "x0_kt": float(row["x0_kt"]),
                        "x1_kt": float(row["x1_kt"]),
                        "x_final_kt": float(row["x_final_kt"]),
                        "residual_export_kt": float(row["residual_export_kt"]),
                        "residual_import_need_kt": float(row["residual_import_need_kt"]),
                        "pass_id": int(row["pass_id"]),
                    }
                    diag_rows.append(row_out)

    flows = pd.DataFrame(
        flow_rows,
        columns=[
            "year",
            "material",
            "commodity",
            "origin_region",
            "destination_region",
            "flow_kt",
        ],
    )
    if flows.empty:
        return TradeODArtifacts(
            flows=flows,
            supplier_shares=pd.DataFrame(),
            supplier_diversification=pd.DataFrame(),
            diagnostics=pd.DataFrame(),
            imports_exports=pd.DataFrame(),
        )

    imports_df = (
        flows.groupby(["year", "material", "commodity", "destination_region"], as_index=False)["flow_kt"]
        .sum()
        .rename(columns={"destination_region": "region", "flow_kt": "imports_kt"})
    )
    exports_df = (
        flows.groupby(["year", "material", "commodity", "origin_region"], as_index=False)["flow_kt"]
        .sum()
        .rename(columns={"origin_region": "region", "flow_kt": "exports_kt"})
    )
    imports_exports = imports_df.merge(
        exports_df, on=["year", "material", "commodity", "region"], how="outer"
    ).fillna(0.0)

    totals = (
        flows.groupby(["year", "material", "commodity", "destination_region"], as_index=False)["flow_kt"]
        .sum()
        .rename(columns={"flow_kt": "dest_total_kt"})
    )
    supplier_shares = flows.merge(
        totals, on=["year", "material", "commodity", "destination_region"], how="left"
    )
    supplier_shares["share_origin_frac"] = np.where(
        supplier_shares["dest_total_kt"] > 0,
        supplier_shares["flow_kt"] / supplier_shares["dest_total_kt"],
        0.0,
    )
    supplier_shares = supplier_shares[
        ["year", "material", "commodity", "destination_region", "origin_region", "share_origin_frac"]
    ].sort_values(
        ["year", "material", "commodity", "destination_region", "origin_region"]
    )

    diagnostics = pd.DataFrame(
        diag_rows,
        columns=[
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
        ],
    ).sort_values(["year", "material", "commodity", "pass_id", "origin_region", "destination_region"])

    # Sanity checks for allocation feasibility.
    con_supply = (
        flows.groupby(["year", "material", "commodity", "origin_region"], as_index=False)["flow_kt"]
        .sum()
        .rename(columns={"origin_region": "region", "flow_kt": "con_export"})
    )
    con_need = (
        flows.groupby(["year", "material", "commodity", "destination_region"], as_index=False)["flow_kt"]
        .sum()
        .rename(columns={"destination_region": "region", "flow_kt": "con_import"})
    )
    constraint_active = constraints[
        constraints["year"].isin(active_years)
        & constraints["material"].isin(list(materials))
        & constraints["commodity"].isin(list(commodities))
        & constraints["region"].isin(reg_list)
    ]
    chk = (
        constraint_active.merge(con_supply, on=["year", "material", "commodity", "region"], how="left")
        .merge(con_need, on=["year", "material", "commodity", "region"], how="left")
        .fillna(0.0)
    )
    if (chk["con_export"] - chk["supply_avail_kt"] > 1e-8).any():
        raise ValueError("trade_od allocation infeasible: modeled exports exceed available supply.")
    if (chk["con_import"] - chk["import_need_kt"] > 1e-8).any():
        raise ValueError("trade_od allocation infeasible: modeled imports exceed import need.")

    supplier_div = compute_supplier_diversification_indices(
        flows=flows,
        supplier_governance_risk=supplier_governance_risk,
    )

    return TradeODArtifacts(
        flows=flows.sort_values(["year", "material", "commodity", "origin_region", "destination_region"]).reset_index(
            drop=True
        ),
        supplier_shares=supplier_shares.reset_index(drop=True),
        supplier_diversification=supplier_div,
        diagnostics=diagnostics.reset_index(drop=True),
        imports_exports=imports_exports.sort_values(["year", "material", "commodity", "region"]).reset_index(
            drop=True
        ),
    )


def validate_trade_od_sources(
    *,
    observed_flows: pd.DataFrame,
    weights: pd.DataFrame,
    constraints: pd.DataFrame,
    materials: Iterable[str],
    regions: Iterable[str],
    commodities: Iterable[str],
) -> None:
    required_obs = {
        "year",
        "material",
        "commodity",
        "origin_region",
        "destination_region",
        "flow_kt",
    }
    required_w = {
        "year",
        "material",
        "commodity",
        "origin_region",
        "destination_region",
        "weight_0_1",
    }
    required_c = {
        "year",
        "material",
        "commodity",
        "region",
        "supply_avail_kt",
        "import_need_kt",
        "export_cap_raw_kt",
        "exportable_kt",
    }
    if not required_obs.issubset(set(observed_flows.columns)):
        raise ValueError("trade_od observed source missing required columns.")
    if not required_w.issubset(set(weights.columns)):
        raise ValueError("trade_od weights source missing required columns.")
    if not required_c.issubset(set(constraints.columns)):
        raise ValueError("trade_od constraints source missing required columns.")

    mats = {str(m) for m in materials}
    regs = {str(r) for r in regions}
    comms = {str(c) for c in commodities}

    for name, df in [
        ("observed_flows", observed_flows),
        ("weights", weights),
        ("constraints", constraints),
    ]:
        if not set(df["material"].astype(str).unique()).issubset(mats):
            raise ValueError(f"trade_od {name} contains unknown materials.")
        if not set(df["commodity"].astype(str).unique()).issubset(comms):
            raise ValueError(f"trade_od {name} contains unknown commodities.")

    if not set(observed_flows["origin_region"].astype(str).unique()).issubset(regs):
        raise ValueError("trade_od observed_flows contains unknown origin_region values.")
    if not set(observed_flows["destination_region"].astype(str).unique()).issubset(regs):
        raise ValueError("trade_od observed_flows contains unknown destination_region values.")
    if not set(weights["origin_region"].astype(str).unique()).issubset(regs):
        raise ValueError("trade_od weights contains unknown origin_region values.")
    if not set(weights["destination_region"].astype(str).unique()).issubset(regs):
        raise ValueError("trade_od weights contains unknown destination_region values.")
    if not set(constraints["region"].astype(str).unique()).issubset(regs):
        raise ValueError("trade_od constraints contains unknown region values.")


def validate_trade_od_runtime_weights(
    *,
    weights: pd.DataFrame,
    materials: Iterable[str],
    regions: Iterable[str],
    commodities: Iterable[str],
) -> None:
    required = {
        "year",
        "material",
        "commodity",
        "origin_region",
        "destination_region",
        "weight_0_1",
    }
    if not required.issubset(set(weights.columns)):
        raise ValueError("trade_od weights source missing required columns.")
    mats = {str(m) for m in materials}
    regs = {str(r) for r in regions}
    comms = {str(c) for c in commodities}
    if not set(weights["material"].astype(str).unique()).issubset(mats):
        raise ValueError("trade_od weights contains unknown materials.")
    if not set(weights["commodity"].astype(str).unique()).issubset(comms):
        raise ValueError("trade_od weights contains unknown commodities.")
    if not set(weights["origin_region"].astype(str).unique()).issubset(regs):
        raise ValueError("trade_od weights contains unknown origin_region values.")
    if not set(weights["destination_region"].astype(str).unique()).issubset(regs):
        raise ValueError("trade_od weights contains unknown destination_region values.")
