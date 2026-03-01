from __future__ import annotations

from crm_model.sd import DemandModel, SDTimeseries, run_bptk_sd
from crm_model.sd.bptk_model import DemandModel as DemandModelNew
from crm_model.sd.bptk_model import SDTimeseries as SDTimeseriesNew
from crm_model.sd.builder import (
    DemandModel as DemandModelCompat,
    SDTimeseries as SDTimeseriesCompat,
    run_bptk_sd as run_bptk_sd_compat,
)
from crm_model.sd.run_sd import run_bptk_sd as run_bptk_sd_new


def test_sd_split_exports_are_wired_and_compatible():
    assert run_bptk_sd is run_bptk_sd_new
    assert run_bptk_sd_compat is run_bptk_sd_new
    assert SDTimeseries is SDTimeseriesNew
    assert SDTimeseriesCompat is SDTimeseriesNew
    assert DemandModel is DemandModelNew
    assert DemandModelCompat is DemandModelNew
