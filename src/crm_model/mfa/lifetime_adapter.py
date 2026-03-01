from __future__ import annotations

import math
from typing import Sequence

import numpy as np
import pandas as pd
from flodym import Dimension, DimensionSet
from flodym.lifetime_models import LogNormalLifetime, WeibullLifetime

from crm_model.data.io import normalize_material, normalize_region


def _time_only_dims(n_steps: int) -> DimensionSet:
    return DimensionSet(
        dim_list=[Dimension(name="Time", letter="t", items=list(range(int(n_steps))))]
    )


def _weibull_scale_from_mean(mean_years: float, shape_k: float) -> float:
    return float(mean_years) / float(math.gamma(1.0 + 1.0 / float(shape_k)))


def discrete_lifetime_pdf_from_flodym(
    *,
    dist: str,
    max_age: int,
    lifetime_multiplier: float = 1.0,
    mean_years: float | None = None,
    shape: float | None = None,
    scale: float | None = None,
    sigma: float | None = None,
    mu: float | None = None,
) -> np.ndarray:
    """Build a 1D discrete retirement PDF (ages 0..max_age) using flodym lifetime models.
    """

    if max_age < 0:
        raise ValueError(f"max_age must be >= 0; got {max_age}")
    if float(lifetime_multiplier) <= 0:
        raise ValueError(f"lifetime_multiplier must be > 0; got {lifetime_multiplier}")

    a_len = int(max_age) + 1
    dist = str(dist).lower()

    if dist == "fixed":
        if mean_years is None or not np.isfinite(float(mean_years)) or float(mean_years) <= 0:
            raise ValueError("fixed lifetime requires mean_years > 0.")
        out = np.zeros(a_len, dtype=float)
        L = int(round(float(mean_years) * float(lifetime_multiplier)))
        if 0 <= L <= max_age:
            out[L] = 1.0
        return out

    dims = _time_only_dims(a_len)
    # Use start-of-interval inflow for annual-bin retirement convention.
    common_kw = {"dims": dims, "inflow_at": "start", "n_pts_per_interval": 1}

    if dist == "weibull":
        if shape is None or not np.isfinite(float(shape)) or float(shape) <= 0:
            raise ValueError("weibull lifetime requires shape > 0.")
        k = float(shape)
        if scale is None:
            if mean_years is None or not np.isfinite(float(mean_years)) or float(mean_years) <= 0:
                raise ValueError("weibull lifetime requires either scale > 0 or mean_years > 0.")
            lam = _weibull_scale_from_mean(float(mean_years), k)
        else:
            lam = float(scale)
        lam = lam * float(lifetime_multiplier)
        if not np.isfinite(lam) or lam <= 0:
            raise ValueError("weibull scale must be > 0 after lifetime_multiplier.")

        model = WeibullLifetime(**common_kw)
        model.set_prms(
            weibull_shape=np.full(a_len, k, dtype=float),
            weibull_scale=np.full(a_len, lam, dtype=float),
        )
        out = np.array(model.pdf[:, 0], dtype=float)
        out[0] = 0.0
        return np.clip(out, 0.0, 1.0)

    if dist == "lognormal":
        if sigma is None or not np.isfinite(float(sigma)) or float(sigma) <= 0:
            raise ValueError("lognormal lifetime requires sigma > 0.")
        sig = float(sigma)

        if mu is None:
            if mean_years is None or not np.isfinite(float(mean_years)) or float(mean_years) <= 0:
                raise ValueError("lognormal lifetime requires either mu or mean_years > 0.")
            mean = float(mean_years)
        else:
            mean = float(np.exp(float(mu) + 0.5 * (sig**2)))
        std = float(mean * np.sqrt(np.exp(sig**2) - 1.0))

        mean *= float(lifetime_multiplier)
        std *= float(lifetime_multiplier)
        if not np.isfinite(mean) or mean <= 0 or not np.isfinite(std) or std <= 0:
            raise ValueError("lognormal mean/std must be > 0 after lifetime_multiplier.")

        model = LogNormalLifetime(**common_kw)
        model.set_prms(
            mean=np.full(a_len, mean, dtype=float),
            std=np.full(a_len, std, dtype=float),
        )
        out = np.array(model.pdf[:, 0], dtype=float)
        out[0] = 0.0
        return np.clip(out, 0.0, 1.0)

    raise ValueError(f"Unsupported lifetime dist '{dist}'.")


def lifetime_pdf_trea_flodym_adapter(
    lifetime_long_df: pd.DataFrame,
    *,
    years: Sequence[int],
    material: str,
    regions: Sequence[str],
    end_uses: Sequence[str],
    lifetime_multiplier: float | Sequence[float] = 1.0,
    max_age: int | None = None,
    fill_method: str = "ffill",
) -> np.ndarray:
    """Build (t,r,e,a) discrete retirement PDFs backed by flodym lifetime models."""

    if max_age is None:
        max_age = max(1, len(years) - 1)

    t_len = len(years)
    r_len = len(regions)
    e_len = len(end_uses) if len(end_uses) else 1
    a_len = max_age + 1
    out = np.zeros((t_len, r_len, e_len, a_len), dtype=float)

    if isinstance(lifetime_multiplier, (list, tuple, np.ndarray)):
        multiplier_ts = np.array(lifetime_multiplier, dtype=float).reshape(-1)
        if multiplier_ts.size != t_len:
            raise ValueError(
                f"lifetime_multiplier timeseries length must match years length {t_len}; got {multiplier_ts.size}."
            )
    else:
        multiplier_ts = np.full(t_len, float(lifetime_multiplier), dtype=float)
    if (multiplier_ts <= 0).any():
        raise ValueError("lifetime_multiplier must be > 0 for all modeled years.")

    material = normalize_material(material)
    sub_all = lifetime_long_df[lifetime_long_df["material"] == material].copy()
    if sub_all.empty:
        raise ValueError(f"Missing lifetime distributions for material={material}")

    for r_idx, region in enumerate(regions):
        region = normalize_region(region)
        sub = sub_all[sub_all["region"] == region].copy()
        if sub.empty:
            raise ValueError(f"Missing lifetime distributions for material={material}, region={region}")

        for e_idx, eu in enumerate(end_uses):
            eu_sub = sub[sub["end_use"] == eu].copy()
            eu_sub = eu_sub.sort_values(["cohort_year", "param"])
            if eu_sub.empty:
                raise ValueError(
                    f"Missing lifetime distributions for material={material}, region={region}, end_use={eu}"
                )

            dist_by_year = eu_sub.groupby("cohort_year", as_index=True)["dist"].first().reindex(list(years))
            if fill_method:
                dist_by_year = dist_by_year.ffill().bfill()

            params_by_year = eu_sub.pivot(index="cohort_year", columns="param", values="value").reindex(list(years))
            if fill_method:
                params_by_year = params_by_year.ffill().bfill()

            for t_idx, y in enumerate(years):
                row = params_by_year.loc[y]
                dist = str(dist_by_year.loc[y]).lower()
                if dist in {"nan", ""}:
                    raise ValueError(
                        "Missing lifetime dist after reindex/fill for "
                        f"material={material}, region={region}, end_use={eu}, year={y}"
                    )

                pdf = discrete_lifetime_pdf_from_flodym(
                    dist=dist,
                    max_age=max_age,
                    lifetime_multiplier=float(multiplier_ts[t_idx]),
                    mean_years=float(row.get("mean_years")) if not pd.isna(row.get("mean_years")) else None,
                    shape=float(row.get("shape")) if not pd.isna(row.get("shape")) else None,
                    scale=float(row.get("scale")) if not pd.isna(row.get("scale")) else None,
                    sigma=float(row.get("sigma")) if not pd.isna(row.get("sigma")) else None,
                    mu=float(row.get("mu")) if not pd.isna(row.get("mu")) else None,
                )
                out[t_idx, r_idx, e_idx, :] = pdf[:a_len]

    return out
