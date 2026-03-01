from __future__ import annotations

from pathlib import Path

import numpy as np

from crm_model.scenario_profiles import load_reporting_profile_csv


def _values(profile, *, variant: str, block: str, key: str, region: str = ""):
    hit = profile[
        (profile["variant"] == variant)
        & (profile["block"] == block)
        & (profile["key"] == key)
        & (profile["material"] == "")
        & (profile["region"] == region)
    ].sort_values("year")
    return {int(r.year): float(r.value) for r in hit.itertuples(index=False)}


def test_r36_r79_profiles_use_multi_anchor_ramps_not_single_steps():
    root = Path(__file__).resolve().parents[1]
    r36 = load_reporting_profile_csv(root / "data" / "ramp_profiles" / "r_strategies" / "r36_profiles.csv")
    r79 = load_reporting_profile_csv(root / "data" / "ramp_profiles" / "r_strategies" / "r79_profiles.csv")

    # Core structural keys should expose 2025/2035/2050 anchors (plus optional 2020 baseline anchor).
    for variant in ["r36_lifetime_reman_low", "r36_lifetime_reman_medium", "r36_lifetime_reman_high"]:
        pts = _values(r36, variant=variant, block="strategy", key="recycling_rate")
        assert {2025, 2035, 2050}.issubset(set(pts.keys()))
        assert np.isfinite(pts[2035])

    for variant in ["r79_recovery_loops_low", "r79_recovery_loops_medium", "r79_recovery_loops_high"]:
        pts = _values(r79, variant=variant, block="mfa_parameters", key="collection_rate")
        assert {2020, 2025, 2035, 2050}.issubset(set(pts.keys()))
        # Non-acute structural collection ramps should avoid large early jump at reporting start.
        assert abs(pts[2025] - pts[2020]) <= 0.03


def test_r79_ramps_preserve_monotonic_ambition_ladder_by_2050():
    root = Path(__file__).resolve().parents[1]
    r79 = load_reporting_profile_csv(root / "data" / "ramp_profiles" / "r_strategies" / "r79_profiles.csv")

    for region in ["", "EU27", "China", "RoW"]:
        low_rec = _values(r79, variant="r79_recovery_loops_low", block="strategy", key="recycling_rate", region=region)
        med_rec = _values(r79, variant="r79_recovery_loops_medium", block="strategy", key="recycling_rate", region=region)
        high_rec = _values(r79, variant="r79_recovery_loops_high", block="strategy", key="recycling_rate", region=region)
        if not low_rec or not med_rec or not high_rec:
            continue
        assert low_rec[2050] <= med_rec[2050] <= high_rec[2050]

        low_yield = _values(r79, variant="r79_recovery_loops_low", block="strategy", key="recycling_yield", region=region)
        med_yield = _values(r79, variant="r79_recovery_loops_medium", block="strategy", key="recycling_yield", region=region)
        high_yield = _values(r79, variant="r79_recovery_loops_high", block="strategy", key="recycling_yield", region=region)
        if not low_yield or not med_yield or not high_yield:
            continue
        assert low_yield[2050] <= med_yield[2050] <= high_yield[2050]
