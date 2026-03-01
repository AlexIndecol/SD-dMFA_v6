from __future__ import annotations

import numpy as np
import pytest

from crm_model.config.io import load_run_config
from crm_model.coupling.interface import validate_coupling_signal_registry
from crm_model.coupling.runner import run_loose_coupled


def test_coupling_config_signals_match_registry_for_core_configs():
    for cfg_path in ["configs/base.yml", "configs/runs/_core.yml", "configs/runs/mvp.yml"]:
        cfg = load_run_config(cfg_path)
        validate_coupling_signal_registry(cfg.coupling.model_dump())


def test_validate_coupling_signal_registry_rejects_unknown_signal_names():
    with pytest.raises(ValueError, match="Unknown coupling signals"):
        validate_coupling_signal_registry(
            {
                "signals": {
                    "sd_to_mfa": ["desired_demand_t", "unknown_signal"],
                    "mfa_to_sd": [
                        "service_stress_t",
                        "circular_supply_stress_t",
                        "strategic_stock_coverage_years_t",
                    ],
                }
            }
        )


def test_run_loose_coupled_rejects_invalid_signal_registry():
    years = [2000, 2001, 2002]
    t = len(years)

    final_demand_t = np.array([100.0, 100.0, 100.0], dtype=float)
    end_use_shares_te = np.ones((t, 1), dtype=float)
    lifetime_pdf = np.zeros((t, 1, 1, t), dtype=float)
    lifetime_pdf[:, :, :, 1] = 1.0

    sd_params = {
        "start_year": 2000,
        "report_start_year": 2000,
        "report_years": years,
    }
    mfa_params = {
        "fabrication_yield": 1.0,
        "collection_rate": 0.5,
        "recycling_yield": 1.0,
        "reman_yield": 1.0,
        "lifetime_pdf_trea": lifetime_pdf,
        "primary_available_to_refining": np.full((t, 1), 1.0e6, dtype=float),
    }

    with pytest.raises(ValueError, match="Unknown coupling signals"):
        run_loose_coupled(
            years=years,
            material="tin",
            region="EU27",
            end_uses=["construction"],
            final_demand_t=final_demand_t,
            end_use_shares_te=end_use_shares_te,
            sd_params=sd_params,
            mfa_params=mfa_params,
            strategy={},
            shocks={},
            coupling={
                "signals": {
                    "sd_to_mfa": ["desired_demand_t", "bad_signal"],
                    "mfa_to_sd": [
                        "service_stress_t",
                        "circular_supply_stress_t",
                        "strategic_stock_coverage_years_t",
                    ],
                }
            },
        )
