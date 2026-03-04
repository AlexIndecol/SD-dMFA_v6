from __future__ import annotations

import numpy as np
from types import SimpleNamespace
from pathlib import Path

from crm_model.config.models import ScenarioDimensionOverride, ShockEvent, ShocksConfig, VariantConfig
from crm_model.scenario_profiles import build_variant_payload_from_profiles, load_reporting_profile_csv
from crm_model.cli import (
    _apply_profile_payload_to_slice,
    _enforce_reporting_phase_for_variant_slice,
    _resolve_exogenous_ramps_for_variant_slice,
)
from crm_model.config.io import load_run_config
from crm_model.coupling.runner import run_loose_coupled
from crm_model.scenarios import (
    _as_timeseries,
    apply_routing_rate_shocks,
    deep_update,
    inject_gate_baselines,
    resolve_sd_parameters_for_slice,
    resolve_variant_slice_overrides,
)


def test_dimension_scoped_variant_overrides_apply_only_to_matching_slice():
    cfg = SimpleNamespace(
        variants={
            "recycling_disruption": VariantConfig(
                dimension_overrides=[
                    ScenarioDimensionOverride(
                        materials=["nickel"],
                        regions=["EU27"],
                        shocks=ShocksConfig(
                            trade_refined_import_need_multiplier=ShockEvent(
                                start_year=2025,
                                duration_years=20,
                                multiplier=0.7,
                            ),
                            collection_rate=ShockEvent(
                                start_year=2025,
                                duration_years=20,
                                multiplier=0.95,
                            ),
                        ),
                    )
                ]
            )
        }
    )

    hit = resolve_variant_slice_overrides(
        cfg=cfg,
        variant_name="recycling_disruption",
        material="nickel",
        region="EU27",
    )
    miss = resolve_variant_slice_overrides(
        cfg=cfg,
        variant_name="recycling_disruption",
        material="tin",
        region="RoW",
    )

    assert "trade_refined_import_need_multiplier" in hit["shocks"]
    assert "collection_rate" in hit["shocks"]
    assert "trade_refined_import_need_multiplier" not in miss["shocks"]
    assert "collection_rate" not in miss["shocks"]


def test_routing_rate_shocks_are_renormalized():
    years = [2020, 2021, 2022]
    rec, rem, disp = apply_routing_rate_shocks(
        recycling_rate=np.array([0.6, 0.6, 0.6], dtype=float),
        remanufacturing_rate=np.array([0.3, 0.3, 0.3], dtype=float),
        disposal_rate=np.array([0.1, 0.1, 0.1], dtype=float),
        years=years,
        shocks={
            "recycling_rate": {"start_year": 2020, "duration_years": 3, "multiplier": 0.5},
            "remanufacturing_rate": {"start_year": 2020, "duration_years": 3, "multiplier": 2.0},
            "disposal_rate": {"start_year": 2020, "duration_years": 3, "multiplier": 1.0},
        },
    )

    assert np.allclose(rec + rem + disp, 1.0, atol=1e-9)
    assert np.all(rec >= 0.0)
    assert np.all(rem >= 0.0)
    assert np.all(disp >= 0.0)


def test_year_gate_applies_override_only_from_start_year():
    years = [2019, 2020, 2021]
    series = _as_timeseries(
        {"start_year": 2020, "before": 0.4, "value": 0.8},
        years=years,
        name="test_gate",
    )
    assert np.allclose(series, np.array([0.4, 0.8, 0.8], dtype=float))


def test_sd_heterogeneity_resolves_by_material_region_in_order():
    base = {
        "demand_price_elasticity": 0.10,
        "coupling_signal_smoothing": 0.50,
        "coupling_service_stress_gain": 5.0,
    }
    rules = [
        {
            "name": "region_eu27",
            "regions": ["EU27"],
            "sd_parameters": {"demand_price_elasticity": 0.12, "coupling_signal_smoothing": 0.55},
        },
        {
            "name": "material_nickel",
            "materials": ["nickel"],
            "sd_parameters": {"coupling_service_stress_gain": 6.0},
        },
        {
            "name": "nickel_eu27_specific",
            "materials": ["nickel"],
            "regions": ["EU27"],
            "sd_parameters": {"coupling_service_stress_gain": 7.0},
        },
    ]

    hit = resolve_sd_parameters_for_slice(
        sd_base=base,
        sd_heterogeneity=rules,
        material="nickel",
        region="EU27",
    )
    miss = resolve_sd_parameters_for_slice(
        sd_base=base,
        sd_heterogeneity=rules,
        material="tin",
        region="RoW",
    )

    assert np.isclose(hit["demand_price_elasticity"], 0.12)
    assert np.isclose(hit["coupling_signal_smoothing"], 0.55)
    assert np.isclose(hit["coupling_service_stress_gain"], 7.0)

    assert np.isclose(miss["demand_price_elasticity"], 0.10)
    assert np.isclose(miss["coupling_signal_smoothing"], 0.50)
    assert np.isclose(miss["coupling_service_stress_gain"], 5.0)


def test_mvp_capacity_crunch_recovery_variant_schema():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "mvp.yml")

    assert "capacity_crunch_recovery" in cfg.variants

    variant = cfg.variants["capacity_crunch_recovery"]
    assert variant.shocks is not None
    shocks = variant.shocks.model_dump(exclude_none=True, exclude_unset=True)

    assert set(["demand_surge", "primary_refined_output", "trade_refined_import_need_multiplier"]).issubset(set(shocks.keys()))
    assert int(shocks["demand_surge"]["start_year"]) == 2025
    assert int(shocks["demand_surge"]["duration_years"]) == 18
    assert int(shocks["primary_refined_output"]["start_year"]) == 2025
    assert int(shocks["primary_refined_output"]["duration_years"]) == 18
    assert int(shocks["trade_refined_import_need_multiplier"]["start_year"]) == 2025
    assert int(shocks["trade_refined_import_need_multiplier"]["duration_years"]) == 18

    assert variant.sd_parameters is not None
    assert float(variant.sd_parameters["bottleneck_scarcity_gain"]) > 0.0
    assert float(variant.sd_parameters["bottleneck_collection_sensitivity"]) > 0.0

    hit = resolve_variant_slice_overrides(
        cfg=cfg,
        variant_name="capacity_crunch_recovery",
        material="nickel",
        region="EU27",
    )
    miss = resolve_variant_slice_overrides(
        cfg=cfg,
        variant_name="capacity_crunch_recovery",
        material="tin",
        region="RoW",
    )

    assert float(hit["sd_parameters"]["bottleneck_scarcity_gain"]) == 0.45
    assert float(hit["sd_parameters"]["bottleneck_collection_sensitivity"]) == 0.22
    assert float(hit["shocks"]["demand_surge"]["multiplier"]) == 1.5
    assert float(miss["sd_parameters"]["bottleneck_scarcity_gain"]) == 0.35
    assert float(miss["sd_parameters"]["bottleneck_collection_sensitivity"]) == 0.18


def test_sd_variant_gate_injects_before_from_run_sd_baseline():
    cfg = SimpleNamespace(
        sd_parameters={
            "capacity_expansion_gain": 0.26,
            "bottleneck_scarcity_gain": 0.15,
        },
        variants={
            "temporal_sd": VariantConfig(
                sd_parameters={
                    "capacity_expansion_gain": {
                        "start_year": 2025,
                        "value": 0.34,
                    }
                },
                dimension_overrides=[
                    ScenarioDimensionOverride(
                        materials=["nickel"],
                        regions=["EU27"],
                        sd_parameters={
                            "bottleneck_scarcity_gain": {
                                "start_year": 2028,
                                "value": 0.45,
                            }
                        },
                    )
                ],
            )
        },
    )

    hit = resolve_variant_slice_overrides(
        cfg=cfg,
        variant_name="temporal_sd",
        material="nickel",
        region="EU27",
    )
    miss = resolve_variant_slice_overrides(
        cfg=cfg,
        variant_name="temporal_sd",
        material="tin",
        region="RoW",
    )

    assert hit["sd_parameters"]["capacity_expansion_gain"]["before"] == 0.26
    assert hit["sd_parameters"]["bottleneck_scarcity_gain"]["before"] == 0.15
    assert miss["sd_parameters"]["capacity_expansion_gain"]["before"] == 0.26


def test_mvp_transition_policy_and_demand_transformation_variant_schema():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "mvp.yml")

    assert "transition_policy_acceleration" in cfg.variants
    variant = cfg.variants["transition_policy_acceleration"]

    assert variant.transition_policy is not None
    tp = (
        variant.transition_policy
        if isinstance(variant.transition_policy, dict)
        else variant.transition_policy.model_dump(exclude_none=True, exclude_unset=True)
    )
    assert isinstance(tp["enabled"], dict)
    assert bool(tp["enabled"]["value"]) is True
    assert bool(tp["enabled"]["before"]) is False
    assert int(tp["start_year"]) == 2026
    assert float(tp["adoption_target"]) > 0.0
    assert float(tp["collection_uplift_max"]) > 0.0

    assert variant.demand_transformation is not None
    dt = (
        variant.demand_transformation
        if isinstance(variant.demand_transformation, dict)
        else variant.demand_transformation.model_dump(exclude_none=True, exclude_unset=True)
    )
    assert isinstance(dt["enabled"], dict)
    assert bool(dt["enabled"]["value"]) is True
    assert bool(dt["enabled"]["before"]) is False
    assert str(dt["service_activity_source"]) == "service_activity"
    assert str(dt["material_intensity_source"]) == "material_intensity"
    assert float(dt["transition_adoption_weight"]) > 0.0

    hit = resolve_variant_slice_overrides(
        cfg=cfg,
        variant_name="transition_policy_acceleration",
        material="nickel",
        region="EU27",
    )
    miss = resolve_variant_slice_overrides(
        cfg=cfg,
        variant_name="transition_policy_acceleration",
        material="tin",
        region="RoW",
    )

    assert float(hit["transition_policy"]["adoption_target"]) > float(miss["transition_policy"]["adoption_target"])
    assert float(hit["demand_transformation"]["transition_adoption_weight"]) > float(
        miss["demand_transformation"]["transition_adoption_weight"]
    )


def test_demand_transformation_variant_has_expected_driver_surface():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "mvp.yml")

    assert "demand_transformation_shift" in cfg.variants
    variant = cfg.variants["demand_transformation_shift"]
    assert variant.demand_transformation is not None
    dt = (
        variant.demand_transformation
        if isinstance(variant.demand_transformation, dict)
        else variant.demand_transformation.model_dump(exclude_none=True, exclude_unset=True)
    )
    assert isinstance(dt["enabled"], dict)
    assert bool(dt["enabled"]["value"]) is True
    assert bool(dt["enabled"]["before"]) is False
    assert str(dt["service_activity_source"]) == "service_activity"
    assert str(dt["material_intensity_source"]) == "material_intensity"
    assert float(dt["min_demand_multiplier"]) < float(dt["max_demand_multiplier"])


def test_mvp_import_squeeze_circular_ramp_variant_schema():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "mvp.yml")

    assert "import_squeeze_circular_ramp" in cfg.variants
    variant = cfg.variants["import_squeeze_circular_ramp"]

    assert variant.shocks is not None
    shocks = variant.shocks.model_dump(exclude_none=True, exclude_unset=True)
    assert "primary_refined_output" in shocks
    assert "trade_refined_import_need_multiplier" in shocks
    assert int(shocks["primary_refined_output"]["start_year"]) == 2025
    assert int(shocks["trade_refined_import_need_multiplier"]["start_year"]) == 2025

    tp = (
        variant.transition_policy
        if isinstance(variant.transition_policy, dict)
        else variant.transition_policy.model_dump(exclude_none=True, exclude_unset=True)
    )
    assert isinstance(tp["enabled"], dict)
    assert bool(tp["enabled"]["value"]) is True
    assert bool(tp["enabled"]["before"]) is False
    assert int(tp["start_year"]) == 2028
    assert float(tp["adoption_target"]) > 0.0

    dt = (
        variant.demand_transformation
        if isinstance(variant.demand_transformation, dict)
        else variant.demand_transformation.model_dump(exclude_none=True, exclude_unset=True)
    )
    assert isinstance(dt["enabled"], dict)
    assert bool(dt["enabled"]["value"]) is True
    assert bool(dt["enabled"]["before"]) is False
    assert float(dt["transition_adoption_weight"]) > 0.0

    hit = resolve_variant_slice_overrides(
        cfg=cfg,
        variant_name="import_squeeze_circular_ramp",
        material="nickel",
        region="EU27",
    )
    miss = resolve_variant_slice_overrides(
        cfg=cfg,
        variant_name="import_squeeze_circular_ramp",
        material="tin",
        region="China",
    )
    assert float(hit["shocks"]["trade_refined_import_need_multiplier"]["multiplier"]) < float(
        miss["shocks"]["trade_refined_import_need_multiplier"]["multiplier"]
    )


def test_sd_gate_injection_uses_slice_resolved_sd_baseline_after_heterogeneity():
    sd_base = {"capacity_expansion_gain": 0.26}
    sd_heterogeneity = [
        {
            "name": "eu_adjustment",
            "regions": ["EU27"],
            "sd_parameters": {"capacity_expansion_gain": 0.30},
        }
    ]
    variant_slice = {
        "sd_parameters": {
            "capacity_expansion_gain": {
                "start_year": 2025,
                "value": 0.34,
            }
        }
    }

    resolved_slice = resolve_sd_parameters_for_slice(
        sd_base=sd_base,
        sd_heterogeneity=sd_heterogeneity,
        material="nickel",
        region="EU27",
    )
    injected = inject_gate_baselines(
        overrides=variant_slice["sd_parameters"],
        primary_base=resolved_slice,
    )
    merged = deep_update(resolved_slice, injected)

    assert merged["capacity_expansion_gain"]["before"] == 0.30


def test_r_portfolio_combined_variant_smoke_run():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "r-strategies.yml")

    years = [2025, 2026, 2027, 2028]
    t = len(years)

    mat = "tin"
    region = "EU27"
    variant_slice = resolve_variant_slice_overrides(
        cfg=cfg,
        variant_name="r_portfolio_combined",
        material=mat,
        region=region,
    )
    assert "exogenous_ramp" in dict(variant_slice["strategy"]["new_scrap_to_secondary_share"])
    variant_slice = _resolve_exogenous_ramps_for_variant_slice(
        variant_slice=variant_slice,
        repo_root=root,
        variant_name="r_portfolio_combined",
        material=mat,
        region=region,
    )

    base_strategy = cfg.strategy.model_dump(exclude_none=True, exclude_unset=True)
    base_shocks = cfg.shocks.model_dump(exclude_none=True, exclude_unset=True)
    strategy = deep_update(base_strategy, variant_slice["strategy"])
    shocks = deep_update(base_shocks, variant_slice["shocks"])

    ramp = dict(strategy["new_scrap_to_secondary_share"])
    assert "points" in ramp
    resolved_share = _as_timeseries(
        ramp,
        years=years,
        name="new_scrap_to_secondary_share",
        default=float(base_strategy["new_scrap_to_secondary_share"]),
    )
    assert float(resolved_share[0]) >= float(base_strategy["new_scrap_to_secondary_share"])
    assert float(resolved_share[-1]) > float(resolved_share[0])

    lifetime_pdf = np.zeros((t, 1, 1, t), dtype=float)
    lifetime_pdf[:, :, :, 1] = 1.0

    fabrication_yield = variant_slice["mfa_parameters"].get(
        "fabrication_yield",
        cfg.mfa_parameters["fabrication_yield"],
    )
    if isinstance(fabrication_yield, dict) and "value" in fabrication_yield:
        fabrication_yield = fabrication_yield["value"]

    mfa_params = {
        "fabrication_yield": fabrication_yield,
        "collection_rate": float(cfg.mfa_parameters["collection_rate"]),
        "recycling_yield": float(cfg.mfa_parameters["recycling_yield"]),
        "reman_yield": float(cfg.mfa_parameters["reman_yield"]),
        "lifetime_pdf_trea": lifetime_pdf,
        "primary_available_to_refining": np.full((t, 1), 1.0e6, dtype=float),
    }

    res = run_loose_coupled(
        years=years,
        material=mat,
        region=region,
        end_uses=["construction"],
        final_demand_t=np.full(t, 100.0, dtype=float),
        end_use_shares_te=np.ones((t, 1), dtype=float),
        sd_params={
            **cfg.sd_parameters,
            "start_year": years[0],
            "report_start_year": years[0],
            "report_years": years,
        },
        mfa_params=mfa_params,
        strategy=strategy,
        shocks=shocks,
        coupling=cfg.coupling.model_dump(),
        service_level_threshold=0.95,
    )

    assert not res.coupling_convergence_iter.empty
    assert "Strategic_inventory_stock" in res.indicators_ts


def test_profile_payload_overrides_variant_yaml_for_r_strategies():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "r-strategies.yml")
    years = cfg.time.years
    assert years is not None

    base_slice = resolve_variant_slice_overrides(
        cfg=cfg,
        variant_name="r79_recovery_loops_high",
        material="nickel",
        region="EU27",
    )
    assert isinstance(base_slice["mfa_parameters"]["collection_rate"], dict)

    profile = load_reporting_profile_csv(root / "data" / "ramp_profiles" / "r_strategies" / "r79_profiles.csv")
    payload = build_variant_payload_from_profiles(
        profiles=profile,
        years=years,
        report_start_year=int(cfg.time.report_start_year),
    )
    merged_slice = _apply_profile_payload_to_slice(
        base_slice=base_slice,
        profile_payload=payload.get("r79_recovery_loops_high", {}),
        material="nickel",
        region="EU27",
    )
    collection = merged_slice["mfa_parameters"]["collection_rate"]
    assert isinstance(collection, list)
    assert len(collection) == len(years)
    assert np.isclose(collection[years.index(2035)], 0.9702662498513582)


def test_r36_and_r79_major_controls_use_exogenous_ramps():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "r-strategies.yml")

    def _as_dict(node):
        if node is None:
            return {}
        if isinstance(node, dict):
            return node
        if hasattr(node, "model_dump"):
            return node.model_dump(exclude_none=True, exclude_unset=True)
        return {}

    r36_keys = {
        "strategy": ["lifetime_multiplier", "reman_yield", "recycling_rate", "remanufacturing_rate", "disposal_rate"],
        "sd_parameters": ["capacity_expansion_gain", "bottleneck_scarcity_gain", "bottleneck_collection_sensitivity"],
    }
    for variant_name in ["r36_lifetime_reman_low", "r36_lifetime_reman_medium", "r36_lifetime_reman_high"]:
        variant = cfg.variants[variant_name]
        for block, keys in r36_keys.items():
            block_map = _as_dict(getattr(variant, block))
            for key in keys:
                node = _as_dict(block_map.get(key))
                assert "exogenous_ramp" in node
                assert str(node["exogenous_ramp"]).startswith("data/ramp_profiles/")

    r79_keys = {
        "mfa_parameters": ["collection_rate", "sorting_yield"],
        "sd_parameters": ["collection_price_response_gain", "bottleneck_collection_sensitivity"],
        "strategy": [
            "recycling_yield",
            "recycling_rate",
            "remanufacturing_rate",
            "disposal_rate",
            "new_scrap_to_secondary_share",
        ],
    }
    for variant_name in ["r79_recovery_loops_low", "r79_recovery_loops_medium", "r79_recovery_loops_high"]:
        variant = cfg.variants[variant_name]
        for block, keys in r79_keys.items():
            block_map = _as_dict(getattr(variant, block))
            for key in keys:
                node = _as_dict(block_map.get(key))
                assert "exogenous_ramp" in node
                assert str(node["exogenous_ramp"]).startswith("data/ramp_profiles/")

    portfolio = cfg.variants["r_portfolio_combined"]
    portfolio_keys = {
        "demand_transformation": [
            "service_activity_multiplier",
            "material_intensity_multiplier",
            "efficiency_improvement",
        ],
        "mfa_parameters": ["fabrication_yield", "collection_rate", "sorting_yield"],
        "sd_parameters": [
            "capacity_envelope_max",
            "capacity_adjustment_lag_years",
            "bottleneck_scarcity_gain",
            "bottleneck_collection_sensitivity",
            "capacity_expansion_gain",
        ],
        "strategy": [
            "lifetime_multiplier",
            "reman_yield",
            "recycling_yield",
            "recycling_rate",
            "remanufacturing_rate",
            "disposal_rate",
            "new_scrap_to_secondary_share",
        ],
    }
    for block, keys in portfolio_keys.items():
        block_map = _as_dict(getattr(portfolio, block))
        for key in keys:
            node = _as_dict(block_map.get(key))
            assert "exogenous_ramp" in node
            assert str(node["exogenous_ramp"]).startswith("data/ramp_profiles/")


def test_runtime_enforces_no_pre_reporting_temporal_modifications():
    years = list(range(1870, 2101))
    report_start_year = 2020
    variant_slice = {
        "sd_parameters": {
            "capacity_expansion_gain": {"start_year": 2010, "value": 0.4},
        },
        "mfa_parameters": {
            "collection_rate": [0.9] * len(years),
        },
        "strategy": {},
        "transition_policy": {},
        "demand_transformation": {},
        "shocks": {
            "demand_surge": {"start_year": 2010, "duration_years": 20, "multiplier": 1.2},
        },
    }
    out = _enforce_reporting_phase_for_variant_slice(
        variant_slice=variant_slice,
        years=years,
        report_start_year=report_start_year,
        sd_base={"capacity_expansion_gain": 0.26},
        mfa_base={"collection_rate": 0.4},
        strategy_base={},
        transition_policy_base={},
        demand_transformation_base={},
        shocks_base={},
    )
    sd_gate = out["sd_parameters"]["capacity_expansion_gain"]
    assert int(sd_gate["start_year"]) == report_start_year
    assert float(sd_gate["before"]) == 0.26
    mfa_gate = out["mfa_parameters"]["collection_rate"]
    assert int(mfa_gate["start_year"]) == report_start_year
    assert float(mfa_gate["before"]) == 0.4
    demand_evt = out["shocks"]["demand_surge"]
    assert int(demand_evt["start_year"]) == report_start_year
    assert int(demand_evt["duration_years"]) == 10


def test_runtime_clips_ramp_points_to_reporting_start():
    years = list(range(1870, 2101))
    report_start_year = 2020
    variant_slice = {
        "sd_parameters": {},
        "mfa_parameters": {
            "collection_rate": {
                "points": {
                    2010: 0.35,
                    2030: 0.55,
                }
            },
        },
        "strategy": {},
        "transition_policy": {},
        "demand_transformation": {},
        "shocks": {},
    }
    out = _enforce_reporting_phase_for_variant_slice(
        variant_slice=variant_slice,
        years=years,
        report_start_year=report_start_year,
        sd_base={},
        mfa_base={"collection_rate": 0.4},
        strategy_base={},
        transition_policy_base={},
        demand_transformation_base={},
        shocks_base={},
    )
    ramp = out["mfa_parameters"]["collection_rate"]
    assert "points" in ramp
    points = {int(k): float(v) for k, v in ramp["points"].items()}
    assert min(points.keys()) == report_start_year
    assert np.isclose(points[report_start_year], 0.45)
    assert np.isclose(points[2030], 0.55)
    assert np.isclose(float(ramp["before"]), 0.4)


def test_runtime_gates_scalar_runtime_overrides_to_reporting_start():
    years = list(range(1870, 2101))
    report_start_year = 2020
    variant_slice = {
        "sd_parameters": {
            "capacity_expansion_gain": 0.4,
        },
        "mfa_parameters": {},
        "strategy": {},
        "transition_policy": {},
        "demand_transformation": {},
        "shocks": {},
    }
    out = _enforce_reporting_phase_for_variant_slice(
        variant_slice=variant_slice,
        years=years,
        report_start_year=report_start_year,
        sd_base={"capacity_expansion_gain": 0.26},
        mfa_base={},
        strategy_base={},
        transition_policy_base={},
        demand_transformation_base={},
        shocks_base={},
    )
    gate = out["sd_parameters"]["capacity_expansion_gain"]
    assert int(gate["start_year"]) == report_start_year
    assert np.isclose(float(gate["before"]), 0.26)
    assert np.isclose(float(gate["value"]), 0.4)


def test_runtime_gates_enabled_flags_but_keeps_source_selector_scalars():
    years = list(range(1870, 2101))
    report_start_year = 2020
    variant_slice = {
        "sd_parameters": {},
        "mfa_parameters": {},
        "strategy": {},
        "transition_policy": {"enabled": True, "start_year": 2026},
        "demand_transformation": {
            "enabled": True,
            "service_activity_source": "service_activity",
            "material_intensity_source": "material_intensity",
        },
        "shocks": {},
    }
    out = _enforce_reporting_phase_for_variant_slice(
        variant_slice=variant_slice,
        years=years,
        report_start_year=report_start_year,
        sd_base={},
        mfa_base={},
        strategy_base={},
        transition_policy_base={"enabled": False, "start_year": 2025},
        demand_transformation_base={
            "enabled": False,
            "service_activity_source": "service_activity",
            "material_intensity_source": "material_intensity",
        },
        shocks_base={},
    )
    tp_enabled = out["transition_policy"]["enabled"]
    dt_enabled = out["demand_transformation"]["enabled"]
    assert int(tp_enabled["start_year"]) == report_start_year
    assert bool(tp_enabled["before"]) is False
    assert bool(tp_enabled["value"]) is True
    assert int(dt_enabled["start_year"]) == report_start_year
    assert bool(dt_enabled["before"]) is False
    assert bool(dt_enabled["value"]) is True
    assert out["demand_transformation"]["service_activity_source"] == "service_activity"
    assert out["demand_transformation"]["material_intensity_source"] == "material_intensity"


def test_runtime_resolves_exogenous_ramp_reference_with_scope_precedence(tmp_path: Path):
    profile = tmp_path / "ramp.csv"
    profile.write_text(
        "\n".join(
            [
                "variant,block,key,year,value,material,region,before",
                "circularity_push,mfa_parameters,collection_rate,2020,0.40,,,0.40",
                "circularity_push,mfa_parameters,collection_rate,2030,0.50,,,",
                "circularity_push,mfa_parameters,collection_rate,2020,0.45,nickel,EU27,0.45",
                "circularity_push,mfa_parameters,collection_rate,2030,0.60,nickel,EU27,",
            ]
        ),
        encoding="utf-8",
    )

    base_slice = {
        "sd_parameters": {},
        "mfa_parameters": {"collection_rate": {"exogenous_ramp": str(profile)}},
        "strategy": {},
        "transition_policy": {},
        "demand_transformation": {},
        "shocks": {},
    }

    eu = _resolve_exogenous_ramps_for_variant_slice(
        variant_slice=base_slice,
        repo_root=tmp_path,
        variant_name="circularity_push",
        material="nickel",
        region="EU27",
    )
    row = _resolve_exogenous_ramps_for_variant_slice(
        variant_slice=base_slice,
        repo_root=tmp_path,
        variant_name="circularity_push",
        material="tin",
        region="RoW",
    )

    eu_points = eu["mfa_parameters"]["collection_rate"]["points"]
    row_points = row["mfa_parameters"]["collection_rate"]["points"]
    assert np.isclose(float(eu_points[2020]), 0.45)
    assert np.isclose(float(eu_points[2030]), 0.60)
    assert np.isclose(float(eu["mfa_parameters"]["collection_rate"]["before"]), 0.45)
    assert np.isclose(float(row_points[2020]), 0.40)
    assert np.isclose(float(row_points[2030]), 0.50)
