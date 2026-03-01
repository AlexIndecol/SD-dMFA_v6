from __future__ import annotations

from dataclasses import dataclass
from typing import Dict
import pandas as pd


@dataclass
class IndicatorResult:
    name: str
    series: pd.Series
    meta: Dict[str, str]


def mfa_state_flow_metrics(ts) -> Dict[str, IndicatorResult]:
    """Return basic MFA state & flow metrics as time series.

    The template keeps this close to the dMFA outputs to avoid duplicated logic.
    """
    return {
        "Stock_in_use": IndicatorResult(
            name="Stock_in_use",
            series=ts.stock_in_use,
            meta={"category": "MFA state & flow metrics", "definition": "Stock of material in use"},
        ),
        "Inflow_to_use_total": IndicatorResult(
            name="Inflow_to_use_total",
            series=ts.inflow_to_use_total,
            meta={"category": "MFA state & flow metrics", "definition": "Delivered inflow to use (new + reman)"},
        ),
        "Outflow_from_use": IndicatorResult(
            name="Outflow_from_use",
            series=ts.outflow_from_use,
            meta={"category": "MFA state & flow metrics", "definition": "Outflow from use to end-of-life"},
        ),
        "Primary_supply": IndicatorResult(
            name="Primary_supply",
            series=ts.primary_supply,
            meta={"category": "MFA state & flow metrics", "definition": "Primary material input used"},
        ),
        "Secondary_supply": IndicatorResult(
            name="Secondary_supply",
            series=ts.secondary_supply,
            meta={"category": "MFA state & flow metrics", "definition": "Secondary material input used"},
        ),
        "EoL_recycled": IndicatorResult(
            name="EoL_recycled",
            series=ts.eol_recycled,
            meta={"category": "MFA state & flow metrics", "definition": "End-of-life material recycled (output of recycling)"},
        ),
        "EoL_remanufactured": IndicatorResult(
            name="EoL_remanufactured",
            series=ts.eol_remanufactured,
            meta={"category": "MFA state & flow metrics", "definition": "End-of-life material remanufactured (output of reman)"},
        ),
    }
