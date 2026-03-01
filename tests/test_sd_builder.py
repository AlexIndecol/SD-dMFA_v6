from __future__ import annotations

import numpy as np

from crm_model.sd.builder import run_bptk_sd


def test_bptk_sd_exposes_collection_multipliers_without_lag():
    years = [2000, 2001, 2002, 2003]
    ts = run_bptk_sd(
        years=years,
        params={
            "demand_exogenous": [100.0, 100.0, 100.0, 100.0],
            "start_year": 2000,
            "demand_response_start_year": 2000,
            "price_base": 1.0,
            "scarcity_multiplier": 2.0,
            "price_scarcity_sensitivity": 1.0,
            "demand_price_elasticity": 0.0,
            "collection_price_response_gain": 0.5,
            "collection_multiplier_min": 0.8,
            "collection_multiplier_max": 1.6,
            "collection_multiplier_lag_years": 0.0,
        },
    )

    assert np.allclose(ts.collection_multiplier_target.values, 1.5, atol=1e-12)
    assert np.allclose(ts.collection_multiplier.values, 1.5, atol=1e-12)


def test_bptk_sd_collection_multiplier_lag_smooths_target():
    years = [2000, 2001, 2002, 2003, 2004]
    ts = run_bptk_sd(
        years=years,
        params={
            "demand_exogenous": [100.0] * len(years),
            "start_year": 2000,
            "demand_response_start_year": 2000,
            "price_base": 1.0,
            "scarcity_multiplier": 2.0,
            "price_scarcity_sensitivity": 1.0,
            "demand_price_elasticity": 0.0,
            "collection_price_response_gain": 0.5,
            "collection_multiplier_min": 0.8,
            "collection_multiplier_max": 1.6,
            "collection_multiplier_lag_years": 2.0,
        },
    )

    target = ts.collection_multiplier_target.values
    applied = ts.collection_multiplier.values

    assert np.allclose(target, 1.5, atol=1e-12)
    assert np.all(applied <= target + 1e-12)
    assert float(applied[-1]) > float(applied[0])


def test_bptk_sd_collection_shock_window_without_lag():
    years = [2000, 2001, 2002, 2003, 2004]
    ts = run_bptk_sd(
        years=years,
        params={
            "demand_exogenous": [100.0] * len(years),
            "start_year": 2000,
            "demand_response_start_year": 2000,
            "price_base": 1.0,
            "scarcity_multiplier": 1.0,
            "price_scarcity_sensitivity": 1.0,
            "demand_price_elasticity": 0.0,
            "collection_price_response_gain": 0.0,
            "collection_shock_start": 1.0,
            "collection_shock_duration": 2.0,
            "collection_shock_multiplier": 1.3,
            "collection_multiplier_min": 0.5,
            "collection_multiplier_max": 2.0,
            "collection_multiplier_lag_years": 0.0,
        },
    )

    expected = np.array([1.0, 1.3, 1.3, 1.0, 1.0], dtype=float)
    assert np.allclose(ts.collection_multiplier_target.values, expected, atol=1e-12)
    assert np.allclose(ts.collection_multiplier.values, expected, atol=1e-12)


def test_bptk_sd_collection_shock_is_lagged_when_enabled():
    years = [2000, 2001, 2002, 2003, 2004]
    ts = run_bptk_sd(
        years=years,
        params={
            "demand_exogenous": [100.0] * len(years),
            "start_year": 2000,
            "demand_response_start_year": 2000,
            "price_base": 1.0,
            "scarcity_multiplier": 1.0,
            "price_scarcity_sensitivity": 1.0,
            "demand_price_elasticity": 0.0,
            "collection_price_response_gain": 0.0,
            "collection_shock_start": 1.0,
            "collection_shock_duration": 3.0,
            "collection_shock_multiplier": 2.0,
            "collection_multiplier_min": 0.5,
            "collection_multiplier_max": 2.0,
            "collection_multiplier_lag_years": 2.0,
        },
    )

    target = ts.collection_multiplier_target.values
    applied = ts.collection_multiplier.values
    assert np.allclose(target, np.array([1.0, 2.0, 2.0, 2.0, 1.0]), atol=1e-12)
    assert np.isclose(float(applied[1]), 1.0, atol=1e-12)
    assert 1.0 < float(applied[2]) < 2.0
    assert float(applied[3]) > float(applied[2])
    assert np.all(applied <= 2.0 + 1e-12)


def test_bptk_sd_accepts_time_varying_scarcity_multiplier():
    years = [2000, 2001, 2002, 2003]
    scarcity = [1.0, 1.2, 1.5, 0.9]
    ts = run_bptk_sd(
        years=years,
        params={
            "demand_exogenous": [100.0] * len(years),
            "start_year": 2000,
            "demand_response_start_year": 2000,
            "price_base": 1.0,
            "scarcity_multiplier": scarcity,
            "price_scarcity_sensitivity": 0.5,
            "demand_price_elasticity": 0.0,
            "collection_price_response_gain": 0.0,
            "collection_multiplier_lag_years": 0.0,
        },
    )

    expected_price = np.array([1.0 + 0.5 * (v - 1.0) for v in scarcity], dtype=float)
    assert np.allclose(ts.scarcity_multiplier.values, np.array(scarcity, dtype=float), atol=1e-12)
    assert np.allclose(ts.price.values, expected_price, atol=1e-12)


def test_bptk_sd_strategic_intents_switch_between_fill_and_release():
    years = [2000, 2001, 2002, 2003]
    ts = run_bptk_sd(
        years=years,
        params={
            "demand_exogenous": [100.0] * len(years),
            "start_year": 2000,
            "demand_response_start_year": 2000,
            "price_base": 1.0,
            "scarcity_multiplier": [0.9, 0.95, 1.3, 1.35],
            "service_stress_signal": [0.02, 0.03, 0.2, 0.25],
            "strategic_stock_coverage_years": [0.1, 0.2, 0.5, 0.4],
            "price_scarcity_sensitivity": 1.0,
            "demand_price_elasticity": 0.0,
            "strategic_reserve_enabled": True,
            "strategic_reserve_target_coverage_years": 0.8,
            "strategic_reserve_fill_gain": 1.0,
            "strategic_reserve_release_gain": 1.0,
            "strategic_reserve_max_fill_rate": 0.3,
            "strategic_reserve_max_release_rate": 0.4,
            "strategic_reserve_fill_price_threshold": 1.0,
            "strategic_reserve_release_price_threshold": 1.1,
            "strategic_reserve_fill_service_threshold": 0.05,
            "strategic_reserve_release_service_threshold": 0.12,
        },
    )

    assert float(ts.strategic_fill_intent.iloc[0]) > 0.0
    assert float(ts.strategic_fill_intent.iloc[1]) > 0.0
    assert np.isclose(float(ts.strategic_fill_intent.iloc[2]), 0.0, atol=1e-12)
    assert np.isclose(float(ts.strategic_fill_intent.iloc[3]), 0.0, atol=1e-12)
    assert np.isclose(float(ts.strategic_release_intent.iloc[0]), 0.0, atol=1e-12)
    assert np.isclose(float(ts.strategic_release_intent.iloc[1]), 0.0, atol=1e-12)
    assert float(ts.strategic_release_intent.iloc[2]) > 0.0
    assert float(ts.strategic_release_intent.iloc[3]) > 0.0


def test_bptk_sd_capacity_envelope_expands_under_bottleneck_pressure():
    years = [2000, 2001, 2002, 2003, 2004, 2005]
    ts = run_bptk_sd(
        years=years,
        params={
            "demand_exogenous": [100.0] * len(years),
            "start_year": 2000,
            "demand_response_start_year": 2000,
            "price_base": 1.0,
            "price_scarcity_sensitivity": 1.0,
            "demand_price_elasticity": 0.0,
            "scarcity_multiplier": 1.0,
            "capacity_envelope_initial": 0.75,
            "capacity_envelope_min": 0.6,
            "capacity_envelope_max": 1.8,
            "capacity_expansion_gain": 0.8,
            "capacity_retirement_gain": 0.0,
            "capacity_adjustment_lag_years": 1.5,
            "capacity_pressure_shortage_weight": 1.0,
            "bottleneck_scarcity_gain": 1.0,
            "bottleneck_collection_sensitivity": 0.5,
            "collection_price_response_gain": 0.3,
            "collection_multiplier_min": 0.5,
            "collection_multiplier_max": 3.0,
            "collection_multiplier_lag_years": 0.0,
        },
    )

    assert float(ts.flow_utilization.iloc[0]) > 1.0
    assert float(ts.bottleneck_pressure.iloc[0]) > 0.0
    assert float(ts.price.iloc[0]) > 1.0
    assert float(ts.capacity_envelope.iloc[-1]) > float(ts.capacity_envelope.iloc[0])


def test_bptk_sd_collection_bottleneck_throttle_damps_multiplier_target():
    years = [2000, 2001, 2002, 2003]
    base_params = {
        "demand_exogenous": [100.0] * len(years),
        "start_year": 2000,
        "demand_response_start_year": 2000,
        "price_base": 1.0,
        "price_scarcity_sensitivity": 1.0,
        "demand_price_elasticity": 0.0,
        "scarcity_multiplier": 1.0,
        "capacity_envelope_initial": 0.7,
        "capacity_envelope_min": 0.6,
        "capacity_envelope_max": 1.2,
        "capacity_expansion_gain": 0.0,
        "capacity_retirement_gain": 0.0,
        "capacity_adjustment_lag_years": 1.0,
        "capacity_pressure_shortage_weight": 1.0,
        "bottleneck_scarcity_gain": 1.0,
        "collection_price_response_gain": 0.6,
        "collection_multiplier_min": 0.5,
        "collection_multiplier_max": 3.0,
        "collection_multiplier_lag_years": 0.0,
    }
    ts_no_throttle = run_bptk_sd(
        years=years,
        params={**base_params, "bottleneck_collection_sensitivity": 0.0},
    )
    ts_with_throttle = run_bptk_sd(
        years=years,
        params={**base_params, "bottleneck_collection_sensitivity": 2.0},
    )

    assert float(ts_with_throttle.collection_bottleneck_throttle.iloc[0]) < 1.0
    assert float(ts_with_throttle.collection_multiplier_target.iloc[0]) < float(
        ts_no_throttle.collection_multiplier_target.iloc[0]
    )


def test_bptk_sd_crunch_recovery_profile_peaks_then_relaxes():
    years = list(range(2000, 2015))
    ts = run_bptk_sd(
        years=years,
        params={
            "demand_exogenous": [100.0] * len(years),
            "start_year": years[0],
            "demand_response_start_year": years[0],
            "price_base": 1.0,
            "price_scarcity_sensitivity": 1.0,
            "demand_price_elasticity": 0.0,
            "scarcity_multiplier": 1.0,
            "capacity_envelope_initial": 0.8,
            "capacity_envelope_min": 0.7,
            "capacity_envelope_max": 1.6,
            "capacity_expansion_gain": 0.35,
            "capacity_retirement_gain": 0.0,
            "capacity_adjustment_lag_years": 2.0,
            "capacity_pressure_shortage_weight": 1.0,
            "bottleneck_scarcity_gain": 0.5,
            "bottleneck_collection_sensitivity": 0.2,
            "collection_price_response_gain": 0.0,
            "collection_multiplier_min": 0.5,
            "collection_multiplier_max": 2.0,
            "collection_multiplier_lag_years": 0.0,
            "demand_surge_start": 2.0,
            "demand_surge_duration": 6.0,
            "demand_surge_multiplier": 1.6,
        },
    )

    stress_years = list(range(2002, 2008))
    post_years = list(range(2009, 2015))

    stress_mean = float(ts.bottleneck_pressure.loc[stress_years].mean())
    post_mean = float(ts.bottleneck_pressure.loc[post_years].mean())
    assert stress_mean > post_mean
    assert float(ts.capacity_envelope.iloc[-1]) > float(ts.capacity_envelope.iloc[0])

    peak_year = int(ts.price.idxmax())
    assert peak_year in set(range(2002, 2009))


def test_bptk_sd_time_varying_capacity_and_price_parameters_change_trajectory():
    years = [2000, 2001, 2002, 2003, 2004]
    base_params = {
        "demand_exogenous": [100.0] * len(years),
        "start_year": 2000,
        "demand_response_start_year": 2000,
        "scarcity_multiplier": 1.0,
        "capacity_envelope_initial": 0.75,
        "capacity_envelope_min": 0.7,
        "capacity_envelope_max": 1.8,
        "capacity_retirement_gain": 0.0,
        "capacity_adjustment_lag_years": 1.0,
        "capacity_pressure_shortage_weight": 1.0,
        "bottleneck_scarcity_gain": 1.0,
        "bottleneck_collection_sensitivity": 0.0,
        "collection_price_response_gain": 0.0,
        "collection_multiplier_min": 0.5,
        "collection_multiplier_max": 2.0,
        "collection_multiplier_lag_years": 0.0,
    }

    ts_scalar = run_bptk_sd(
        years=years,
        params={
            **base_params,
            "price_base": 1.0,
            "price_scarcity_sensitivity": 1.0,
            "demand_price_elasticity": 0.0,
            "capacity_expansion_gain": 0.15,
        },
    )
    ts_temporal = run_bptk_sd(
        years=years,
        params={
            **base_params,
            "price_base": [1.0, 1.0, 1.1, 1.2, 1.2],
            "price_scarcity_sensitivity": [1.0, 1.0, 1.1, 1.2, 1.2],
            "demand_price_elasticity": [0.0, 0.0, 0.0, 0.0, 0.0],
            "capacity_expansion_gain": [0.15, 0.20, 0.30, 0.30, 0.30],
        },
    )

    assert not np.allclose(ts_scalar.price.values, ts_temporal.price.values)
