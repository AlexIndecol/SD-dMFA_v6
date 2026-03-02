from __future__ import annotations

from pathlib import Path

import pandas as pd

from crm_model.data.io import load_supplier_governance_risk


def test_supplier_governance_risk_dataset_contract():
    root = Path(__file__).resolve().parents[1]
    path = root / "data" / "exogenous" / "supplier_governance_risk.csv"
    df = load_supplier_governance_risk(path)

    years = set(df["year"].astype(int).unique().tolist())
    assert years == set(range(1870, 2101))

    origins = set(df["origin_region"].astype(str).unique().tolist())
    assert origins == {"EU27", "China", "RoW"}

    assert ((df["value"] >= 0.0) & (df["value"] <= 1.0)).all()

    counts = df.groupby("origin_region")["year"].nunique()
    assert int(counts["EU27"]) == 231
    assert int(counts["China"]) == 231
    assert int(counts["RoW"]) == 231

