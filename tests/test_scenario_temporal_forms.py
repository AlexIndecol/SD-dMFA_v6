from __future__ import annotations

from pathlib import Path

from crm_model.config.io import load_run_config
from crm_model.scenario_profiles import (
    build_variant_payload_from_profiles,
    load_reporting_profile_csv,
)


def test_transition_policy_remains_scalar_surface_in_scenarios():
    root = Path(__file__).resolve().parents[1]
    mvp = load_run_config(root / "configs" / "runs" / "mvp.yml")
    variant = mvp.variants["transition_policy_acceleration"]
    tp = (
        variant.transition_policy
        if isinstance(variant.transition_policy, dict)
        else variant.transition_policy.model_dump(exclude_none=True, exclude_unset=True)
    )
    assert isinstance(tp["enabled"], bool)
    assert isinstance(tp["start_year"], int)
    assert isinstance(tp["adoption_target"], float)


def test_r02_family_uses_year_gated_demand_transformation_controls():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "r-strategies.yml")
    for name in [
        "r02_demand_efficiency_low",
        "r02_demand_efficiency_medium",
        "r02_demand_efficiency_high",
    ]:
        dt = cfg.variants[name].demand_transformation
        node = dt if isinstance(dt, dict) else dt.model_dump(exclude_none=True, exclude_unset=True)
        eff = node["efficiency_improvement"]
        assert isinstance(eff, dict)
        assert int(eff["start_year"]) >= 2025


def test_profile_csv_pipeline_produces_full_horizon_timeseries_payload():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "mvp.yml")
    profile = load_reporting_profile_csv(
        root / "data" / "ramp_profiles" / "mvp" / "import_squeeze_circular_ramp.csv"
    )
    payload = build_variant_payload_from_profiles(
        profiles=profile,
        years=cfg.time.years,
        report_start_year=cfg.time.report_start_year,
    )
    series = payload["import_squeeze_circular_ramp"]["demand_transformation"]["efficiency_improvement"]
    assert len(series) == len(cfg.time.years)
