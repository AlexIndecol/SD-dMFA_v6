from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np


def _is_year_gate(value: Any) -> bool:
    return isinstance(value, dict) and "start_year" in value and "value" in value


def _is_ramp_points(value: Any) -> bool:
    return isinstance(value, dict) and "points" in value


def _parse_ramp_points(*, points: Any, name: str) -> tuple[np.ndarray, np.ndarray]:
    if isinstance(points, dict):
        items = [(int(k), float(v)) for k, v in points.items()]
    elif isinstance(points, (list, tuple)):
        items = []
        for row in points:
            if not isinstance(row, dict) or "year" not in row or "value" not in row:
                raise ValueError(
                    f"{name}.points list items must be mappings with 'year' and 'value'."
                )
            items.append((int(row["year"]), float(row["value"])))
    else:
        raise ValueError(
            f"{name}.points must be a mapping {{year: value}} or a list of {{year, value}} mappings."
        )
    if not items:
        raise ValueError(f"{name}.points must not be empty.")
    items = sorted(items, key=lambda kv: kv[0])
    x = np.array([yy for yy, _ in items], dtype=float)
    y = np.array([vv for _, vv in items], dtype=float)
    if np.unique(x).size != x.size:
        raise ValueError(f"{name}.points contains duplicate years.")
    return x, y


def _gate_with_before(value: Any, before: Any) -> Any:
    if _is_year_gate(value):
        if "before" in value:
            return value
        out = dict(value)
        out["before"] = before
        return out
    if _is_ramp_points(value):
        if "before" in value:
            return value
        out = dict(value)
        out["before"] = before
        return out
    return value


def _as_timeseries(
    value: Any,
    *,
    years: Sequence[int],
    name: str,
    default: Optional[float] = None,
) -> np.ndarray:
    if _is_ramp_points(value):
        interpolation = str(value.get("interpolation", "linear")).strip().lower()
        if interpolation != "linear":
            raise ValueError(f"{name}.interpolation must be 'linear'; got {interpolation!r}.")
        x, y = _parse_ramp_points(points=value.get("points"), name=name)
        xq = np.array([int(yy) for yy in years], dtype=float)
        yq = np.interp(xq, x, y, left=float(y[0]), right=float(y[-1]))
        before_value = value.get("before", None)
        if before_value is None:
            return np.array(yq, dtype=float)
        before_ts = _as_timeseries(
            before_value,
            years=years,
            name=f"{name}.before",
            default=default,
        )
        out = before_ts.copy()
        start_year = int(np.min(x))
        for i, yy in enumerate(years):
            if int(yy) >= start_year:
                out[i] = float(yq[i])
        return out

    if _is_year_gate(value):
        start_year = int(value["start_year"])
        before_value = value.get("before", default)
        gate_ts = _as_timeseries(
            value["value"],
            years=years,
            name=f"{name}.value",
            default=default,
        )
        if all(int(y) >= start_year for y in years):
            return gate_ts
        if before_value is None:
            raise ValueError(
                f"{name} gate is missing 'before' and no default baseline is available."
            )
        before_ts = _as_timeseries(
            before_value,
            years=years,
            name=f"{name}.before",
            default=default,
        )
        out = before_ts.copy()
        for i, y in enumerate(years):
            if int(y) >= start_year:
                out[i] = gate_ts[i]
        return out

    if value is None:
        if default is None:
            raise ValueError(f"Missing required parameter '{name}'.")
        return np.array([float(default)] * len(years), dtype=float)
    if isinstance(value, (list, tuple, np.ndarray)):
        arr = np.array(value, dtype=float).reshape(-1)
        if arr.size != len(years):
            raise ValueError(f"{name} must have length {len(years)}; got {arr.size}.")
        return arr
    return np.array([float(value)] * len(years), dtype=float)


def _resolve_routing_rates(
    *,
    years: Sequence[int],
    strategy: Dict[str, Any],
    params: Dict[str, Any],
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    reman_baseline = params.get("remanufacturing_rate", params.get("remanufacture_share", 0.0))
    if "remanufacturing_rate" in strategy:
        reman_rate = _gate_with_before(strategy.get("remanufacturing_rate"), reman_baseline)
    elif "remanufacture_share" in strategy:
        reman_rate = _gate_with_before(strategy.get("remanufacture_share"), reman_baseline)
    else:
        reman_rate = reman_baseline

    rec_baseline = params.get("recycling_rate")
    rec_rate = (
        _gate_with_before(strategy.get("recycling_rate"), rec_baseline)
        if "recycling_rate" in strategy
        else rec_baseline
    )

    disp_baseline = params.get("disposal_rate")
    disp_rate = (
        _gate_with_before(strategy.get("disposal_rate"), disp_baseline)
        if "disposal_rate" in strategy
        else disp_baseline
    )

    reman_ts = _as_timeseries(reman_rate, years=years, name="remanufacturing_rate", default=0.0)

    rec_default = None
    disp_default = None
    if rec_rate is None and disp_rate is None:
        rec_default = 1.0
        disp_default = 0.0
    elif rec_rate is None:
        rec_default = 0.0
    elif disp_rate is None:
        disp_default = 0.0

    rec_ts = _as_timeseries(rec_rate, years=years, name="recycling_rate", default=rec_default)
    disp_ts = _as_timeseries(disp_rate, years=years, name="disposal_rate", default=disp_default)

    # Complete single-missing residual if needed.
    if rec_rate is None and disp_rate is not None:
        rec_ts = 1.0 - reman_ts - disp_ts
    elif disp_rate is None and rec_rate is not None:
        disp_ts = 1.0 - reman_ts - rec_ts
    elif rec_rate is None and disp_rate is None:
        rec_ts = 1.0 - reman_ts

    for name, arr in {
        "recycling_rate": rec_ts,
        "remanufacturing_rate": reman_ts,
        "disposal_rate": disp_ts,
    }.items():
        if (arr < 0).any() or (arr > 1).any():
            raise ValueError(f"{name} must be in [0, 1].")

    if not np.allclose(rec_ts + reman_ts + disp_ts, 1.0, atol=1e-9):
        raise ValueError("recycling_rate + remanufacturing_rate + disposal_rate must equal 1.0.")

    return rec_ts, reman_ts, disp_ts



__all__ = ["_as_timeseries", "_resolve_routing_rates"]
