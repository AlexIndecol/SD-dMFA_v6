from __future__ import annotations

from pathlib import Path

from crm_model.coupling.interface import MFA_TO_SD_VARIABLES, SD_TO_MFA_VARIABLES
from crm_model.coupling.runner import run_loose_coupled
from crm_model.mfa.run_mfa import run_flodym_mfa
from crm_model.sd.run_sd import run_bptk_sd
from crm_model.config.io import load_run_config


def test_crm_model_shims_are_importable():
    assert callable(run_bptk_sd)
    assert callable(run_flodym_mfa)
    assert callable(run_loose_coupled)


def test_coupling_interface_registry_has_core_variables():
    assert "desired_demand_t" in SD_TO_MFA_VARIABLES
    assert "strategic_fill_intent_t" in SD_TO_MFA_VARIABLES
    assert "strategic_release_intent_t" in SD_TO_MFA_VARIABLES
    assert "service_stress_t" in MFA_TO_SD_VARIABLES
    assert "strategic_stock_coverage_years_t" in MFA_TO_SD_VARIABLES


def test_repo_layout_scaffold_files_exist():
    root = Path(__file__).resolve().parents[1]
    expected = [
        root / "configs" / "base.yml",
        root / "configs" / "regions.yml",
        root / "configs" / "materials.yml",
        root / "configs" / "end_use.yml",
        root / "configs" / "end_use_detail.yml",
        root / "configs" / "stages.yml",
        root / "configs" / "qualities.yml",
        root / "configs" / "trade.yml",
        root / "configs" / "runs" / "_core.yml",
        root / "configs" / "runs" / "mvp.yml",
        root / "configs" / "runs" / "r-strategies.yml",
        root / "configs" / "calibration_trade.yml",
        root / "configs" / "scenarios" / "mvp" / "demand_surge.yml",
        root / "configs" / "scenarios" / "mvp" / "recycling_disruption.yml",
        root / "configs" / "scenarios" / "mvp" / "combined_shocks.yml",
        root / "configs" / "scenarios" / "mvp" / "circularity_push.yml",
        root / "configs" / "scenarios" / "mvp" / "capacity_crunch_recovery.yml",
        root / "configs" / "scenarios" / "mvp" / "transition_policy_acceleration.yml",
        root / "configs" / "scenarios" / "mvp" / "demand_transformation_shift.yml",
        root / "configs" / "scenarios" / "mvp" / "surplus_build_drawdown.yml",
        root / "configs" / "scenarios" / "mvp" / "strategic_reserve_build_release.yml",
        root / "configs" / "scenarios" / "mvp" / "import_squeeze_circular_ramp.yml",
        root / "configs" / "templates" / "sd_parameters_temporal_interface.yml",
        root / "data" / "exogenous" / "templates" / "service_activity_template.csv",
        root / "data" / "exogenous" / "templates" / "material_intensity_template.csv",
        root / "data" / "exogenous" / "supplier_governance_risk.csv",
        root / "data" / "ramp_profiles" / "templates" / "reporting_timeseries_profile_template.csv",
        root / "data" / "ramp_profiles" / "mvp" / "import_squeeze_circular_ramp.csv",
        root / "data" / "ramp_profiles" / "mvp" / "circularity_push.csv",
        root / "data" / "ramp_profiles" / "r_strategies" / "r02_profiles.csv",
        root / "data" / "ramp_profiles" / "r_strategies" / "r36_profiles.csv",
        root / "data" / "ramp_profiles" / "r_strategies" / "r79_profiles.csv",
        root / "data" / "ramp_profiles" / "r_strategies" / "r_portfolio_profiles.csv",
        root / "configs" / "scenarios" / "r_strategies" / "r02_demand_efficiency_low.yml",
        root / "configs" / "scenarios" / "r_strategies" / "r02_demand_efficiency_medium.yml",
        root / "configs" / "scenarios" / "r_strategies" / "r02_demand_efficiency_high.yml",
        root / "configs" / "scenarios" / "r_strategies" / "r36_lifetime_reman_low.yml",
        root / "configs" / "scenarios" / "r_strategies" / "r36_lifetime_reman_medium.yml",
        root / "configs" / "scenarios" / "r_strategies" / "r36_lifetime_reman_high.yml",
        root / "configs" / "scenarios" / "r_strategies" / "r79_recovery_loops_low.yml",
        root / "configs" / "scenarios" / "r_strategies" / "r79_recovery_loops_medium.yml",
        root / "configs" / "scenarios" / "r_strategies" / "r79_recovery_loops_high.yml",
        root / "configs" / "scenarios" / "r_strategies" / "r_portfolio_combined.yml",
        root / "scripts" / "run_one.py",
        root / "scripts" / "run_batch.py",
        root / "scripts" / "calibration" / "calibrate_trade_od.py",
        root / "scripts" / "analysis" / "audit_scenario_realism.py",
        root / "scripts" / "scenarios" / "build_reporting_timeseries_profiles.py",
        root / "scripts" / "validation" / "lint_run_configs.py",
    ]
    missing = [str(p) for p in expected if not p.exists()]
    assert not missing, f"Missing scaffold files: {missing}"


def test_base_config_loads_variants_from_scenarios_dir():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "base.yml")
    expected = {
        "baseline",
        "demand_surge",
        "recycling_disruption",
        "combined_shocks",
        "circularity_push",
    }
    assert expected.issubset(set(cfg.variants.keys()))


def test_mvp_config_loads_expected_scenarios_from_directory():
    root = Path(__file__).resolve().parents[1]

    mvp = load_run_config(root / "configs" / "runs" / "mvp.yml")
    expected_mvp = {
        "baseline",
        "demand_surge",
        "recycling_disruption",
        "combined_shocks",
        "circularity_push",
        "capacity_crunch_recovery",
        "transition_policy_acceleration",
        "demand_transformation_shift",
        "surplus_build_drawdown",
        "strategic_reserve_build_release",
        "import_squeeze_circular_ramp",
    }
    assert set(mvp.variants.keys()) == expected_mvp


def test_r_strategies_config_loads_expected_scenarios_from_directory():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "r-strategies.yml")
    expected = {
        "baseline",
        "r02_demand_efficiency_low",
        "r02_demand_efficiency_medium",
        "r02_demand_efficiency_high",
        "r36_lifetime_reman_low",
        "r36_lifetime_reman_medium",
        "r36_lifetime_reman_high",
        "r79_recovery_loops_low",
        "r79_recovery_loops_medium",
        "r79_recovery_loops_high",
        "r_portfolio_combined",
    }
    assert set(cfg.variants.keys()) == expected


def test_dimensions_symbols_and_stage_stock_config_are_loaded():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "mvp.yml")

    assert cfg.dimensions is not None
    assert cfg.dimensions.symbols.time == "t"
    assert cfg.dimensions.symbols.region == "r"
    assert cfg.dimensions.symbols.material == "m"
    assert cfg.dimensions.symbols.end_use == "e"
    assert cfg.dimensions.symbols.end_use_detailed == "ed"
    assert cfg.dimensions.symbols.stage == "p"
    assert cfg.dimensions.symbols.quality == "q"
    assert cfg.dimensions.symbols.commodity == "c"
    assert cfg.dimensions.symbols.origin_region == "o"
    assert cfg.dimensions.symbols.destination_region == "d"
    assert cfg.dimensions.trade_aliases.origin_region == "r"
    assert cfg.dimensions.trade_aliases.destination_region == "r"
    assert cfg.dimensions.commodities == []
    assert cfg.dimensions.origin_regions == []
    assert cfg.dimensions.destination_regions == []
    assert cfg.trade_od.enabled is False
    assert cfg.trade_od.runtime_mode == "endogenous"
    assert cfg.trade_od.activation_phases == ["calibration", "reporting"]
    assert cfg.trade_od.commodities == ["concentrates", "refined_metal", "scrap"]
    assert float(cfg.trade_od.capacity_cap_sd_multiplier) == 1.2
    assert str(cfg.trade_od.weight_extrapolation_policy) == "clamp_normalize"

    assert cfg.mfa_graph is not None
    stock_names = {s.name for s in cfg.mfa_graph.stocks}
    assert "stock_in_use" in stock_names
    assert "refinery_stockpile_native" in stock_names
    assert "strategic_inventory_native" in stock_names
