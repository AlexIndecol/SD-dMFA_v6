#!/usr/bin/env python
from __future__ import annotations

import argparse
from datetime import datetime
from itertools import product
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from scipy.optimize import minimize

from crm_model.cli import run_one_variant
from crm_model.common.io import load_run_config, resolve_repo_root_from_config
from crm_model.common.validation import validate_exogenous_inputs


def _parse_variable_weights(spec: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for token in str(spec).split(","):
        token = token.strip()
        if not token:
            continue
        if ":" not in token:
            raise ValueError(
                "variable weight spec must use key:value entries, "
                f"got '{token}'"
            )
        k, v = token.split(":", 1)
        key = k.strip()
        val = float(v.strip())
        if val <= 0:
            raise ValueError(f"variable weight must be >0 for '{key}', got {val}")
        out[key] = val
    if not out:
        raise ValueError("No variable weights parsed from --variable-weights")
    return out


def _read_csv_required(path: Path, required: Iterable[str]) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = sorted(set(required) - set(df.columns))
    if missing:
        raise ValueError(f"{path} missing required columns: {missing}")
    return df


def _normalize_key_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["year"] = pd.to_numeric(out["year"], errors="coerce").astype("Int64")
    out = out.dropna(subset=["year"])\
             .copy()
    out["year"] = out["year"].astype(int)
    out["material"] = out["material"].astype(str).str.strip().str.lower()
    out["region"] = out["region"].astype(str).str.strip()
    return out


def _load_observed(path: Path, *, start_year: int, end_year: int) -> pd.DataFrame:
    df = _read_csv_required(path, ["year", "material", "region", "value"])
    df = _normalize_key_cols(df)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"]).copy()
    df = df[(df["year"] >= start_year) & (df["year"] <= end_year)].copy()
    return df[["year", "material", "region", "value"]]


def _winsorize(values: np.ndarray, q_low: float = 0.02, q_high: float = 0.98) -> np.ndarray:
    if values.size == 0:
        return values
    lo = float(np.quantile(values, q_low))
    hi = float(np.quantile(values, q_high))
    return np.clip(values, lo, hi)


def _build_raw_targets(
    *,
    obs_refined: pd.DataFrame,
    obs_benef: pd.DataFrame,
    obs_extract: pd.DataFrame,
) -> Dict[Tuple[str, str], Dict[str, pd.DataFrame]]:
    keys = ["year", "material", "region"]

    ref_merge = obs_refined.rename(columns={"value": "refined_obs"}).merge(
        obs_benef.rename(columns={"value": "benef_obs"}), on=keys, how="inner"
    )
    ref_merge = ref_merge[ref_merge["benef_obs"] > 0].copy()
    ref_merge["raw"] = ref_merge["refined_obs"] / ref_merge["benef_obs"]

    ben_merge = obs_benef.rename(columns={"value": "benef_obs"}).merge(
        obs_extract.rename(columns={"value": "extract_obs"}), on=keys, how="inner"
    )
    ben_merge = ben_merge[ben_merge["extract_obs"] > 0].copy()
    ben_merge["raw"] = ben_merge["benef_obs"] / ben_merge["extract_obs"]

    targets: Dict[Tuple[str, str], Dict[str, pd.DataFrame]] = {}
    for (mat, reg), grp in ref_merge.groupby(["material", "region"], as_index=False):
        v = pd.to_numeric(grp["raw"], errors="coerce").to_numpy(dtype=float)
        y = grp["year"].to_numpy(dtype=int)
        m = np.isfinite(v)
        v = v[m]
        y = y[m]
        if v.size == 0:
            continue
        v = _winsorize(np.clip(v, 0.01, 0.999))
        targets.setdefault((str(mat), str(reg)), {})["refining_yield"] = pd.DataFrame(
            {"year": y, "raw": v}
        ).sort_values("year")

    for (mat, reg), grp in ben_merge.groupby(["material", "region"], as_index=False):
        v = pd.to_numeric(grp["raw"], errors="coerce").to_numpy(dtype=float)
        y = grp["year"].to_numpy(dtype=int)
        m = np.isfinite(v)
        v = v[m]
        y = y[m]
        if v.size == 0:
            continue
        v = _winsorize(np.clip(v, 0.01, 0.999))
        targets.setdefault((str(mat), str(reg)), {})["beneficiation_yield"] = pd.DataFrame(
            {"year": y, "raw": v}
        ).sort_values("year")

    return targets


def _fit_piecewise_smooth(
    *,
    years_obs: np.ndarray,
    values_obs: np.ndarray,
    fit_years: np.ndarray,
    anchors: np.ndarray,
    smooth_lambda: float,
) -> np.ndarray:
    if years_obs.size == 0 or values_obs.size == 0:
        return np.full(fit_years.shape, np.nan, dtype=float)

    order = np.argsort(years_obs)
    years_obs = years_obs[order]
    values_obs = values_obs[order]

    if years_obs.size == 1:
        v = float(np.clip(values_obs[0], 0.01, 0.999))
        return np.full(fit_years.shape, v, dtype=float)

    x0 = np.interp(anchors, years_obs, values_obs, left=values_obs[0], right=values_obs[-1])
    x0 = np.clip(x0, 0.01, 0.999)

    def objective(x: np.ndarray) -> float:
        pred_obs = np.interp(years_obs, anchors, x)
        fit_term = float(np.mean((pred_obs - values_obs) ** 2))
        if x.size >= 3:
            curv = x[2:] - 2.0 * x[1:-1] + x[:-2]
            smooth_term = float(np.mean(curv**2))
        else:
            smooth_term = 0.0
        return fit_term + float(smooth_lambda) * smooth_term

    bounds = [(0.01, 0.999)] * int(anchors.size)
    res = minimize(objective, x0=x0, method="L-BFGS-B", bounds=bounds)
    x_star = np.clip(res.x if res.success else x0, 0.01, 0.999)
    pred_fit = np.interp(fit_years, anchors, x_star)
    return np.clip(pred_fit, 0.01, 0.999)


def _effective_pair_lambda(values_obs: np.ndarray, global_lambda: float, *, enabled: bool) -> float:
    if not enabled:
        return float(global_lambda)
    v = np.asarray(values_obs, dtype=float)
    v = v[np.isfinite(v)]
    if v.size < 5:
        return float(global_lambda)
    scale_ref = max(1e-12, float(np.mean(np.abs(v))))
    if v.size >= 3:
        roughness = float(np.mean(np.abs(v[2:] - 2.0 * v[1:-1] + v[:-2])) / scale_ref)
    else:
        roughness = 0.0
    # Rougher series get less smoothing; smoother series keep near-global lambda.
    factor = float(np.clip(1.0 / (1.0 + 8.0 * roughness), 0.35, 1.5))
    return float(global_lambda * factor)


def _build_candidate_stage(
    *,
    base_stage: pd.DataFrame,
    raw_targets: Dict[Tuple[str, str], Dict[str, pd.DataFrame]],
    fit_start: int,
    fit_end: int,
    smooth_lambda: float,
    smooth_lambda_by_region: Dict[str, float] | None,
    pair_specific_smoothing: bool,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    df = _normalize_key_cols(base_stage)
    all_years = np.array(sorted(df["year"].unique().tolist()), dtype=int)
    fit_years = np.arange(fit_start, fit_end + 1, dtype=int)
    anchors = np.arange(fit_start, fit_end + 1, 5, dtype=int)
    if anchors[-1] != fit_end:
        anchors = np.append(anchors, fit_end)

    pair_rows: List[Dict[str, Any]] = []
    diag_rows: List[Dict[str, Any]] = []

    pair_keys = (
        df[["material", "region"]]
        .drop_duplicates()
        .sort_values(["material", "region"])
        .itertuples(index=False, name=None)
    )

    for mat, reg in pair_keys:
        lambda_base = (
            float(smooth_lambda_by_region.get(str(reg), smooth_lambda))
            if smooth_lambda_by_region is not None
            else float(smooth_lambda)
        )
        sub = df[(df["material"] == mat) & (df["region"] == reg)].sort_values("year")
        base_b = sub.set_index("year")["beneficiation_yield"].reindex(fit_years).to_numpy(dtype=float)
        base_r = sub.set_index("year")["refining_yield"].reindex(fit_years).to_numpy(dtype=float)

        tgt = raw_targets.get((mat, reg), {})
        ben_raw_df = tgt.get("beneficiation_yield")
        ref_raw_df = tgt.get("refining_yield")

        if ben_raw_df is None or ben_raw_df.empty:
            ben_fit = np.clip(base_b, 0.01, 0.999)
            ben_raw_lookup: Dict[int, float] = {}
            ben_lambda_eff = float(lambda_base)
        else:
            years_obs = ben_raw_df["year"].to_numpy(dtype=int)
            vals_obs = np.clip(ben_raw_df["raw"].to_numpy(dtype=float), 0.01, 0.999)
            ben_lambda_eff = _effective_pair_lambda(
                vals_obs,
                lambda_base,
                enabled=pair_specific_smoothing,
            )
            ben_fit = _fit_piecewise_smooth(
                years_obs=years_obs,
                values_obs=vals_obs,
                fit_years=fit_years,
                anchors=anchors,
                smooth_lambda=ben_lambda_eff,
            )
            ben_raw_lookup = dict(zip(years_obs.tolist(), vals_obs.tolist()))

        if ref_raw_df is None or ref_raw_df.empty:
            ref_fit = np.clip(base_r, 0.01, 0.999)
            ref_raw_lookup = {}
            ref_lambda_eff = float(lambda_base)
        else:
            years_obs = ref_raw_df["year"].to_numpy(dtype=int)
            vals_obs = np.clip(ref_raw_df["raw"].to_numpy(dtype=float), 0.01, 0.999)
            ref_lambda_eff = _effective_pair_lambda(
                vals_obs,
                lambda_base,
                enabled=pair_specific_smoothing,
            )
            ref_fit = _fit_piecewise_smooth(
                years_obs=years_obs,
                values_obs=vals_obs,
                fit_years=fit_years,
                anchors=anchors,
                smooth_lambda=ref_lambda_eff,
            )
            ref_raw_lookup = dict(zip(years_obs.tolist(), vals_obs.tolist()))

        ben_first, ben_last = float(ben_fit[0]), float(ben_fit[-1])
        ref_first, ref_last = float(ref_fit[0]), float(ref_fit[-1])

        ben_fit_lookup = dict(zip(fit_years.tolist(), ben_fit.tolist()))
        ref_fit_lookup = dict(zip(fit_years.tolist(), ref_fit.tolist()))

        for y in all_years.tolist():
            ben_v = ben_fit_lookup.get(y, ben_first if y < fit_start else ben_last)
            ref_v = ref_fit_lookup.get(y, ref_first if y < fit_start else ref_last)
            pair_rows.append(
                {
                    "year": int(y),
                    "material": mat,
                    "region": reg,
                    "beneficiation_yield_fit": float(ben_v),
                    "refining_yield_fit": float(ref_v),
                }
            )

        base_b_lookup = dict(zip(fit_years.tolist(), base_b.tolist()))
        base_r_lookup = dict(zip(fit_years.tolist(), base_r.tolist()))
        for y in fit_years.tolist():
            diag_rows.append(
                {
                    "year": int(y),
                    "material": mat,
                    "region": reg,
                    "yield_name": "beneficiation_yield",
                    "raw_value": ben_raw_lookup.get(y, np.nan),
                    "smoothed_value": float(ben_fit_lookup[y]),
                    "base_value": float(base_b_lookup.get(y, np.nan)),
                    "smooth_lambda_global": float(lambda_base),
                    "smooth_lambda_effective": float(ben_lambda_eff),
                }
            )
            diag_rows.append(
                {
                    "year": int(y),
                    "material": mat,
                    "region": reg,
                    "yield_name": "refining_yield",
                    "raw_value": ref_raw_lookup.get(y, np.nan),
                    "smoothed_value": float(ref_fit_lookup[y]),
                    "base_value": float(base_r_lookup.get(y, np.nan)),
                    "smooth_lambda_global": float(lambda_base),
                    "smooth_lambda_effective": float(ref_lambda_eff),
                }
            )

    fit_panel = pd.DataFrame(pair_rows)
    out = df.merge(fit_panel, on=["year", "material", "region"], how="left")
    out["beneficiation_yield"] = out["beneficiation_yield_fit"].fillna(out["beneficiation_yield"])
    out["refining_yield"] = out["refining_yield_fit"].fillna(out["refining_yield"])
    out = out.drop(columns=["beneficiation_yield_fit", "refining_yield_fit"])

    for c in ["beneficiation_yield", "refining_yield", "extraction_yield", "sorting_yield"]:
        out[c] = np.clip(pd.to_numeric(out[c], errors="coerce"), 0.0, 1.0)

    for c in [
        "extraction_loss_to_sysenv_share",
        "beneficiation_loss_to_sysenv_share",
        "refining_loss_to_sysenv_share",
        "sorting_reject_to_disposal_share",
        "sorting_reject_to_sysenv_share",
    ]:
        out[c] = np.clip(pd.to_numeric(out[c], errors="coerce"), 0.0, 1.0)

    reject_sum = out["sorting_reject_to_disposal_share"] + out["sorting_reject_to_sysenv_share"]
    reject_sum = reject_sum.replace(0.0, 1.0)
    out["sorting_reject_to_disposal_share"] = out["sorting_reject_to_disposal_share"] / reject_sum
    out["sorting_reject_to_sysenv_share"] = out["sorting_reject_to_sysenv_share"] / reject_sum

    out = out.sort_values(["year", "material", "region"]).reset_index(drop=True)
    diag = pd.DataFrame(diag_rows)
    return out, diag


def _extract_indicator(ts_df: pd.DataFrame, indicator: str) -> pd.DataFrame:
    sub = ts_df[ts_df["indicator"] == indicator][["material", "region", "year", "value"]].copy()
    out = (
        sub.groupby(["material", "region", "year"], as_index=False)["value"]
        .sum()
        .rename(columns={"value": "model_value"})
    )
    out["material"] = out["material"].astype(str).str.lower()
    out["region"] = out["region"].astype(str)
    return out


def _metrics_by_pair(joined: pd.DataFrame, var_name: str) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for (mat, reg), g in joined.groupby(["material", "region"], as_index=False):
        g = g.dropna(subset=["observed_value", "model_value"]).copy()
        if g.empty:
            continue
        e = g["model_value"].to_numpy(dtype=float) - g["observed_value"].to_numpy(dtype=float)
        rmse = float(np.sqrt(np.mean(e**2)))
        mae = float(np.mean(np.abs(e)))
        mean_obs = float(np.mean(np.abs(g["observed_value"].to_numpy(dtype=float))))
        nrmse = float(rmse / mean_obs) if mean_obs > 0 else np.nan
        rows.append(
            {
                "observed_variable": var_name,
                "material": str(mat),
                "region": str(reg),
                "n_years": int(len(g)),
                "rmse": rmse,
                "mae": mae,
                "mean_obs": mean_obs,
                "nrmse": nrmse,
            }
        )
    return pd.DataFrame(rows)


def _compute_upstream_metrics(
    *,
    ts_df: pd.DataFrame,
    stage_df: pd.DataFrame,
    obs_refined: pd.DataFrame,
    obs_benef: pd.DataFrame,
    obs_extract: pd.DataFrame,
    fit_start: int,
    fit_end: int,
    variable_weights: Dict[str, float],
) -> Tuple[pd.DataFrame, float]:
    primary = _extract_indicator(ts_df, "Primary_supply")
    primary = primary[(primary["year"] >= fit_start) & (primary["year"] <= fit_end)].copy()

    stage = _normalize_key_cols(stage_df)
    stage = stage[(stage["year"] >= fit_start) & (stage["year"] <= fit_end)][
        ["year", "material", "region", "beneficiation_yield", "refining_yield"]
    ].copy()

    m = primary.merge(stage, on=["year", "material", "region"], how="left")
    eps = 1e-12
    m["benef_proxy"] = m["model_value"] / np.maximum(pd.to_numeric(m["refining_yield"], errors="coerce"), eps)
    m["extract_proxy"] = m["model_value"] / np.maximum(
        pd.to_numeric(m["refining_yield"], errors="coerce") * pd.to_numeric(m["beneficiation_yield"], errors="coerce"),
        eps,
    )

    obs_ref = _normalize_key_cols(obs_refined.rename(columns={"value": "observed_value"}))
    obs_ben = _normalize_key_cols(obs_benef.rename(columns={"value": "observed_value"}))
    obs_ext = _normalize_key_cols(obs_extract.rename(columns={"value": "observed_value"}))

    keys = ["year", "material", "region"]
    ref_join = obs_ref.merge(m[keys + ["model_value"]], on=keys, how="inner")
    ben_join = obs_ben.merge(m[keys + ["benef_proxy"]].rename(columns={"benef_proxy": "model_value"}), on=keys, how="inner")
    ext_join = obs_ext.merge(m[keys + ["extract_proxy"]].rename(columns={"extract_proxy": "model_value"}), on=keys, how="inner")

    ref_metrics = _metrics_by_pair(ref_join, "primary_refined_observed")
    ben_metrics = _metrics_by_pair(ben_join, "beneficiation_output_observed")
    ext_metrics = _metrics_by_pair(ext_join, "primary_extraction_observed")

    all_metrics = pd.concat([ref_metrics, ben_metrics, ext_metrics], ignore_index=True)
    if all_metrics.empty:
        score = float("inf")
    else:
        w = all_metrics["observed_variable"].map(lambda x: float(variable_weights.get(str(x), 1.0))).to_numpy(dtype=float)
        score = float(np.average(all_metrics["nrmse"].to_numpy(dtype=float), weights=w))
    return all_metrics, score


def _window_pair_metrics(
    merged: pd.DataFrame,
    years: Iterable[int],
    *,
    min_required_years: int,
) -> pd.DataFrame:
    yset = set(int(y) for y in years)
    sub = merged[merged["year"].isin(yset)].copy()
    if sub.empty:
        return pd.DataFrame(columns=["material", "region", "n_years", "rmse", "mae", "mean_obs", "nrmse"])

    rows: List[Dict[str, Any]] = []
    for (mat, reg), grp in sub.groupby(["material", "region"]):
        grp = grp.dropna(subset=["model", "obs"])
        n = int(len(grp))
        if n < int(min_required_years):
            continue
        err = grp["model"].to_numpy(dtype=float) - grp["obs"].to_numpy(dtype=float)
        rmse = float(np.sqrt(np.mean(err**2)))
        mae = float(np.mean(np.abs(err)))
        mean_obs = float(np.mean(np.abs(grp["obs"].to_numpy(dtype=float))))
        nrmse = float(rmse / mean_obs) if mean_obs > 0 else np.nan
        rows.append({"material": str(mat), "region": str(reg), "n_years": n, "rmse": rmse, "mae": mae, "mean_obs": mean_obs, "nrmse": nrmse})
    return pd.DataFrame(rows)


def _weighted_mean(pairs_df: pd.DataFrame, col: str) -> float:
    if pairs_df.empty:
        return float("inf")
    w = pairs_df["mean_obs"].to_numpy(dtype=float)
    if np.all(w <= 0):
        w = np.ones_like(w, dtype=float)
    return float(np.average(pairs_df[col].to_numpy(dtype=float), weights=w))


def _compute_stock_guardrail(
    *,
    ts_df: pd.DataFrame,
    obs_stock: pd.DataFrame,
    train_years: List[int],
    validation_years: List[int],
    min_required_years: int,
) -> Dict[str, float]:
    stock = _extract_indicator(ts_df, "Stock_in_use")
    stock = stock.rename(columns={"model_value": "model"})

    obs = _normalize_key_cols(obs_stock)
    obs = obs[["year", "material", "region", "value"]].rename(columns={"value": "obs"})
    merged = stock.merge(obs, on=["year", "material", "region"], how="inner")

    tr_pairs = _window_pair_metrics(merged, train_years, min_required_years=min_required_years)
    va_pairs = _window_pair_metrics(merged, validation_years, min_required_years=min_required_years)

    return {
        "train_weighted_rmse": _weighted_mean(tr_pairs, "rmse"),
        "validation_weighted_rmse": _weighted_mean(va_pairs, "rmse"),
        "train_weighted_nrmse": _weighted_mean(tr_pairs, "nrmse"),
        "validation_weighted_nrmse": _weighted_mean(va_pairs, "nrmse"),
        "n_pairs_train": float(len(tr_pairs)),
        "n_pairs_validation": float(len(va_pairs)),
    }


def _evaluate_stage_candidate(
    *,
    run_config: Path,
    repo_root: Path,
    variant: str,
    stage_path: Path,
    obs_refined: pd.DataFrame,
    obs_benef: pd.DataFrame,
    obs_extract: pd.DataFrame,
    obs_stock: pd.DataFrame,
    fit_start: int,
    fit_end: int,
    train_years: List[int],
    validation_years: List[int],
    min_required_years: int,
    variable_weights: Dict[str, float],
) -> Dict[str, Any]:
    cfg = load_run_config(run_config)
    if cfg.variables is None or "stage_yields_losses" not in cfg.variables:
        raise ValueError("Run config missing variables.stage_yields_losses")
    cfg.variables["stage_yields_losses"].path = str(stage_path)

    warnings = validate_exogenous_inputs(cfg, repo_root=repo_root)
    if warnings:
        print(f"Validation warnings for candidate {stage_path.name}:")
        for w in warnings:
            print("-", w)

    ts_df, _, _, _, _ = run_one_variant(
        cfg=cfg,
        repo_root=repo_root,
        variant_name=variant,
        phase="calibration",
        timeseries_indicators=["Stock_in_use", "Primary_supply"],
        collect_scalar=False,
        collect_summary=False,
        collect_coupling_debug=False,
    )

    stage_df = _read_csv_required(stage_path, [
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
    ])

    upstream_metrics, upstream_score = _compute_upstream_metrics(
        ts_df=ts_df,
        stage_df=stage_df,
        obs_refined=obs_refined,
        obs_benef=obs_benef,
        obs_extract=obs_extract,
        fit_start=fit_start,
        fit_end=fit_end,
        variable_weights=variable_weights,
    )

    stock_metrics = _compute_stock_guardrail(
        ts_df=ts_df,
        obs_stock=obs_stock,
        train_years=train_years,
        validation_years=validation_years,
        min_required_years=min_required_years,
    )

    return {
        "ts_df": ts_df,
        "upstream_metrics": upstream_metrics,
        "upstream_score": float(upstream_score),
        "stock_metrics": stock_metrics,
    }


def _pairwise_degradation_penalty(
    *,
    baseline_metrics: pd.DataFrame,
    candidate_metrics: pd.DataFrame,
    tolerance: float,
    penalty_weight: float,
    variable_weights: Dict[str, float],
) -> Tuple[float, pd.DataFrame]:
    keys = ["observed_variable", "material", "region"]
    b = baseline_metrics[keys + ["nrmse"]].rename(columns={"nrmse": "nrmse_baseline"})
    c = candidate_metrics[keys + ["nrmse"]].rename(columns={"nrmse": "nrmse_candidate"})
    d = b.merge(c, on=keys, how="inner")
    if d.empty:
        return 0.0, d
    denom = np.maximum(np.abs(d["nrmse_baseline"].to_numpy(dtype=float)), 1e-12)
    frac = (d["nrmse_candidate"].to_numpy(dtype=float) - d["nrmse_baseline"].to_numpy(dtype=float)) / denom
    d["degradation_frac"] = frac
    d["excess_over_tolerance"] = np.maximum(frac - float(tolerance), 0.0)
    d["variable_weight"] = d["observed_variable"].map(lambda x: float(variable_weights.get(str(x), 1.0)))
    penalty = float(penalty_weight) * float(
        np.sum(d["variable_weight"].to_numpy(dtype=float) * d["excess_over_tolerance"].to_numpy(dtype=float))
    )
    return penalty, d


def _region_degradation_penalty(
    *,
    baseline_metrics: pd.DataFrame,
    candidate_metrics: pd.DataFrame,
    tolerance: float,
    penalty_weight: float,
    variable_weights: Dict[str, float],
) -> Tuple[float, pd.DataFrame, bool]:
    keys = ["observed_variable", "material", "region"]
    b = baseline_metrics[keys + ["nrmse"]].rename(columns={"nrmse": "nrmse_baseline"})
    c = candidate_metrics[keys + ["nrmse"]].rename(columns={"nrmse": "nrmse_candidate"})
    d = b.merge(c, on=keys, how="inner")
    if d.empty:
        cols = [
            "region",
            "n_pairs",
            "nrmse_baseline_region",
            "nrmse_candidate_region",
            "degradation_frac",
            "excess_over_tolerance",
        ]
        return 0.0, pd.DataFrame(columns=cols), True

    d["variable_weight"] = d["observed_variable"].map(lambda x: float(variable_weights.get(str(x), 1.0)))

    rows: List[Dict[str, Any]] = []
    for reg, grp in d.groupby("region", as_index=False):
        w = grp["variable_weight"].to_numpy(dtype=float)
        n_b = grp["nrmse_baseline"].to_numpy(dtype=float)
        n_c = grp["nrmse_candidate"].to_numpy(dtype=float)
        baseline_region = float(np.average(n_b, weights=w))
        candidate_region = float(np.average(n_c, weights=w))
        frac = (candidate_region - baseline_region) / max(abs(baseline_region), 1e-12)
        excess = max(0.0, float(frac) - float(tolerance))
        rows.append(
            {
                "region": str(reg),
                "n_pairs": int(len(grp)),
                "nrmse_baseline_region": baseline_region,
                "nrmse_candidate_region": candidate_region,
                "degradation_frac": float(frac),
                "excess_over_tolerance": float(excess),
            }
        )
    out = pd.DataFrame(rows).sort_values("region").reset_index(drop=True)
    penalty = float(penalty_weight) * float(out["excess_over_tolerance"].sum())
    feasible = bool((out["excess_over_tolerance"] <= 0).all())
    return penalty, out, feasible


def _slugify(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(text))


def _plot_raw_vs_smoothed(diag_df: pd.DataFrame, out_dir: Path) -> None:
    if diag_df.empty:
        return
    pairs = diag_df[["material", "region"]].drop_duplicates().sort_values(["material", "region"]).itertuples(index=False, name=None)
    pair_list = list(pairs)

    for yield_name in ["beneficiation_yield", "refining_yield"]:
        sub = diag_df[diag_df["yield_name"] == yield_name].copy()
        if sub.empty:
            continue
        n = len(pair_list)
        ncols = 3
        nrows = int(np.ceil(n / ncols))
        fig, axes = plt.subplots(nrows, ncols, figsize=(14, 3.2 * nrows), squeeze=False)

        for i, (mat, reg) in enumerate(pair_list):
            r, c = divmod(i, ncols)
            ax = axes[r][c]
            g = sub[(sub["material"] == mat) & (sub["region"] == reg)].sort_values("year")
            ax.plot(g["year"], g["base_value"], linestyle="--", linewidth=1.2, label="base")
            ax.plot(g["year"], g["smoothed_value"], linewidth=1.5, label="smoothed")
            raw = g.dropna(subset=["raw_value"])
            if not raw.empty:
                ax.scatter(raw["year"], raw["raw_value"], s=12, alpha=0.8, label="raw")
            ax.set_title(f"{mat} | {reg}")
            ax.grid(alpha=0.25)
            if r == nrows - 1:
                ax.set_xlabel("Year")

        for j in range(n, nrows * ncols):
            r, c = divmod(j, ncols)
            axes[r][c].axis("off")

        handles, labels = axes[0][0].get_legend_handles_labels()
        fig.legend(handles, labels, ncol=3, loc="upper center", frameon=False)
        fig.suptitle(f"Raw vs Smoothed ({yield_name})", y=0.995)
        fig.tight_layout()
        fig.savefig(out_dir / f"raw_vs_smoothed_{yield_name}.png", dpi=180)
        plt.close(fig)


def _plot_upstream_delta(comp_df: pd.DataFrame, out_dir: Path) -> None:
    if comp_df.empty:
        return
    d = comp_df.copy()
    d["label"] = d["observed_variable"] + "|" + d["material"] + "|" + d["region"]
    d = d.sort_values("delta_nrmse")

    fig, ax = plt.subplots(figsize=(14, max(4, 0.35 * len(d))))
    ax.barh(d["label"], d["delta_nrmse"], color=np.where(d["delta_nrmse"] <= 0, "#2ca25f", "#de2d26"))
    ax.axvline(0.0, color="black", linewidth=0.9)
    ax.set_title("Upstream Fit Delta (selected - baseline) in NRMSE")
    ax.set_xlabel("Delta NRMSE")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_dir / "upstream_fit_delta_nrmse.png", dpi=180)
    plt.close(fig)


def _plot_stock_guardrail(stock_cmp: pd.DataFrame, tolerance: float, out_dir: Path) -> None:
    if stock_cmp.empty:
        return
    d = stock_cmp.copy()
    d = d[d["metric"].isin(["train_weighted_rmse", "validation_weighted_rmse"])].copy()
    if d.empty:
        return
    d["pct_change"] = 100.0 * d["pct_change"]

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(d["metric"], d["pct_change"], color="#3182bd")
    ax.axhline(100.0 * tolerance, color="#de2d26", linestyle="--", linewidth=1.2, label="tolerance")
    ax.set_title("Stock Guardrail Delta (selected vs baseline)")
    ax.set_ylabel("Percent change [%]")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out_dir / "stock_guardrail_delta.png", dpi=180)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description="Fit stage_yields_losses dataset against upstream observed data.")
    ap.add_argument("--base-stage-file", default="data/exogenous/stage_yields_losses.csv")
    ap.add_argument("--observed-refined", default="data/exogenous/primary_refined_observed.csv")
    ap.add_argument("--observed-beneficiation", default="data/exogenous/beneficiation_output_observed.csv")
    ap.add_argument("--observed-extraction", default="data/exogenous/primary_extraction_observed.csv")
    ap.add_argument("--output-stage-file", default="data/exogenous/stage_yields_losses_v3.csv")
    ap.add_argument("--fit-start-year", type=int, default=1971)
    ap.add_argument("--fit-end-year", type=int, default=2023)
    ap.add_argument("--run-config", default="configs/runs/mvp.yml")
    ap.add_argument("--variant", default="baseline")
    ap.add_argument("--calibration-spec", default="configs/calibration.yml")
    ap.add_argument("--guardrail-stock-tolerance", type=float, default=0.05)
    ap.add_argument("--smooth-lambdas", default="0.2,0.5,1.0,2.0,5.0")
    ap.add_argument("--outdir", default="data/exogenous/diagnostics/stage_yield_fit_v3")
    ap.add_argument("--penalty-weight", type=float, default=25.0)
    ap.add_argument(
        "--variable-weights",
        default="primary_refined_observed:1.0,beneficiation_output_observed:1.0,primary_extraction_observed:1.0",
        help="Comma-separated key:value weights for upstream variables.",
    )
    ap.add_argument("--pairwise-degradation-tolerance", type=float, default=0.10)
    ap.add_argument("--pairwise-degradation-penalty-weight", type=float, default=8.0)
    ap.add_argument("--pair-specific-smoothing", action="store_true")
    ap.add_argument("--region-targeted", action="store_true")
    ap.add_argument("--region-degradation-tolerance", type=float, default=0.05)
    ap.add_argument("--region-degradation-penalty-weight", type=float, default=20.0)
    ap.add_argument("--region-hard-constraint", action="store_true")
    args = ap.parse_args()

    variable_weights = _parse_variable_weights(args.variable_weights)

    run_config = Path(args.run_config).resolve()
    repo_root = resolve_repo_root_from_config(run_config)

    base_stage_path = (repo_root / args.base_stage_file).resolve()
    out_stage_path = (repo_root / args.output_stage_file).resolve()
    obs_refined_path = (repo_root / args.observed_refined).resolve()
    obs_benef_path = (repo_root / args.observed_beneficiation).resolve()
    obs_extract_path = (repo_root / args.observed_extraction).resolve()
    cal_spec_path = (repo_root / args.calibration_spec).resolve()
    out_dir = (repo_root / args.outdir).resolve()
    cand_dir = out_dir / "candidates"
    plots_dir = out_dir / "plots"
    out_dir.mkdir(parents=True, exist_ok=True)
    cand_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    base_stage = _read_csv_required(
        base_stage_path,
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
    )

    obs_refined = _load_observed(obs_refined_path, start_year=args.fit_start_year, end_year=args.fit_end_year)
    obs_benef = _load_observed(obs_benef_path, start_year=args.fit_start_year, end_year=args.fit_end_year)
    obs_extract = _load_observed(obs_extract_path, start_year=args.fit_start_year, end_year=args.fit_end_year)

    cfg_for_stock = load_run_config(run_config)
    if cfg_for_stock.variables is None or "stock_in_use" not in cfg_for_stock.variables:
        raise ValueError("Run config variables.stock_in_use is required for stock guardrail.")
    obs_stock_path = (repo_root / cfg_for_stock.variables["stock_in_use"].path).resolve()
    obs_stock = _read_csv_required(obs_stock_path, ["year", "material", "region", "end_use", "value"])

    cal_spec = yaml.safe_load(cal_spec_path.read_text(encoding="utf-8")) or {}
    windows = cal_spec.get("windows", {})
    train = windows.get("train", {})
    valid = windows.get("validation", {})
    train_years = list(range(int(train.get("start_year", args.fit_start_year)), int(train.get("end_year", args.fit_end_year)) + 1))
    validation_years = list(range(int(valid.get("start_year", args.fit_start_year)), int(valid.get("end_year", args.fit_end_year)) + 1))
    min_required_years = int((cal_spec.get("objective", {}).get("missing_data", {}) or {}).get("min_required_years_per_material_region", 1))

    raw_targets = _build_raw_targets(
        obs_refined=obs_refined,
        obs_benef=obs_benef,
        obs_extract=obs_extract,
    )

    print("Running baseline freeze evaluation...")
    baseline_eval = _evaluate_stage_candidate(
        run_config=run_config,
        repo_root=repo_root,
        variant=args.variant,
        stage_path=base_stage_path,
        obs_refined=obs_refined,
        obs_benef=obs_benef,
        obs_extract=obs_extract,
        obs_stock=obs_stock,
        fit_start=args.fit_start_year,
        fit_end=args.fit_end_year,
        train_years=train_years,
        validation_years=validation_years,
        min_required_years=min_required_years,
        variable_weights=variable_weights,
    )

    baseline_metrics = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "run_config": str(run_config),
        "variant": args.variant,
        "base_stage_file": str(base_stage_path),
        "fit_window": f"{args.fit_start_year}-{args.fit_end_year}",
        "upstream_balanced_nrmse": float(baseline_eval["upstream_score"]),
        "stock_guardrail": baseline_eval["stock_metrics"],
    }
    (out_dir / "baseline_metrics.yml").write_text(yaml.safe_dump(baseline_metrics, sort_keys=False), encoding="utf-8")

    lambdas = [float(x.strip()) for x in str(args.smooth_lambdas).split(",") if x.strip()]
    if not lambdas:
        raise ValueError("No smoothing lambdas provided.")

    candidate_rows: List[Dict[str, Any]] = []
    candidate_details: Dict[str, Dict[str, Any]] = {}

    if args.region_targeted:
        regions = sorted(base_stage["region"].astype(str).unique().tolist())
        candidate_specs: List[Dict[str, Any]] = []
        for combo in product(lambdas, repeat=len(regions)):
            lambda_map = {str(r): float(v) for r, v in zip(regions, combo)}
            label = "__".join(f"{r}-{lambda_map[r]:.6g}" for r in regions)
            candidate_specs.append({"label": label, "lambda": np.nan, "lambda_map": lambda_map})
        print(
            f"Region-targeted search enabled across {len(regions)} regions and {len(candidate_specs)} candidates."
        )
    else:
        candidate_specs = [
            {"label": f"lambda_{lam:.6g}", "lambda": float(lam), "lambda_map": None}
            for lam in lambdas
        ]

    for spec in candidate_specs:
        label = str(spec["label"])
        lam = spec["lambda"]
        lambda_map = spec["lambda_map"]
        print(f"Evaluating candidate {label}...")
        cand_stage_df, diag_df = _build_candidate_stage(
            base_stage=base_stage,
            raw_targets=raw_targets,
            fit_start=args.fit_start_year,
            fit_end=args.fit_end_year,
            smooth_lambda=float(lambdas[0]),
            smooth_lambda_by_region=lambda_map,
            pair_specific_smoothing=bool(args.pair_specific_smoothing),
        )

        slug = _slugify(label)
        cand_path = cand_dir / f"stage_yields_losses_candidate_{slug}.csv"
        cand_stage_df.to_csv(cand_path, index=False)
        diag_df.to_csv(cand_dir / f"raw_vs_smoothed_{slug}.csv", index=False)

        ev = _evaluate_stage_candidate(
            run_config=run_config,
            repo_root=repo_root,
            variant=args.variant,
            stage_path=cand_path,
            obs_refined=obs_refined,
            obs_benef=obs_benef,
            obs_extract=obs_extract,
            obs_stock=obs_stock,
            fit_start=args.fit_start_year,
            fit_end=args.fit_end_year,
            train_years=train_years,
            validation_years=validation_years,
            min_required_years=min_required_years,
            variable_weights=variable_weights,
        )

        b_stock = baseline_eval["stock_metrics"]
        c_stock = ev["stock_metrics"]

        train_deg = (
            (c_stock["train_weighted_rmse"] - b_stock["train_weighted_rmse"]) / max(b_stock["train_weighted_rmse"], 1e-12)
            if np.isfinite(b_stock["train_weighted_rmse"]) and np.isfinite(c_stock["train_weighted_rmse"]) else 0.0
        )
        val_deg = (
            (c_stock["validation_weighted_rmse"] - b_stock["validation_weighted_rmse"]) / max(b_stock["validation_weighted_rmse"], 1e-12)
            if np.isfinite(b_stock["validation_weighted_rmse"]) and np.isfinite(c_stock["validation_weighted_rmse"]) else 0.0
        )

        train_excess = max(0.0, float(train_deg) - float(args.guardrail_stock_tolerance))
        val_excess = max(0.0, float(val_deg) - float(args.guardrail_stock_tolerance))
        stock_penalty = float(args.penalty_weight) * (train_excess + val_excess)
        pairwise_penalty, pairwise_df = _pairwise_degradation_penalty(
            baseline_metrics=baseline_eval["upstream_metrics"],
            candidate_metrics=ev["upstream_metrics"],
            tolerance=float(args.pairwise_degradation_tolerance),
            penalty_weight=float(args.pairwise_degradation_penalty_weight),
            variable_weights=variable_weights,
        )
        region_penalty, region_df, region_feasible = _region_degradation_penalty(
            baseline_metrics=baseline_eval["upstream_metrics"],
            candidate_metrics=ev["upstream_metrics"],
            tolerance=float(args.region_degradation_tolerance),
            penalty_weight=float(args.region_degradation_penalty_weight),
            variable_weights=variable_weights,
        )
        hard_penalty = (
            1_000_000.0 if bool(args.region_hard_constraint) and not bool(region_feasible) else 0.0
        )
        total = float(ev["upstream_score"]) + stock_penalty + pairwise_penalty + region_penalty + hard_penalty

        row = {
            "candidate_id": label,
            "lambda": float(lam),
            "lambda_by_region": (
                yaml.safe_dump(lambda_map, sort_keys=True, default_flow_style=True).strip()
                if isinstance(lambda_map, dict)
                else ""
            ),
            "upstream_balanced_nrmse": float(ev["upstream_score"]),
            "stock_train_weighted_rmse": float(c_stock["train_weighted_rmse"]),
            "stock_validation_weighted_rmse": float(c_stock["validation_weighted_rmse"]),
            "stock_train_degradation_frac": float(train_deg),
            "stock_validation_degradation_frac": float(val_deg),
            "stock_penalty": float(stock_penalty),
            "pairwise_penalty": float(pairwise_penalty),
            "region_penalty": float(region_penalty),
            "region_hard_penalty": float(hard_penalty),
            "region_constraint_feasible": bool(region_feasible),
            "penalty": float(stock_penalty + pairwise_penalty + region_penalty + hard_penalty),
            "total_score": float(total),
            "candidate_stage_file": str(cand_path),
        }
        candidate_rows.append(row)
        candidate_details[label] = {
            "row": row,
            "diag": diag_df,
            "upstream_metrics": ev["upstream_metrics"],
            "stock_metrics": c_stock,
            "stage_df": cand_stage_df,
            "pairwise_degradation": pairwise_df,
            "region_degradation": region_df,
        }
        pairwise_df.to_csv(cand_dir / f"pairwise_degradation_{slug}.csv", index=False)
        region_df.to_csv(cand_dir / f"region_degradation_{slug}.csv", index=False)

    cand_scores = pd.DataFrame(candidate_rows).sort_values("total_score").reset_index(drop=True)
    cand_scores.to_csv(out_dir / "candidate_scores.csv", index=False)

    best_row = cand_scores.iloc[0].to_dict()
    best_id = str(best_row["candidate_id"])
    best = candidate_details[best_id]
    best_lambda = float(best_row["lambda"]) if pd.notna(best_row.get("lambda", np.nan)) else np.nan

    # Final assembly output file.
    out_stage_path.parent.mkdir(parents=True, exist_ok=True)
    best["stage_df"].to_csv(out_stage_path, index=False)

    baseline_up = baseline_eval["upstream_metrics"].rename(
        columns={"rmse": "rmse_baseline", "mae": "mae_baseline", "nrmse": "nrmse_baseline", "n_years": "n_years_baseline"}
    )
    selected_up = best["upstream_metrics"].rename(
        columns={"rmse": "rmse_selected", "mae": "mae_selected", "nrmse": "nrmse_selected", "n_years": "n_years_selected"}
    )
    comp = baseline_up.merge(
        selected_up,
        on=["observed_variable", "material", "region"],
        how="outer",
    )
    comp["delta_nrmse"] = comp["nrmse_selected"] - comp["nrmse_baseline"]
    comp["delta_rmse"] = comp["rmse_selected"] - comp["rmse_baseline"]
    comp.to_csv(out_dir / "upstream_fit_comparison.csv", index=False)
    best["pairwise_degradation"].to_csv(out_dir / "pairwise_degradation_comparison.csv", index=False)
    best["region_degradation"].to_csv(out_dir / "region_degradation_comparison.csv", index=False)

    b_stock = baseline_eval["stock_metrics"]
    s_stock = best["stock_metrics"]
    stock_rows = []
    for k in ["train_weighted_rmse", "validation_weighted_rmse", "train_weighted_nrmse", "validation_weighted_nrmse"]:
        b = float(b_stock.get(k, np.nan))
        s = float(s_stock.get(k, np.nan))
        d = s - b
        p = d / max(abs(b), 1e-12) if np.isfinite(b) and np.isfinite(s) else np.nan
        stock_rows.append({"metric": k, "baseline": b, "selected": s, "delta": d, "pct_change": p})
    stock_cmp = pd.DataFrame(stock_rows)
    stock_cmp.to_csv(out_dir / "stock_guardrail_comparison.csv", index=False)

    _plot_raw_vs_smoothed(best["diag"], plots_dir)
    _plot_upstream_delta(comp, plots_dir)
    _plot_stock_guardrail(stock_cmp, tolerance=float(args.guardrail_stock_tolerance), out_dir=plots_dir)

    baseline_score = float(baseline_eval["upstream_score"])
    selected_score = float(best_row["upstream_balanced_nrmse"])
    improved = bool(selected_score < baseline_score)
    train_deg = float(best_row["stock_train_degradation_frac"])
    val_deg = float(best_row["stock_validation_degradation_frac"])
    guardrail_ok = bool(
        train_deg <= float(args.guardrail_stock_tolerance)
        and val_deg <= float(args.guardrail_stock_tolerance)
    )

    selected_meta = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "selected_candidate_id": best_id,
        "selected_lambda": (
            float(best_lambda) if np.isfinite(best_lambda) else None
        ),
        "selected_lambda_by_region": (
            yaml.safe_load(best_row.get("lambda_by_region", "")) if best_row.get("lambda_by_region", "") else {}
        ),
        "selected_candidate_stage_file": str(best_row["candidate_stage_file"]),
        "output_stage_file": str(out_stage_path),
        "baseline_upstream_balanced_nrmse": baseline_score,
        "selected_upstream_balanced_nrmse": selected_score,
        "upstream_improved": improved,
        "guardrail_tolerance": float(args.guardrail_stock_tolerance),
        "stock_train_degradation_frac": train_deg,
        "stock_validation_degradation_frac": val_deg,
        "pairwise_degradation_tolerance": float(args.pairwise_degradation_tolerance),
        "pairwise_penalty_weight": float(args.pairwise_degradation_penalty_weight),
        "region_targeted": bool(args.region_targeted),
        "region_degradation_tolerance": float(args.region_degradation_tolerance),
        "region_degradation_penalty_weight": float(args.region_degradation_penalty_weight),
        "region_hard_constraint": bool(args.region_hard_constraint),
        "pair_specific_smoothing": bool(args.pair_specific_smoothing),
        "variable_weights": variable_weights,
        "selected_pairwise_penalty": float(best_row.get("pairwise_penalty", 0.0)),
        "selected_stock_penalty": float(best_row.get("stock_penalty", 0.0)),
        "selected_region_penalty": float(best_row.get("region_penalty", 0.0)),
        "selected_region_hard_penalty": float(best_row.get("region_hard_penalty", 0.0)),
        "selected_region_constraint_feasible": bool(best_row.get("region_constraint_feasible", True)),
        "guardrail_ok": guardrail_ok,
        "accepted": bool(improved and guardrail_ok),
    }
    (out_dir / "selected_candidate.yml").write_text(yaml.safe_dump(selected_meta, sort_keys=False), encoding="utf-8")

    print(f"Wrote candidate scores: {out_dir / 'candidate_scores.csv'}")
    print(f"Wrote selected file: {out_stage_path}")
    print(f"Baseline upstream balanced NRMSE: {baseline_score:.6g}")
    print(f"Selected upstream balanced NRMSE: {selected_score:.6g}")
    print(f"Train degradation frac: {train_deg:.6g}, validation degradation frac: {val_deg:.6g}")

    if not selected_meta["accepted"]:
        print("Acceptance gates not met (requires upstream improvement and stock degradation <= tolerance).")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
