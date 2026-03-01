from __future__ import annotations

from dataclasses import dataclass
from typing import Dict
import numpy as np
import pandas as pd

@dataclass
class IndicatorResult:
    name: str
    series: pd.Series
    meta: Dict[str, str]

def end_of_life_recycling_rate(eol_recycled: pd.Series, eol_generated: pd.Series) -> IndicatorResult:
    rr = (eol_recycled / eol_generated).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return IndicatorResult(
        name="EoL_RR",
        series=rr,
        meta={"definition": "EoL RR = EoL recycled / EoL generated"},
    )

def recycling_input_rate(recycled_input: pd.Series, total_input: pd.Series) -> IndicatorResult:
    rir = (recycled_input / total_input).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return IndicatorResult(
        name="RIR",
        series=rir,
        meta={"definition": "RIR = secondary input / total input"},
    )
