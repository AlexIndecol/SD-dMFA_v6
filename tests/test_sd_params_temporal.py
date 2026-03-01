from __future__ import annotations

import numpy as np
import pytest

from crm_model.sd.params import (
    expand_temporal_value,
    inject_gate_before,
    migrate_legacy_strategy_sd_controls,
    normalize_and_validate_sd_parameters,
    validate_sd_parameter_ranges,
)


def test_expand_temporal_value_supports_scalar_gate_and_series():
    years = [2020, 2021, 2022, 2023]

    scalar = expand_temporal_value(0.3, years=years, name="sd_parameters.capacity_expansion_gain")
    assert np.allclose(scalar, np.array([0.3, 0.3, 0.3, 0.3], dtype=float))

    gate = expand_temporal_value(
        {"start_year": 2022, "value": 0.4, "before": 0.2},
        years=years,
        name="sd_parameters.capacity_expansion_gain",
    )
    assert np.allclose(gate, np.array([0.2, 0.2, 0.4, 0.4], dtype=float))

    series = expand_temporal_value(
        [0.1, 0.2, 0.3, 0.4],
        years=years,
        name="sd_parameters.coupling_signal_smoothing",
    )
    assert np.allclose(series, np.array([0.1, 0.2, 0.3, 0.4], dtype=float))

    ramp = expand_temporal_value(
        {
            "points": {
                2020: 0.10,
                2022: 0.30,
                2023: 0.40,
            },
            "before": 0.05,
        },
        years=years,
        name="sd_parameters.capacity_expansion_gain",
    )
    assert np.allclose(ramp, np.array([0.10, 0.20, 0.30, 0.40], dtype=float))


def test_inject_gate_before_adds_before_when_missing():
    gate = {"start_year": 2025, "value": 0.34}
    injected = inject_gate_before(gate, 0.26)
    assert injected["before"] == 0.26
    assert injected["start_year"] == 2025
    assert injected["value"] == 0.34


def test_expand_temporal_value_length_mismatch_fails():
    years = [2020, 2021, 2022]
    with pytest.raises(ValueError, match="must have length 3; got 2"):
        expand_temporal_value(
            [0.1, 0.2],
            years=years,
            name="sd_parameters.coupling_signal_smoothing",
        )


def test_historic_gate_emits_deprecation_warning():
    years = [2020, 2021, 2022]
    with pytest.warns(DeprecationWarning, match="before report_start_year"):
        expand_temporal_value(
            {"start_year": 2019, "value": 0.34, "before": 0.26},
            years=years,
            name="sd_parameters.capacity_expansion_gain",
            report_start_year=2020,
            emit_warnings=True,
            context="test",
        )


def test_validate_sd_parameter_ranges_enforces_pair_constraints_elementwise():
    years = [2020, 2021, 2022]
    with pytest.raises(ValueError, match="collection_multiplier_min must be <= collection_multiplier_max"):
        validate_sd_parameter_ranges(
            {
                "collection_multiplier_min": [0.9, 0.9, 0.9],
                "collection_multiplier_max": [0.8, 1.0, 1.0],
            },
            years=years,
        )


def test_normalize_and_validate_sd_parameters_accepts_temporal_sd_inputs():
    years = [2020, 2021, 2022]
    out = normalize_and_validate_sd_parameters(
        {
            "price_base": {"start_year": 2021, "value": 1.1, "before": 1.0},
            "capacity_envelope_min": [0.8, 0.8, 0.85],
            "capacity_envelope_max": [1.2, 1.2, 1.25],
        },
        years=years,
        report_start_year=2020,
        emit_warnings=True,
        context="test",
    )
    assert "price_base" in out
    assert "capacity_envelope_min" in out
    assert "capacity_envelope_max" in out


def test_legacy_sd_aliases_fail_fast():
    with pytest.raises(ValueError, match="no longer supported"):
        normalize_and_validate_sd_parameters({"base_price": 1.0})


def test_legacy_strategy_collection_controls_fail_fast():
    with pytest.raises(ValueError, match="no longer supported"):
        migrate_legacy_strategy_sd_controls(
            sd_parameters={"price_base": 1.0},
            strategy={"collection_multiplier_min": 0.8},
        )
