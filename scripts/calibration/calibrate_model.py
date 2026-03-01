#!/usr/bin/env python
"""Calibrate SD-dMFA parameters against observed stock-in-use.

Usage:
  python scripts/calibration/calibrate_model.py --config configs/runs/mvp.yml --calibration-spec configs/calibration.yml
"""

from __future__ import annotations

import argparse
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import yaml
from scipy.optimize import differential_evolution, minimize

from crm_model.cli import run_one_variant
from crm_model.common.config_models import ScenarioDimensionOverride
from crm_model.common.io import load_run_config, resolve_repo_root_from_config
from crm_model.common.run_layout import archive_old_timestamped_runs, config_runs_root
from crm_model.common.validation import validate_exogenous_inputs


def _read_yaml(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML file must contain a top-level mapping: {path}")
    return data


def _write_yaml(path: Path, data: Any) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _set_by_path(root: Any, dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    target = root
    for part in parts[:-1]:
        if isinstance(target, dict):
            if part not in target:
                target[part] = {}
            target = target[part]
        else:
            target = getattr(target, part)

    leaf = parts[-1]
    if isinstance(target, dict):
        target[leaf] = value
    else:
        setattr(target, leaf, value)


def _get_by_path(root: Any, dotted_path: str) -> Any:
    parts = dotted_path.split(".")
    target = root
    for part in parts:
        if isinstance(target, dict):
            if part not in target:
                raise KeyError(f"Path not found in mapping: {dotted_path}")
            target = target[part]
        else:
            target = getattr(target, part)
    return target


def _range_years(start_year: int, end_year: int) -> List[int]:
    if end_year < start_year:
        raise ValueError(f"Invalid year window: {start_year}..{end_year}")
    return list(range(start_year, end_year + 1))


def _aggregate_observed_stock(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {"year", "material", "region", "end_use", "value"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Observed stock file is missing required columns: {missing}")

    out = (
        df.groupby(["material", "region", "year"], as_index=False)["value"]
        .sum()
        .rename(columns={"value": "obs"})
    )
    return out


def _window_pair_metrics(
    merged: pd.DataFrame,
    years: Iterable[int],
    *,
    min_required_years: int,
) -> pd.DataFrame:
    yset = set(int(y) for y in years)
    sub = merged[merged["year"].isin(yset)].copy()
    if sub.empty:
        return pd.DataFrame(
            columns=[
                "material",
                "region",
                "n_years",
                "rmse",
                "mae",
                "mean_obs",
                "nrmse_mean",
            ]
        )

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

        rows.append(
            {
                "material": str(mat),
                "region": str(reg),
                "n_years": n,
                "rmse": rmse,
                "mae": mae,
                "mean_obs": mean_obs,
                "nrmse_mean": nrmse,
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "material",
                "region",
                "n_years",
                "rmse",
                "mae",
                "mean_obs",
                "nrmse_mean",
            ]
        )
    return pd.DataFrame(rows)


def _weighted_mean_rmse(pairs_df: pd.DataFrame, *, weight_basis: str) -> float:
    if pairs_df.empty:
        return float("inf")

    if weight_basis == "mean_observed_stock":
        weights = pairs_df["mean_obs"].to_numpy(dtype=float)
        if np.all(weights <= 0):
            weights = np.ones_like(weights, dtype=float)
        return float(np.average(pairs_df["rmse"].to_numpy(dtype=float), weights=weights))

    # fallback: unweighted mean
    return float(pairs_df["rmse"].mean())


def _weighted_mean_nrmse(pairs_df: pd.DataFrame, *, weight_basis: str) -> float:
    if pairs_df.empty:
        return float("inf")

    if weight_basis == "mean_observed_stock":
        weights = pairs_df["mean_obs"].to_numpy(dtype=float)
        if np.all(weights <= 0):
            weights = np.ones_like(weights, dtype=float)
        return float(np.average(pairs_df["nrmse_mean"].to_numpy(dtype=float), weights=weights))

    return float(pairs_df["nrmse_mean"].mean())


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "none", "null", "nan"}:
        return None
    return float(value)


class CalibrationProblem:
    def __init__(
        self,
        *,
        cfg_path: Path,
        variant_name: str,
        calibration_spec: Dict[str, Any],
    ):
        self.cfg_path = cfg_path.resolve()
        self.repo_root = resolve_repo_root_from_config(self.cfg_path)
        self.variant_name = variant_name
        self.spec = calibration_spec

        # Avoid matplotlib cache warnings in restricted environments.
        mpl_dir = self.repo_root / ".cache" / "matplotlib"
        mpl_dir.mkdir(parents=True, exist_ok=True)
        import os

        os.environ.setdefault("MPLCONFIGDIR", str(mpl_dir))

        self.base_cfg = load_run_config(self.cfg_path)
        if self.variant_name not in self.base_cfg.variants:
            raise ValueError(
                f"Unknown variant '{self.variant_name}'. Available: {list(self.base_cfg.variants.keys())}"
            )
        variant_cfg = self.base_cfg.variants[self.variant_name]
        strategic_enabled = bool(getattr(self.base_cfg.strategy, "strategic_reserve_enabled", False))
        if variant_cfg.strategy is not None:
            strategic_enabled = strategic_enabled or bool(
                getattr(variant_cfg.strategy, "strategic_reserve_enabled", False)
            )
        for ov in variant_cfg.dimension_overrides:
            if ov.strategy is not None and bool(getattr(ov.strategy, "strategic_reserve_enabled", False)):
                strategic_enabled = True
                break
        if strategic_enabled:
            print(
                "Warning: strategic reserve mechanism is enabled during calibration. "
                "Disable strategic_reserve_enabled for baseline fit runs to avoid confounded calibration."
            )

        warnings = validate_exogenous_inputs(self.base_cfg, repo_root=self.repo_root)
        if warnings:
            print("Validation warnings:")
            for w in warnings:
                print("-", w)

        objective = self.spec.get("objective") or {}
        windows = self.spec.get("windows") or {}
        selection = self.spec.get("selection") or {}
        selection_constraints = selection.get("constraints") or {}
        params_root = self.spec.get("parameters") or {}
        params_block = (params_root.get("mfa")) or {}
        slice_block = (params_root.get("slice_adjustments")) or {}
        outputs = self.spec.get("outputs") or {}

        self.weight_basis = str((objective.get("aggregation") or {}).get("weight_basis", "mean_observed_stock"))
        self.min_required_years = int((objective.get("missing_data") or {}).get("min_required_years_per_material_region", 1))
        self.search_metric = str(selection.get("search_metric", "train_weighted_rmse"))
        self.primary_metric = str(selection.get("primary_metric", "validation_weighted_rmse"))
        self.fallback_metric = str(selection.get("fallback_metric", "train_weighted_rmse"))
        self.min_pairs_train = int(selection_constraints.get("min_pairs_train", 1))
        self.min_pairs_validation = int(selection_constraints.get("min_pairs_validation", 1))
        self.max_validation_weighted_rmse = _optional_float(
            selection_constraints.get("max_validation_weighted_rmse")
        )
        self.max_validation_weighted_nrmse = _optional_float(
            selection_constraints.get("max_validation_weighted_nrmse")
        )
        self.max_train_weighted_rmse = _optional_float(
            selection_constraints.get("max_train_weighted_rmse")
        )
        self.max_train_weighted_nrmse = _optional_float(
            selection_constraints.get("max_train_weighted_nrmse")
        )
        self.train_years = _range_years(
            int((windows.get("train") or {}).get("start_year")),
            int((windows.get("train") or {}).get("end_year")),
        )
        self.validation_years = _range_years(
            int((windows.get("validation") or {}).get("start_year")),
            int((windows.get("validation") or {}).get("end_year")),
        )

        target_source = objective.get("target_source")
        if not target_source:
            raise ValueError("calibration objective.target_source is required")
        target_path = (self.repo_root / str(target_source)).resolve()
        if not target_path.exists():
            raise FileNotFoundError(f"Observed stock file not found: {target_path}")
        self.obs = _aggregate_observed_stock(target_path)

        if not isinstance(params_block, dict) or not params_block:
            raise ValueError("calibration parameters.mfa must define at least one parameter")

        self.param_names: List[str] = []
        self.initial: List[float] = []
        self.bounds: List[Tuple[float, float]] = []
        self.param_specs: List[Dict[str, Any]] = []
        for name, meta in params_block.items():
            if not isinstance(meta, dict):
                raise ValueError(f"Parameter spec for '{name}' must be a mapping")
            path = str(meta.get("path"))
            bounds = meta.get("bounds")
            initial = float(meta.get("initial"))
            if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
                raise ValueError(f"Parameter '{name}' bounds must be [low, high]")
            low = float(bounds[0])
            high = float(bounds[1])
            if not low < high:
                raise ValueError(f"Parameter '{name}' bounds are invalid: [{low}, {high}]")
            if not (low <= initial <= high):
                raise ValueError(f"Parameter '{name}' initial value {initial} is outside bounds [{low}, {high}]")
            self.param_names.append(str(name))
            self.initial.append(initial)
            self.bounds.append((low, high))
            self.param_specs.append(
                {
                    "name": str(name),
                    "kind": "global",
                    "path": path,
                }
            )

        if slice_block:
            if not isinstance(slice_block, dict):
                raise ValueError("calibration parameters.slice_adjustments must be a mapping")
            for name, meta in slice_block.items():
                if not isinstance(meta, dict):
                    raise ValueError(f"Slice-adjustment spec for '{name}' must be a mapping")
                path = str(meta.get("path"))
                if "." not in path:
                    raise ValueError(
                        f"Slice-adjustment '{name}' path must include a section prefix; got '{path}'."
                    )
                section, _, subpath = path.partition(".")
                if section not in {"mfa_parameters", "strategy", "sd_parameters"}:
                    raise ValueError(
                        f"Slice-adjustment '{name}' path prefix must be one of "
                        f"mfa_parameters/strategy/sd_parameters; got '{section}'."
                    )
                if not subpath:
                    raise ValueError(f"Slice-adjustment '{name}' path is missing leaf after section prefix.")
                material = str(meta.get("material"))
                region = str(meta.get("region"))
                bounds = meta.get("bounds")
                initial = float(meta.get("initial"))
                if not material or material.lower() in {"none", "null"}:
                    raise ValueError(f"Slice-adjustment '{name}' requires a non-empty material.")
                if not region or region.lower() in {"none", "null"}:
                    raise ValueError(f"Slice-adjustment '{name}' requires a non-empty region.")
                if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
                    raise ValueError(f"Slice-adjustment '{name}' bounds must be [low, high]")
                low = float(bounds[0])
                high = float(bounds[1])
                if not low < high:
                    raise ValueError(f"Slice-adjustment '{name}' bounds are invalid: [{low}, {high}]")
                if not (low <= initial <= high):
                    raise ValueError(
                        f"Slice-adjustment '{name}' initial value {initial} is outside bounds [{low}, {high}]"
                    )
                apply_mode = str(meta.get("apply", "multiplier")).strip().lower()
                if apply_mode not in {"multiplier", "add", "set"}:
                    raise ValueError(
                        f"Slice-adjustment '{name}' apply must be one of multiplier/add/set; got '{apply_mode}'."
                    )
                self.param_names.append(str(name))
                self.initial.append(initial)
                self.bounds.append((low, high))
                self.param_specs.append(
                    {
                        "name": str(name),
                        "kind": "slice_adjustment",
                        "path": path,
                        "section": section,
                        "subpath": subpath,
                        "material": material,
                        "region": region,
                        "apply": apply_mode,
                    }
                )

        self.cache: Dict[Tuple[float, ...], Dict[str, Any]] = {}
        self.results: List[Dict[str, Any]] = []
        self.trials: List[Dict[str, Any]] = []
        self.search_best_result: Dict[str, Any] | None = None
        self.selected_result: Dict[str, Any] | None = None
        self.selection_reason: str = ""
        self.eval_counter = 0
        self.run_dir: Path | None = None
        self.last_autosave_eval: int = -1
        self.autosave_every_evaluations = max(
            1, int(outputs.get("autosave_every_evaluations", 1))
        )
        self.save_trial_history_csv = bool(outputs.get("save_trial_history_csv", True))
        self.save_best_config_patch_yml = bool(outputs.get("save_best_config_patch_yml", True))
        self.save_validation_summary_csv = bool(outputs.get("save_validation_summary_csv", True))
        self.stop_requested = False
        self.stop_reason: str | None = None
        self._deadline_monotonic: float | None = None

    def _vector_to_params(self, vector: np.ndarray) -> Dict[str, float]:
        return {name: float(vector[i]) for i, name in enumerate(self.param_names)}

    def set_run_dir(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.last_autosave_eval = -1

    def set_deadline_minutes(self, max_runtime_minutes: float | None) -> None:
        if max_runtime_minutes is None:
            self._deadline_monotonic = None
            return
        if max_runtime_minutes <= 0:
            raise ValueError("--max-runtime-minutes must be > 0")
        self._deadline_monotonic = time.monotonic() + (60.0 * float(max_runtime_minutes))

    def request_stop(self, reason: str) -> None:
        self.stop_requested = True
        if not self.stop_reason:
            self.stop_reason = reason

    def _persist_partial_outputs(self, *, force: bool = False) -> None:
        if self.run_dir is None:
            return
        if not self.trials:
            return
        if (not force) and (self.eval_counter - self.last_autosave_eval < self.autosave_every_evaluations):
            return

        if self.save_trial_history_csv:
            pd.DataFrame(self.trials).to_csv(self.run_dir / "trial_history.partial.csv", index=False)
        if self.save_best_config_patch_yml:
            _write_yaml(
                self.run_dir / "search_best_config_patch.partial.yml",
                _build_patch(self, self.search_best_result),
            )

        checkpoint = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "evaluations_completed": int(len(self.trials)),
            "search_metric": self.search_metric,
            "search_best_trial_id": (
                int(self.search_best_result["trial_id"]) if self.search_best_result else None
            ),
            "search_best_score": (
                float(self.search_best_result["search_score"]) if self.search_best_result else None
            ),
            "stop_requested": bool(self.stop_requested),
            "stop_reason": self.stop_reason,
        }
        _write_yaml(self.run_dir / "checkpoint.yml", checkpoint)
        self.last_autosave_eval = int(self.eval_counter)

    def _vector_to_cfg(self, vector: np.ndarray):
        cfg_trial = self.base_cfg.model_copy(deep=True)
        params = self._vector_to_params(vector)
        for spec in self.param_specs:
            if spec["kind"] != "global":
                continue
            _set_by_path(cfg_trial, str(spec["path"]), float(params[spec["name"]]))
        self._apply_slice_adjustments(cfg_trial, params)
        return cfg_trial

    def _apply_slice_adjustments(self, cfg_trial: Any, params: Dict[str, float]) -> None:
        specs = [s for s in self.param_specs if s["kind"] == "slice_adjustment"]
        if not specs:
            return

        grouped: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = {}
        for spec in specs:
            name = str(spec["name"])
            section = str(spec["section"])
            subpath = str(spec["subpath"])
            material = str(spec["material"])
            region = str(spec["region"])
            apply_mode = str(spec["apply"])
            param_val = float(params[name])

            base_val = float(_get_by_path(cfg_trial, str(spec["path"])))
            if apply_mode == "multiplier":
                calibrated_val = base_val * param_val
            elif apply_mode == "add":
                calibrated_val = base_val + param_val
            else:
                calibrated_val = param_val

            if np.isclose(calibrated_val, base_val, rtol=1e-12, atol=1e-12):
                continue

            key = (material, region)
            if key not in grouped:
                grouped[key] = {"mfa_parameters": {}, "strategy": {}, "sd_parameters": {}}
            _set_by_path(grouped[key][section], subpath, float(calibrated_val))

        variant_cfg = cfg_trial.variants[self.variant_name]
        kept = [ov for ov in variant_cfg.dimension_overrides if not str(ov.name or "").startswith("calibration__")]
        variant_cfg.dimension_overrides = kept

        for (material, region), payload in grouped.items():
            kwargs: Dict[str, Any] = {
                "name": f"calibration__{material}_{region}",
                "materials": [material],
                "regions": [region],
            }
            if payload["mfa_parameters"]:
                kwargs["mfa_parameters"] = payload["mfa_parameters"]
            if payload["strategy"]:
                kwargs["strategy"] = payload["strategy"]
            if payload["sd_parameters"]:
                kwargs["sd_parameters"] = payload["sd_parameters"]
            variant_cfg.dimension_overrides.append(ScenarioDimensionOverride(**kwargs))

    def _metric_value(self, result: Dict[str, Any], metric_name: str) -> float:
        metric_key_map = {
            "train_weighted_rmse": "train_weighted_rmse",
            "validation_weighted_rmse": "validation_weighted_rmse",
            "train_weighted_nrmse": "train_weighted_nrmse",
            "validation_weighted_nrmse": "validation_weighted_nrmse",
        }
        key = metric_key_map.get(metric_name)
        if key is None:
            raise ValueError(
                f"Unknown metric '{metric_name}'. Allowed: {sorted(metric_key_map.keys())}"
            )
        value = float(result.get(key, np.nan))
        if not np.isfinite(value):
            return float("inf")
        return value

    def _passes_selection_constraints(self, result: Dict[str, Any]) -> bool:
        if int(result.get("n_pairs_train", 0)) < self.min_pairs_train:
            return False
        if int(result.get("n_pairs_validation", 0)) < self.min_pairs_validation:
            return False

        if (
            self.max_validation_weighted_rmse is not None
            and self._metric_value(result, "validation_weighted_rmse")
            > self.max_validation_weighted_rmse
        ):
            return False
        if (
            self.max_validation_weighted_nrmse is not None
            and self._metric_value(result, "validation_weighted_nrmse")
            > self.max_validation_weighted_nrmse
        ):
            return False
        if (
            self.max_train_weighted_rmse is not None
            and self._metric_value(result, "train_weighted_rmse") > self.max_train_weighted_rmse
        ):
            return False
        if (
            self.max_train_weighted_nrmse is not None
            and self._metric_value(result, "train_weighted_nrmse") > self.max_train_weighted_nrmse
        ):
            return False
        return True

    def _run_and_score(self, vector: np.ndarray, *, stage: str) -> Dict[str, Any]:
        if self.stop_requested:
            raise KeyboardInterrupt

        key = tuple(float(f"{x:.12g}") for x in vector.tolist())
        if key in self.cache:
            return self.cache[key]

        cfg_trial = self._vector_to_cfg(vector)

        # Make sure calibration run covers both train and validation windows.
        eval_start = min(int(self.base_cfg.time.start_year), self.train_years[0], self.validation_years[0])  # type: ignore[union-attr]
        eval_end = max(self.train_years[-1], self.validation_years[-1])
        cfg_trial.time.start_year = int(eval_start)  # type: ignore[union-attr]
        cfg_trial.time.calibration_end_year = int(eval_end)  # type: ignore[union-attr]

        ts_df, _, _, _, _ = run_one_variant(
            cfg=cfg_trial,
            repo_root=self.repo_root,
            variant_name=self.variant_name,
            phase="calibration",
            timeseries_indicators=["Stock_in_use"],
            collect_scalar=False,
            collect_summary=False,
            collect_coupling_debug=False,
        )

        mod = ts_df[ts_df["indicator"] == "Stock_in_use"].copy()
        if mod.empty:
            raise ValueError("Stock_in_use not found in calibration timeseries. Check indicators config.")
        mod = mod[["material", "region", "year", "value"]].rename(columns={"value": "model"})

        merged = mod.merge(self.obs, on=["material", "region", "year"], how="inner")
        if merged.empty:
            raise ValueError("No overlap between modeled and observed stock_in_use series.")

        train_pairs = _window_pair_metrics(
            merged, self.train_years, min_required_years=self.min_required_years
        )
        valid_pairs = _window_pair_metrics(
            merged, self.validation_years, min_required_years=self.min_required_years
        )

        train_wrmse = _weighted_mean_rmse(train_pairs, weight_basis=self.weight_basis)
        valid_wrmse = _weighted_mean_rmse(valid_pairs, weight_basis=self.weight_basis)
        train_wnrmse = _weighted_mean_nrmse(train_pairs, weight_basis=self.weight_basis)
        valid_wnrmse = _weighted_mean_nrmse(valid_pairs, weight_basis=self.weight_basis)

        params = self._vector_to_params(vector)
        result = {
            "train_weighted_rmse": float(train_wrmse) if np.isfinite(train_wrmse) else np.nan,
            "validation_weighted_rmse": float(valid_wrmse) if np.isfinite(valid_wrmse) else np.nan,
            "train_weighted_nrmse": float(train_wnrmse) if np.isfinite(train_wnrmse) else np.nan,
            "validation_weighted_nrmse": float(valid_wnrmse) if np.isfinite(valid_wnrmse) else np.nan,
            "n_pairs_train": int(len(train_pairs)),
            "n_pairs_validation": int(len(valid_pairs)),
            "params": params,
            "stage": stage,
            "pair_summary": pd.merge(
                train_pairs.rename(
                    columns={
                        "n_years": "n_years_train",
                        "rmse": "rmse_train",
                        "mae": "mae_train",
                        "mean_obs": "mean_obs_train",
                        "nrmse_mean": "nrmse_train_mean",
                    }
                ),
                valid_pairs.rename(
                    columns={
                        "n_years": "n_years_validation",
                        "rmse": "rmse_validation",
                        "mae": "mae_validation",
                        "mean_obs": "mean_obs_validation",
                        "nrmse_mean": "nrmse_validation_mean",
                    }
                ),
                on=["material", "region"],
                how="outer",
            ),
            "trial_id": int(self.eval_counter),
        }

        search_score = self._metric_value(result, self.search_metric)
        if not np.isfinite(search_score):
            search_score = 1.0e30
        result["search_score"] = float(search_score)
        result["search_metric"] = self.search_metric

        trial_row = {
            "trial_id": int(self.eval_counter),
            "stage": stage,
            "objective_search_metric": self.search_metric,
            "objective_search_score": float(search_score),
            "train_weighted_rmse": result["train_weighted_rmse"],
            "validation_weighted_rmse": result["validation_weighted_rmse"],
            "train_weighted_nrmse": result["train_weighted_nrmse"],
            "validation_weighted_nrmse": result["validation_weighted_nrmse"],
            "n_pairs_train": result["n_pairs_train"],
            "n_pairs_validation": result["n_pairs_validation"],
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        trial_row.update({f"param_{k}": float(v) for k, v in params.items()})
        self.trials.append(trial_row)
        self.eval_counter += 1
        self.cache[key] = result
        self.results.append(result)

        if self.search_best_result is None or search_score < float(self.search_best_result["search_score"]):
            self.search_best_result = result
            print(
                f"[best] trial={trial_row['trial_id']} stage={stage} "
                f"{self.search_metric}={search_score:.6g} "
                f"train_wRMSE={result['train_weighted_rmse']:.6g} "
                f"val_wRMSE={result['validation_weighted_rmse']:.6g}"
            )

        self._persist_partial_outputs(force=False)

        return result

    def objective(self, vector: np.ndarray, *, stage: str) -> float:
        if self._deadline_monotonic is not None and time.monotonic() >= self._deadline_monotonic:
            self.request_stop("max_runtime_reached")
            raise KeyboardInterrupt
        clipped = np.array(vector, dtype=float)
        lows = np.array([b[0] for b in self.bounds], dtype=float)
        highs = np.array([b[1] for b in self.bounds], dtype=float)
        clipped = np.clip(clipped, lows, highs)
        return float(self._run_and_score(clipped, stage=stage)["search_score"])

    def select_best_result(self) -> Dict[str, Any]:
        if not self.results:
            raise RuntimeError("No evaluated candidates available for selection.")

        feasible = [r for r in self.results if self._passes_selection_constraints(r)]
        if feasible:
            selected = min(feasible, key=lambda r: self._metric_value(r, self.primary_metric))
            self.selection_reason = (
                f"selected by primary_metric='{self.primary_metric}' among "
                f"{len(feasible)} feasible candidates"
            )
        else:
            selected = min(self.results, key=lambda r: self._metric_value(r, self.fallback_metric))
            self.selection_reason = (
                "no candidate satisfied selection constraints; "
                f"fell back to fallback_metric='{self.fallback_metric}' across "
                f"{len(self.results)} candidates"
            )
        self.selected_result = selected
        return selected


def _estimate_de_iters(max_evaluations: int, dim: int, popsize: int) -> Tuple[int, int]:
    if max_evaluations <= 0:
        return 0, max(1, popsize)
    if dim <= 0:
        raise ValueError("No parameters selected for calibration.")

    eff_pop = max(1, min(popsize, max(1, max_evaluations // dim)))
    maxiter = max(0, math.ceil(max_evaluations / (eff_pop * dim)) - 1)
    return maxiter, eff_pop


def _build_patch(problem: CalibrationProblem, result: Dict[str, Any] | None) -> Dict[str, Any]:
    if result is None:
        return {}

    patch: Dict[str, Any] = {}
    for spec in problem.param_specs:
        if spec["kind"] != "global":
            continue
        _set_by_path(patch, str(spec["path"]), float(result["params"][str(spec["name"])]))

    has_slice = any(s["kind"] == "slice_adjustment" for s in problem.param_specs)
    if has_slice:
        vec = np.array([float(result["params"][n]) for n in problem.param_names], dtype=float)
        cfg_trial = problem._vector_to_cfg(vec)
        variant_cfg = cfg_trial.variants[problem.variant_name]
        all_overrides = [
            ov.model_dump(exclude_none=True, exclude_unset=True)
            for ov in variant_cfg.dimension_overrides
        ]
        _set_by_path(
            patch,
            f"variants.{problem.variant_name}.dimension_overrides",
            all_overrides,
        )
    return patch


def main() -> int:
    ap = argparse.ArgumentParser(description="Calibrate SD-dMFA parameters to stock observations.")
    ap.add_argument("--config", default="configs/runs/mvp.yml")
    ap.add_argument("--calibration-spec", default="configs/calibration.yml")
    ap.add_argument("--variant", default="baseline")
    ap.add_argument("--outdir", default="outputs/runs/calibration")
    ap.add_argument("--max-evals", type=int, default=None, help="Override global search max evaluations.")
    ap.add_argument("--seed", type=int, default=None, help="Override DE random seed.")
    ap.add_argument("--no-local", action="store_true", help="Disable local refinement stage.")
    ap.add_argument(
        "--max-runtime-minutes",
        type=float,
        default=None,
        help="Stop search after this wall-clock budget and keep best-so-far.",
    )
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cal_path = Path(args.calibration_spec).resolve()
    spec = _read_yaml(cal_path)

    problem = CalibrationProblem(cfg_path=cfg_path, variant_name=args.variant, calibration_spec=spec)
    problem.set_deadline_minutes(args.max_runtime_minutes)

    repo_root = resolve_repo_root_from_config(cfg_path)
    out_root = config_runs_root((repo_root / args.outdir).resolve(), cfg_path.stem)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = out_root / args.variant / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    problem.set_run_dir(run_dir)

    _write_yaml(
        run_dir / "run_info.yml",
        {
            "timestamp": stamp,
            "config": str(args.config),
            "calibration_spec": str(args.calibration_spec),
            "variant": args.variant,
            "max_evals_override": args.max_evals,
            "seed_override": args.seed,
            "no_local": bool(args.no_local),
            "max_runtime_minutes": args.max_runtime_minutes,
        },
    )
    print(f"Calibration artifacts (live): {run_dir}")

    print("Running baseline evaluation...")
    baseline_vec = np.array(problem.initial, dtype=float)
    _ = problem.objective(baseline_vec, stage="baseline")

    opt_spec = spec.get("optimization") or {}
    global_spec = opt_spec.get("global_search") or {}
    local_spec = opt_spec.get("local_refinement") or {}

    global_max_evals = int(global_spec.get("max_evaluations", 200))
    if args.max_evals is not None:
        global_max_evals = int(args.max_evals)
    popsize = int(global_spec.get("popsize", 10))
    seed = args.seed if args.seed is not None else global_spec.get("seed", None)
    maxiter, eff_popsize = _estimate_de_iters(global_max_evals, len(problem.bounds), popsize)
    stopping_spec = opt_spec.get("stopping") or {}
    min_improvement = float(stopping_spec.get("min_improvement", 0.0))
    patience_rounds = int(stopping_spec.get("patience_rounds", 0))
    de_best = {"score": float("inf"), "stale_rounds": 0}

    def _de_callback(_: np.ndarray, __: float) -> bool:
        if problem.stop_requested:
            return True
        best = problem.search_best_result
        if best is None:
            return False
        score = float(best["search_score"])
        if not np.isfinite(score):
            return False
        if de_best["score"] - score > min_improvement:
            de_best["score"] = score
            de_best["stale_rounds"] = 0
            return False
        de_best["stale_rounds"] += 1
        if patience_rounds > 0 and de_best["stale_rounds"] >= patience_rounds:
            print(
                "Global search early-stopped by patience: "
                f"stale_rounds={de_best['stale_rounds']} min_improvement={min_improvement:.3g}"
            )
            return True
        return False

    print(
        f"Global search: method=differential_evolution, max_evals~{global_max_evals}, "
        f"popsize={eff_popsize}, maxiter={maxiter}"
    )
    interrupted = False
    min_de_evals = len(problem.bounds)
    if global_max_evals < min_de_evals:
        print(
            f"Global search skipped: max_evals ({global_max_evals}) < minimum DE population size "
            f"for dim={len(problem.bounds)} ({min_de_evals})."
        )
    else:
        try:
            _ = differential_evolution(
                lambda x: problem.objective(np.asarray(x, dtype=float), stage="global"),
                bounds=problem.bounds,
                maxiter=maxiter,
                popsize=eff_popsize,
                seed=seed,
                polish=False,
                disp=False,
                callback=_de_callback,
            )
        except KeyboardInterrupt:
            interrupted = True
            problem.request_stop(problem.stop_reason or "keyboard_interrupt")
            print("Global search interrupted; keeping best-so-far.")

    local_enabled = bool(local_spec.get("enabled", True)) and (not args.no_local) and (not interrupted)
    if local_enabled:
        if problem.search_best_result is None:
            raise RuntimeError("No best result available after global search.")
        x0 = np.array([problem.search_best_result["params"][n] for n in problem.param_names], dtype=float)
        local_max_evals = int(local_spec.get("max_evaluations", 200))
        print(f"Local refinement: method=nelder_mead, max_evals={local_max_evals}")
        try:
            _ = minimize(
                lambda x: problem.objective(np.asarray(x, dtype=float), stage="local"),
                x0,
                method="Nelder-Mead",
                options={"maxfev": local_max_evals, "xatol": 1e-4, "fatol": 1e-6},
            )
        except KeyboardInterrupt:
            interrupted = True
            problem.request_stop(problem.stop_reason or "keyboard_interrupt")
            print("Local refinement interrupted; keeping best-so-far.")

    if problem.search_best_result is None:
        raise RuntimeError("Calibration failed: no evaluations completed.")
    selected_result = problem.select_best_result()
    search_best = problem.search_best_result
    problem._persist_partial_outputs(force=True)

    if problem.save_trial_history_csv:
        trials_df = pd.DataFrame(problem.trials)
        trials_df.to_csv(run_dir / "trial_history.csv", index=False)

    if problem.save_best_config_patch_yml:
        best_patch = _build_patch(problem, selected_result)
        _write_yaml(run_dir / "best_config_patch.yml", best_patch)
        _write_yaml(run_dir / "search_best_config_patch.yml", _build_patch(problem, search_best))

    best_pairs = selected_result["pair_summary"]
    if problem.save_validation_summary_csv and isinstance(best_pairs, pd.DataFrame):
        best_pairs.to_csv(run_dir / "validation_summary.csv", index=False)

    metadata = {
        "timestamp": stamp,
        "config": str(args.config),
        "calibration_spec": str(args.calibration_spec),
        "variant": args.variant,
        "objective": spec.get("objective", {}).get("id", "weighted_stock_rmse"),
        "search_metric": problem.search_metric,
        "selection_primary_metric": problem.primary_metric,
        "selection_fallback_metric": problem.fallback_metric,
        "selection_reason": problem.selection_reason,
        "selected_trial_id": int(selected_result["trial_id"]),
        "search_best_trial_id": int(search_best["trial_id"]),
        "train_weighted_rmse_best": float(selected_result["train_weighted_rmse"]),
        "validation_weighted_rmse_best": float(selected_result["validation_weighted_rmse"]),
        "train_weighted_nrmse_best": float(selected_result["train_weighted_nrmse"]),
        "validation_weighted_nrmse_best": float(selected_result["validation_weighted_nrmse"]),
        "n_unique_evaluations": int(len(problem.trials)),
        "best_params": selected_result["params"],
        "search_best_train_weighted_rmse": float(search_best["train_weighted_rmse"]),
        "search_best_validation_weighted_rmse": float(search_best["validation_weighted_rmse"]),
        "search_best_train_weighted_nrmse": float(search_best["train_weighted_nrmse"]),
        "search_best_validation_weighted_nrmse": float(search_best["validation_weighted_nrmse"]),
        "search_best_params": search_best["params"],
        "interrupted": bool(interrupted),
        "stop_reason": problem.stop_reason,
    }
    _write_yaml(run_dir / "calibration_metadata.yml", metadata)

    moved = archive_old_timestamped_runs(run_dir.parent, keep_last=3)
    if moved:
        print(f"Archived {len(moved)} older run(s) to: {run_dir.parent / '_archive'}")

    print(f"Saved calibration artifacts to: {run_dir}")
    print(
        f"Selected best ({problem.primary_metric}) trial={metadata['selected_trial_id']} "
        f"train_wRMSE={metadata['train_weighted_rmse_best']:.6g}, "
        f"validation_wRMSE={metadata['validation_weighted_rmse_best']:.6g}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
