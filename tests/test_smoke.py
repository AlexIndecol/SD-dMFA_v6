import numpy as np
import pytest

from crm_model.coupling.runner import run_loose_coupled
from crm_model.mfa.builder import SimpleMetalCycleWithReman, run_flodym_mfa


def test_smoke_run_loose_coupled():
    years = list(range(2000, 2011))
    t = len(years)

    material = "tin"
    region = "EU27"
    end_uses = ["construction"]

    final_demand_t = np.linspace(100.0, 120.0, t)
    end_use_shares_te = np.ones((t, 1))

    # lifetime pdf: fixed retirement at age 3
    a = t
    lifetime_pdf = np.zeros((t, 1, 1, a))
    lifetime_pdf[:, :, :, 3] = 1.0

    primary_available = np.full((t, 1), 1e6)

    sd_params = {
        "start_year": years[0],
        "report_start_year": 2005,
        "report_years": list(range(2005, years[-1] + 1)),
        "price_base": 1.0,
        "price_scarcity_sensitivity": 0.5,
        "demand_price_elasticity": 0.1,
        "coupling_service_stress_gain": 5.0,
        "coupling_signal_smoothing": 0.5,
    }

    mfa_params = {
        "fabrication_yield": 0.95,
        "collection_rate": 0.4,
        "recycling_yield": 0.8,
        "reman_yield": 0.9,
        "lifetime_pdf_trea": lifetime_pdf,
        "primary_available_to_refining": primary_available,
    }

    res = run_loose_coupled(
        years=years,
        material=material,
        region=region,
        end_uses=end_uses,
        final_demand_t=final_demand_t,
        end_use_shares_te=end_use_shares_te,
        sd_params=sd_params,
        mfa_params=mfa_params,
        strategy={"recycling_yield": 0.8, "lifetime_multiplier": 1.0, "remanufacture_share": 0.0},
        shocks={},
        coupling={"max_iter": 2, "convergence_tol": 1e-6},
        service_level_threshold=0.95,
    )

    assert len(res.sd.demand) == t
    assert len(res.mfa.stock_in_use) == t
    assert "Service_level" in res.indicators_ts
    assert "Mass_balance_residual_max_abs" in res.indicators_ts
    assert "Coupling_service_stress" in res.indicators_ts
    assert "Coupling_circular_supply_stress" in res.indicators_ts
    assert "Coupling_strategic_stock_coverage_signal" in res.indicators_ts
    assert "Coupling_stress_multiplier" in res.indicators_ts
    assert "Collection_rate_effective" in res.indicators_ts
    assert "Coupling_collection_multiplier" in res.indicators_ts
    assert "SD_scarcity_multiplier_effective" in res.indicators_ts
    assert "SD_capacity_envelope" in res.indicators_ts
    assert "SD_flow_utilization" in res.indicators_ts
    assert "SD_bottleneck_pressure" in res.indicators_ts
    assert "SD_collection_bottleneck_throttle" in res.indicators_ts
    assert "final_service_stress_signal" in res.meta
    assert "final_circular_supply_stress_signal" in res.meta
    assert "final_strategic_stock_coverage_signal" in res.meta
    assert "final_stress_multiplier" in res.meta
    assert "final_scarcity_multiplier_effective_mean" in res.meta
    assert "final_capacity_envelope_mean" in res.meta
    assert "final_flow_utilization_mean" in res.meta
    assert "final_bottleneck_pressure_mean" in res.meta
    assert "final_collection_bottleneck_throttle_mean" in res.meta
    assert "coupling_converged" in res.meta
    assert "coupling_convergence_metric" in res.meta
    assert not res.coupling_signals_iter_year.empty
    assert not res.coupling_convergence_iter.empty
    assert len(res.coupling_signals_iter_year) == int(res.meta["iterations"]) * t
    assert int(res.coupling_convergence_iter["iteration"].max()) == int(res.meta["iterations"])
    assert (res.coupling_convergence_iter["max_signal_delta"] >= 0.0).all()
    assert np.allclose(
        res.coupling_signals_iter_year["service_stress_signal_target"]
        - res.coupling_signals_iter_year["service_stress_signal_next"],
        res.coupling_signals_iter_year["service_stress_residual_lag"],
        atol=1e-12,
    )


def test_smoke_run_loose_coupled_accepts_temporal_sd_parameters():
    years = [2000, 2001, 2002, 2003, 2004, 2005]
    t = len(years)

    final_demand_t = np.linspace(90.0, 120.0, t)
    end_use_shares_te = np.ones((t, 1), dtype=float)
    lifetime_pdf = np.zeros((t, 1, 1, t), dtype=float)
    lifetime_pdf[:, :, :, 2] = 1.0

    sd_params = {
        "start_year": years[0],
        "report_start_year": 2002,
        "report_years": list(range(2002, years[-1] + 1)),
        "price_base": [1.0, 1.0, 1.05, 1.1, 1.1, 1.1],
        "price_scarcity_sensitivity": 0.6,
        "demand_price_elasticity": {"start_year": 2002, "value": 0.08, "before": 0.0},
        "coupling_service_stress_gain": [4.0, 4.0, 4.5, 5.0, 5.0, 5.0],
        "coupling_circular_supply_stress_gain": 1.0,
        "coupling_signal_smoothing": [0.5, 0.5, 0.55, 0.6, 0.6, 0.6],
        "capacity_expansion_gain": {"start_year": 2003, "value": 0.3, "before": 0.2},
        "bottleneck_scarcity_gain": [0.1, 0.1, 0.12, 0.15, 0.15, 0.15],
    }
    mfa_params = {
        "fabrication_yield": 0.95,
        "collection_rate": 0.4,
        "recycling_yield": 0.8,
        "reman_yield": 0.9,
        "lifetime_pdf_trea": lifetime_pdf,
        "primary_available_to_refining": np.full((t, 1), 1e6, dtype=float),
    }

    res = run_loose_coupled(
        years=years,
        material="nickel",
        region="EU27",
        end_uses=["construction"],
        final_demand_t=final_demand_t,
        end_use_shares_te=end_use_shares_te,
        sd_params=sd_params,
        mfa_params=mfa_params,
        strategy={"recycling_yield": 0.8, "lifetime_multiplier": 1.0, "remanufacture_share": 0.0},
        shocks={},
        coupling={"max_iter": 2, "convergence_tol": 1e-6},
        service_level_threshold=0.95,
    )

    assert len(res.sd.demand) == t
    assert "SD_bottleneck_pressure" in res.indicators_ts
    assert "final_stress_multiplier" in res.meta


def test_scalar_vs_constant_temporal_sd_parameters_have_tight_drift():
    years = [2000, 2001, 2002, 2003, 2004]
    t = len(years)
    final_demand_t = np.linspace(100.0, 120.0, t)
    end_use_shares_te = np.ones((t, 1), dtype=float)
    lifetime_pdf = np.zeros((t, 1, 1, t), dtype=float)
    lifetime_pdf[:, :, :, 2] = 1.0
    mfa_params = {
        "fabrication_yield": 0.95,
        "collection_rate": 0.4,
        "recycling_yield": 0.8,
        "reman_yield": 0.9,
        "lifetime_pdf_trea": lifetime_pdf,
        "primary_available_to_refining": np.full((t, 1), 1e6, dtype=float),
    }
    strategy = {"recycling_yield": 0.8, "lifetime_multiplier": 1.0, "remanufacture_share": 0.0}

    sd_scalar = {
        "start_year": years[0],
        "report_start_year": years[0],
        "report_years": years,
        "price_base": 1.0,
        "price_scarcity_sensitivity": 0.55,
        "demand_price_elasticity": 0.1,
        "coupling_service_stress_gain": 5.0,
        "coupling_circular_supply_stress_gain": 1.0,
        "coupling_signal_smoothing": 0.5,
        "capacity_expansion_gain": 0.26,
        "capacity_adjustment_lag_years": 4.5,
        "capacity_pressure_shortage_weight": 0.78,
        "bottleneck_scarcity_gain": 0.15,
        "bottleneck_collection_sensitivity": 0.08,
    }
    sd_temporal = {
        **sd_scalar,
        "price_base": [1.0] * t,
        "price_scarcity_sensitivity": [0.55] * t,
        "demand_price_elasticity": [0.1] * t,
        "coupling_service_stress_gain": [5.0] * t,
        "coupling_circular_supply_stress_gain": [1.0] * t,
        "coupling_signal_smoothing": [0.5] * t,
        "capacity_expansion_gain": [0.26] * t,
        "capacity_adjustment_lag_years": [4.5] * t,
        "capacity_pressure_shortage_weight": [0.78] * t,
        "bottleneck_scarcity_gain": [0.15] * t,
        "bottleneck_collection_sensitivity": [0.08] * t,
    }

    scalar_res = run_loose_coupled(
        years=years,
        material="tin",
        region="EU27",
        end_uses=["construction"],
        final_demand_t=final_demand_t,
        end_use_shares_te=end_use_shares_te,
        sd_params=sd_scalar,
        mfa_params=mfa_params,
        strategy=strategy,
        shocks={},
        coupling={"max_iter": 2, "convergence_tol": 1e-6},
        service_level_threshold=0.95,
    )
    temporal_res = run_loose_coupled(
        years=years,
        material="tin",
        region="EU27",
        end_uses=["construction"],
        final_demand_t=final_demand_t,
        end_use_shares_te=end_use_shares_te,
        sd_params=sd_temporal,
        mfa_params=mfa_params,
        strategy=strategy,
        shocks={},
        coupling={"max_iter": 2, "convergence_tol": 1e-6},
        service_level_threshold=0.95,
    )

    assert np.isclose(
        scalar_res.meta["final_stress_multiplier"],
        temporal_res.meta["final_stress_multiplier"],
        rtol=0.10,
        atol=1e-12,
    )


def test_invalid_collection_routing_rates_fail_fast():
    years = [2000, 2001, 2002, 2003]
    t = len(years)

    service_demand_tre = np.full((t, 1, 1), 100.0, dtype=float)
    lifetime_pdf = np.zeros((t, 1, 1, t), dtype=float)
    lifetime_pdf[:, :, :, 1] = 1.0

    with pytest.raises(ValueError, match="recycling_rate \\+ remanufacturing_rate \\+ disposal_rate must equal 1.0"):
        run_flodym_mfa(
            years=years,
            regions=["EU27"],
            end_uses=["construction"],
            service_demand_tre=service_demand_tre,
            params={
                "lifetime_pdf_trea": lifetime_pdf,
                "primary_available_to_refining": np.full((t, 1), 1.0e6, dtype=float),
            },
            strategy={
                "recycling_rate": 0.8,
                "remanufacturing_rate": 0.4,
                "disposal_rate": 0.0,
            },
        )


def test_coupling_feedback_modes_time_series_vs_scalar_mean():
    years = [2000, 2001, 2002, 2003, 2004]
    t = len(years)
    final_demand_t = np.array([80.0, 120.0, 150.0, 110.0, 90.0], dtype=float)
    end_use_shares_te = np.ones((t, 1), dtype=float)

    lifetime_pdf = np.zeros((t, 1, 1, t), dtype=float)
    lifetime_pdf[:, :, :, 1] = 1.0
    primary_available = np.full((t, 1), 70.0, dtype=float)

    sd_params = {
        "start_year": years[0],
        "demand_response_start_year": years[0],
        "report_start_year": years[0],
        "report_years": years,
        "price_base": 1.0,
        "price_scarcity_sensitivity": 0.7,
        "demand_price_elasticity": 0.0,
        "coupling_service_stress_gain": 4.0,
        "coupling_circular_supply_stress_gain": 1.0,
        "coupling_signal_smoothing": 0.8,
    }
    mfa_params = {
        "fabrication_yield": 1.0,
        "collection_rate": 0.2,
        "recycling_yield": 1.0,
        "reman_yield": 1.0,
        "lifetime_pdf_trea": lifetime_pdf,
        "primary_available_to_refining": primary_available,
    }
    strategy = {
        "recycling_rate": 1.0,
        "remanufacturing_rate": 0.0,
        "disposal_rate": 0.0,
        "refinery_stockpile_release_rate": 1.0,
    }

    res_ts = run_loose_coupled(
        years=years,
        material="nickel",
        region="EU27",
        end_uses=["construction"],
        final_demand_t=final_demand_t,
        end_use_shares_te=end_use_shares_te,
        sd_params=sd_params,
        mfa_params=mfa_params,
        strategy=strategy,
        shocks={},
        coupling={
            "max_iter": 3,
            "convergence_tol": 1e-6,
            "feedback_signal_mode": "time_series",
            "feedback_on_report_years_only": False,
        },
        service_level_threshold=0.95,
    )
    res_scalar = run_loose_coupled(
        years=years,
        material="nickel",
        region="EU27",
        end_uses=["construction"],
        final_demand_t=final_demand_t,
        end_use_shares_te=end_use_shares_te,
        sd_params=sd_params,
        mfa_params=mfa_params,
        strategy=strategy,
        shocks={},
        coupling={
            "max_iter": 3,
            "convergence_tol": 1e-6,
            "feedback_signal_mode": "scalar_mean",
            "feedback_on_report_years_only": False,
        },
        service_level_threshold=0.95,
    )

    ts_mult = res_ts.indicators_ts["Coupling_stress_multiplier"].values
    scalar_mult = res_scalar.indicators_ts["Coupling_stress_multiplier"].values

    assert np.max(ts_mult) - np.min(ts_mult) > 1e-8
    assert np.allclose(scalar_mult, np.full_like(scalar_mult, scalar_mult[0]), atol=1e-12)
    assert np.isclose(res_scalar.meta["final_stress_multiplier"], float(np.mean(scalar_mult)), atol=1e-12)


def test_remanufacturing_is_end_use_gated():
    years = [2000, 2001, 2002]
    t = len(years)

    service_demand_tre = np.full((t, 1, 2), 100.0, dtype=float)
    lifetime_pdf = np.zeros((t, 1, 2, t), dtype=float)
    lifetime_pdf[:, :, :, 1] = 1.0

    eligibility = np.zeros((t, 1, 2), dtype=float)
    eligibility[:, :, 1] = 1.0  # second end-use eligible, first not eligible

    mfa, _ = run_flodym_mfa(
        years=years,
        regions=["EU27"],
        end_uses=["construction", "machinery_and_equipment"],
        service_demand_tre=service_demand_tre,
        params={
            "lifetime_pdf_trea": lifetime_pdf,
            "primary_available_to_refining": np.full((t, 1), 1.0e6, dtype=float),
            "remanufacturing_end_use_eligibility_tre": eligibility,
        },
        strategy={
            "recycling_rate": 0.4,
            "remanufacturing_rate": 0.4,
            "disposal_rate": 0.2,
            "recycling_yield": 1.0,
            "reman_yield": 1.0,
        },
    )

    col_to_rem = mfa.flows["collection => remanufacture"].values
    col_to_rec = mfa.flows["collection => recycling"].values
    col_to_disp = mfa.flows["collection => disposal"].values
    eol_to_col = mfa.flows["end_of_life => collection"].values

    # Ineligible end-use gets no reman routing.
    assert np.allclose(col_to_rem[:, 0, 0], 0.0, atol=1e-12)
    # Eligible end-use keeps positive reman routing once cohorts retire.
    assert float(np.max(col_to_rem[:, 0, 1])) > 0.0
    # Flow conservation still holds on ineligible stream via recycling/disposal.
    assert np.allclose(
        col_to_rec[:, 0, 0] + col_to_disp[:, 0, 0],
        eol_to_col[:, 0, 0],
        atol=1e-12,
    )


def test_refinery_stockpile_accumulates_and_releases():
    years = [2000, 2001, 2002]
    t = len(years)

    service_demand_tre = np.array([[[100.0]], [[10.0]], [[80.0]]], dtype=float)
    lifetime_pdf = np.zeros((t, 1, 1, t), dtype=float)
    lifetime_pdf[:, :, :, 1] = 1.0

    _, ts = run_flodym_mfa(
        years=years,
        regions=["EU27"],
        end_uses=["construction"],
        service_demand_tre=service_demand_tre,
        params={
            "lifetime_pdf_trea": lifetime_pdf,
            "primary_available_to_refining": np.full((t, 1), 1.0e6, dtype=float),
            "fabrication_yield": 1.0,
            "collection_rate": 1.0,
            "recycling_yield": 1.0,
            "reman_yield": 1.0,
        },
        strategy={
            "recycling_rate": 1.0,
            "remanufacturing_rate": 0.0,
            "disposal_rate": 0.0,
            "refinery_stockpile_release_rate": 1.0,
        },
    )

    assert float(ts.refinery_stockpile_stock.loc[2001]) > 0.0
    assert float(ts.refinery_stockpile_outflow.loc[2002]) > 0.0
    assert np.allclose(ts.recycling_surplus_unused.values, 0.0, atol=1e-12)


def test_remanufacturing_no_longer_uses_native_buffer_stock():
    years = [2000, 2001, 2002]
    t = len(years)

    service_demand_tre = np.array([[[100.0]], [[10.0]], [[80.0]]], dtype=float)
    lifetime_pdf = np.zeros((t, 1, 1, t), dtype=float)
    lifetime_pdf[:, :, :, 1] = 1.0

    _, ts = run_flodym_mfa(
        years=years,
        regions=["EU27"],
        end_uses=["construction"],
        service_demand_tre=service_demand_tre,
        params={
            "lifetime_pdf_trea": lifetime_pdf,
            "primary_available_to_refining": np.full((t, 1), 1.0e6, dtype=float),
            "fabrication_yield": 1.0,
            "collection_rate": 1.0,
            "recycling_yield": 1.0,
            "reman_yield": 1.0,
        },
        strategy={
            "recycling_rate": 0.0,
            "remanufacturing_rate": 1.0,
            "disposal_rate": 0.0,
            "refinery_stockpile_release_rate": 1.0,
        },
    )

    assert np.all(ts.remanufacture_surplus_unused.values >= -1e-12)
    assert float(ts.inflow_to_use_reman.loc[2002]) > 0.0


def test_native_stocks_are_materialized_and_track_flows():
    years = [2000, 2001, 2002, 2003]
    t = len(years)
    service_demand_tre = np.array([[[100.0]], [[20.0]], [[120.0]], [[50.0]]], dtype=float)
    lifetime_pdf = np.zeros((t, 1, 1, t), dtype=float)
    lifetime_pdf[:, :, :, 1] = 1.0

    params = {
        "lifetime_pdf_trea": lifetime_pdf,
        "primary_available_to_refining": np.full((t, 1), 1.0e6, dtype=float),
        "fabrication_yield": 1.0,
        "collection_rate": 1.0,
        "recycling_yield": 1.0,
        "reman_yield": 1.0,
    }
    strategy = {
        "recycling_rate": 0.6,
        "remanufacturing_rate": 0.4,
        "disposal_rate": 0.0,
        "refinery_stockpile_release_rate": 0.75,
    }

    mfa, ts = run_flodym_mfa(
        years=years,
        regions=["EU27"],
        end_uses=["construction"],
        service_demand_tre=service_demand_tre,
        params=params,
        strategy=strategy,
    )

    assert SimpleMetalCycleWithReman.REFINERY_STOCKPILE_STOCK_NAME in mfa.stocks
    assert np.all(ts.refinery_stockpile_stock.values >= -1e-12)
    assert np.allclose(ts.recycling_surplus_unused.values, 0.0, atol=1e-12)
    assert np.all(ts.remanufacture_surplus_unused.values >= -1e-12)
    assert np.allclose(ts.new_scrap_generated.values, ts.fabrication_losses.values, atol=1e-12)
    assert np.allclose(ts.old_scrap_generated.values, ts.outflow_from_use.values, atol=1e-12)


def test_sd_endogenous_collection_changes_effective_collection_rate():
    years = list(range(2000, 2008))
    t = len(years)

    res = run_loose_coupled(
        years=years,
        material="tin",
        region="EU27",
        end_uses=["construction"],
        final_demand_t=np.full(t, 100.0, dtype=float),
        end_use_shares_te=np.ones((t, 1), dtype=float),
        sd_params={
            "start_year": years[0],
            "report_start_year": 2000,
            "report_years": years,
            "price_base": 1.0,
            "price_scarcity_sensitivity": 1.2,
            "demand_price_elasticity": 0.0,
            "coupling_service_stress_gain": 8.0,
            "coupling_circular_supply_stress_gain": 0.0,
            "coupling_signal_smoothing": 1.0,
            "collection_price_response_gain": 0.6,
            "collection_multiplier_min": 0.8,
            "collection_multiplier_max": 1.6,
            "collection_multiplier_lag_years": 1.0,
        },
        mfa_params={
            "fabrication_yield": 1.0,
            "collection_rate": 0.4,
            "recycling_yield": 1.0,
            "reman_yield": 1.0,
            "lifetime_pdf_trea": np.where(
                np.arange(t)[None, None, None, :] == 1,
                1.0,
                0.0,
            ).repeat(t, axis=0),
            "primary_available_to_refining": np.full((t, 1), 5.0, dtype=float),
        },
        strategy={
            "recycling_rate": 1.0,
            "remanufacturing_rate": 0.0,
            "disposal_rate": 0.0,
        },
        shocks={},
        coupling={"max_iter": 3, "convergence_tol": 1e-6},
        service_level_threshold=0.95,
    )

    trace = res.coupling_signals_iter_year
    final_iter = int(res.meta["iterations"])
    final_trace = trace[trace["iteration"] == final_iter].sort_values("year")
    assert "collection_rate_effective" in final_trace.columns
    assert "collection_multiplier_next" in final_trace.columns
    assert float(final_trace["collection_multiplier_next"].max()) > 1.0
    assert float(final_trace["collection_rate_effective"].max()) > 0.4


def test_strategic_reserve_fill_and_release_changes_unmet_service_profile():
    years = [2000, 2001, 2002, 2003]
    t = len(years)
    service_demand_tre = np.array([[[20.0]], [[20.0]], [[40.0]], [[40.0]]], dtype=float)
    lifetime_pdf = np.zeros((t, 1, 1, t), dtype=float)
    lifetime_pdf[:, :, :, min(3, t - 1)] = 1.0

    common_params = {
        "lifetime_pdf_trea": lifetime_pdf,
        "primary_available_to_refining": np.full((t, 1), 20.0, dtype=float),
        "fabrication_yield": 1.0,
        "collection_rate": 0.0,
        "recycling_yield": 1.0,
        "reman_yield": 1.0,
    }
    common_strategy = {
        "recycling_rate": 1.0,
        "remanufacturing_rate": 0.0,
        "disposal_rate": 0.0,
        "refinery_stockpile_release_rate": 0.0,
    }

    _, ts_off = run_flodym_mfa(
        years=years,
        regions=["EU27"],
        end_uses=["construction"],
        service_demand_tre=service_demand_tre,
        params=common_params,
        strategy={**common_strategy, "strategic_reserve_enabled": False},
    )
    _, ts_on = run_flodym_mfa(
        years=years,
        regions=["EU27"],
        end_uses=["construction"],
        service_demand_tre=service_demand_tre,
        params={
            **common_params,
            "strategic_fill_intent": np.array([1.0, 1.0, 0.0, 0.0], dtype=float),
            "strategic_release_intent": np.array([0.0, 0.0, 1.0, 1.0], dtype=float),
        },
        strategy={**common_strategy, "strategic_reserve_enabled": True},
    )

    assert float(ts_on.unmet_service.loc[2000]) > float(ts_off.unmet_service.loc[2000])
    assert float(ts_on.unmet_service.loc[2001]) > float(ts_off.unmet_service.loc[2001])
    assert float(ts_on.unmet_service.loc[2002]) < float(ts_off.unmet_service.loc[2002])
    assert float(ts_on.unmet_service.loc[2003]) < float(ts_off.unmet_service.loc[2003])
    assert float(ts_on.strategic_inventory_stock.max()) > 0.0
    assert float(ts_on.strategic_inventory_outflow.loc[2002]) > 0.0
