from __future__ import annotations

from crm_model.mfa import MFATimeseries, SimpleMetalCycleWithReman, run_flodym_mfa
from crm_model.mfa.builder import (
    MFATimeseries as MFATimeseriesCompat,
    SimpleMetalCycleWithReman as SimpleMetalCycleWithRemanCompat,
    run_flodym_mfa as run_flodym_mfa_compat,
)
from crm_model.mfa.run_mfa import run_flodym_mfa as run_flodym_mfa_new
from crm_model.mfa.system import MFATimeseries as MFATimeseriesNew


def test_mfa_split_exports_are_wired_and_compatible():
    assert run_flodym_mfa is run_flodym_mfa_new
    assert run_flodym_mfa_compat is run_flodym_mfa_new
    assert MFATimeseries is MFATimeseriesNew
    assert MFATimeseriesCompat is MFATimeseriesNew
    assert SimpleMetalCycleWithReman is SimpleMetalCycleWithRemanCompat
