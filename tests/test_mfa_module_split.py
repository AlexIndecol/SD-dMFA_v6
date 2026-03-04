from __future__ import annotations

from crm_model.mfa import MFATimeseries, SimpleMetalCycleWithReman, run_flodym_mfa
from crm_model.mfa.builder import (
    MFATimeseries as MFATimeseriesCompat,
    SimpleMetalCycleWithReman as SimpleMetalCycleWithRemanCompat,
    run_flodym_mfa as run_flodym_mfa_compat,
)
from crm_model.mfa.run_mfa import (
    _strategy_override_with_before,
    run_flodym_mfa as run_flodym_mfa_new,
)
from crm_model.mfa.system import MFATimeseries as MFATimeseriesNew


def test_mfa_split_exports_are_wired_and_compatible():
    assert run_flodym_mfa is run_flodym_mfa_new
    assert run_flodym_mfa_compat is run_flodym_mfa_new
    assert MFATimeseries is MFATimeseriesNew
    assert MFATimeseriesCompat is MFATimeseriesNew
    assert SimpleMetalCycleWithReman is SimpleMetalCycleWithRemanCompat


def test_strategy_override_with_before_injects_ramp_before_when_missing():
    strategy = {
        "recycling_yield": {
            "points": {2020: 0.85, 2030: 0.9},
        }
    }
    out = _strategy_override_with_before(strategy, "recycling_yield", 0.8)
    assert isinstance(out, dict)
    assert out.get("before") == 0.8
    assert out.get("points") == {2020: 0.85, 2030: 0.9}


def test_strategy_override_with_before_preserves_existing_ramp_before():
    strategy = {
        "recycling_yield": {
            "points": {2020: 0.85, 2030: 0.9},
            "before": 0.77,
        }
    }
    out = _strategy_override_with_before(strategy, "recycling_yield", 0.8)
    assert isinstance(out, dict)
    assert out.get("before") == 0.77
