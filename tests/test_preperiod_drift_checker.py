from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


def _load_checker_module():
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "validation" / "check_reporting_preperiod_drift.py"
    spec = importlib.util.spec_from_file_location("check_reporting_preperiod_drift", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_collect_drift_rows_filters_observed_and_post_report_years():
    mod = _load_checker_module()
    scenario_ts = pd.DataFrame(
        [
            {"year": 2019, "material": "tin", "region": "EU27", "indicator": "Stock_in_use", "value": 12.0},
            {"year": 2019, "material": "tin", "region": "EU27", "indicator": "Observed_stock", "value": 20.0},
            {"year": 2020, "material": "tin", "region": "EU27", "indicator": "Stock_in_use", "value": 14.0},
        ]
    )
    baseline_ts = pd.DataFrame(
        [
            {"year": 2019, "material": "tin", "region": "EU27", "indicator": "Stock_in_use", "value": 10.0},
            {"year": 2019, "material": "tin", "region": "EU27", "indicator": "Observed_stock", "value": 5.0},
            {"year": 2020, "material": "tin", "region": "EU27", "indicator": "Stock_in_use", "value": 10.0},
        ]
    )

    out = mod._collect_drift_rows(
        scenario_ts=scenario_ts,
        baseline_ts=baseline_ts,
        report_start_year=2020,
        tolerance=0.5,
        scenario="scenario_a",
        scenario_run_id="20260304-000000",
        baseline_run_id="20260304-000001",
    )

    assert len(out) == 1
    row = out.iloc[0]
    assert row["indicator"] == "Stock_in_use"
    assert row["year"] == 2019
    assert row["abs_diff"] == 2.0
    assert row["scenario"] == "scenario_a"


def test_summarize_drift_picks_worst_row_per_scenario():
    mod = _load_checker_module()
    drift = pd.DataFrame(
        [
            {
                "scenario": "s1",
                "indicator": "Stock_in_use",
                "material": "tin",
                "region": "EU27",
                "year": 2018,
                "abs_diff": 1.0,
            },
            {
                "scenario": "s1",
                "indicator": "Extraction_losses",
                "material": "tin",
                "region": "EU27",
                "year": 2019,
                "abs_diff": 3.0,
            },
            {
                "scenario": "s2",
                "indicator": "Primary_supply",
                "material": "zinc",
                "region": "RoW",
                "year": 2015,
                "abs_diff": 2.0,
            },
        ]
    )

    summary = mod._summarize_drift(drift)
    assert set(summary["scenario"]) == {"s1", "s2"}
    s1 = summary.loc[summary["scenario"] == "s1"].iloc[0]
    assert s1["max_abs_diff"] == 3.0
    assert s1["worst_indicator"] == "Extraction_losses"
