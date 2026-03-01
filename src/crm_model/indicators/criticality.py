from __future__ import annotations

import pandas as pd
from dataclasses import dataclass
from typing import Dict

@dataclass
class CriticalityResult:
    name: str
    series: pd.Series
    meta: Dict[str, str]

# TODO: pick a criticality framework (EU CRM, Yale, Graedel, etc.)
# and clarify the system boundary and time dynamics.
def supply_risk_proxy(import_reliance: pd.Series, hhi_production: pd.Series) -> CriticalityResult:
    """Placeholder: a simple proxy combining import reliance and production concentration."""
    s = (import_reliance.clip(0,1) * hhi_production.clip(0,1))
    return CriticalityResult(
        name="SupplyRiskProxy",
        series=s,
        meta={"note": "Placeholder. Replace with agreed criticality framework."},
    )
