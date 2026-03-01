from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from crm_model.scenario_profiles import (
    build_variant_payload_from_profiles,
    expand_reporting_profile_series,
    load_reporting_profile_csv,
)


def test_expand_reporting_profile_series_covers_full_horizon():
    years = [2018, 2019, 2020, 2021, 2022]
    out = expand_reporting_profile_series(
        years=years,
        report_start_year=2020,
        year_values={2020: 1.0, 2022: 0.8},
        before_value=0.95,
    )
    assert len(out) == len(years)
    assert np.isclose(out[0], 0.95)
    assert np.isclose(out[1], 0.95)
    assert np.isclose(out[2], 1.0)
    assert np.isclose(out[-1], 0.8)


def test_load_reporting_profile_csv_rejects_duplicates(tmp_path: Path):
    p = tmp_path / "dup.csv"
    p.write_text(
        "variant,block,key,year,value,material,region\n"
        "v1,sd_parameters,a,2020,1.0,,\n"
        "v1,sd_parameters,a,2020,1.1,,\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicated rows"):
        load_reporting_profile_csv(p)


def test_build_variant_payload_from_profiles_creates_global_and_override_payloads():
    df = pd.DataFrame(
        [
            {"variant": "v1", "block": "sd_parameters", "key": "capacity_expansion_gain", "year": 2020, "value": 0.2, "material": "", "region": "", "before": 0.15},
            {"variant": "v1", "block": "sd_parameters", "key": "capacity_expansion_gain", "year": 2022, "value": 0.3, "material": "", "region": "", "before": np.nan},
            {"variant": "v1", "block": "demand_transformation", "key": "efficiency_improvement", "year": 2020, "value": 0.01, "material": "nickel", "region": "EU27", "before": np.nan},
            {"variant": "v1", "block": "demand_transformation", "key": "efficiency_improvement", "year": 2022, "value": 0.05, "material": "nickel", "region": "EU27", "before": np.nan},
        ]
    )
    payload = build_variant_payload_from_profiles(
        profiles=df,
        years=[2019, 2020, 2021, 2022],
        report_start_year=2020,
    )
    assert "v1" in payload
    assert "sd_parameters" in payload["v1"]
    assert len(payload["v1"]["sd_parameters"]["capacity_expansion_gain"]) == 4
    assert payload["v1"]["dimension_overrides"][0]["materials"] == ["nickel"]
    assert payload["v1"]["dimension_overrides"][0]["regions"] == ["EU27"]

