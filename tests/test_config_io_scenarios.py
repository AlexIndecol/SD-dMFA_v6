from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from crm_model.config.io import load_run_config


def _core_includes(root: Path) -> dict[str, str]:
    cfg_dir = root / "configs"
    return {
        "time": str((cfg_dir / "time.yml").resolve()),
        "regions": str((cfg_dir / "regions.yml").resolve()),
        "materials": str((cfg_dir / "materials.yml").resolve()),
        "end_uses": str((cfg_dir / "end_use.yml").resolve()),
        "stages": str((cfg_dir / "stages.yml").resolve()),
        "qualities": str((cfg_dir / "qualities.yml").resolve()),
        "coupling": str((cfg_dir / "coupling.yml").resolve()),
        "indicators": str((cfg_dir / "indicators.yml").resolve()),
        "variables": str((root / "registry" / "variable_registry.yml").resolve()),
    }


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_scenarios_include_accepts_glob_pattern(tmp_path: Path):
    _write_yaml(tmp_path / "scenarios" / "baseline.yml", {"description": "Baseline"})
    _write_yaml(tmp_path / "scenarios" / "demand_surge.yml", {"description": "Demand shock"})

    root = Path(__file__).resolve().parents[1]
    config_path = tmp_path / "cfg.yml"
    _write_yaml(
        config_path,
        {
            "name": "scenario-glob-test",
            "includes": {**_core_includes(root), "scenarios": "scenarios/*.yml"},
            "sd_parameters": {"price_base": 1.0},
        },
    )

    cfg = load_run_config(config_path)
    assert {"baseline", "demand_surge"} == set(cfg.variants.keys())


def test_inline_variants_override_file_based_scenario_with_same_name(tmp_path: Path):
    _write_yaml(
        tmp_path / "scenarios" / "baseline.yml",
        {"description": "from-file", "sd_parameters": {"demand_price_elasticity": 0.11}},
    )

    root = Path(__file__).resolve().parents[1]
    config_path = tmp_path / "cfg.yml"
    _write_yaml(
        config_path,
        {
            "name": "scenario-inline-override-test",
            "includes": {**_core_includes(root), "scenarios": "scenarios/*.yml"},
            "sd_parameters": {"price_base": 1.0},
            "variants": {
                "baseline": {"description": "from-inline", "sd_parameters": {"demand_price_elasticity": 0.22}}
            },
        },
    )

    cfg = load_run_config(config_path)
    assert cfg.variants["baseline"].description == "from-inline"
    assert cfg.variants["baseline"].sd_parameters["demand_price_elasticity"] == 0.22


def test_scenarios_include_accepts_single_file(tmp_path: Path):
    _write_yaml(
        tmp_path / "scenarios" / "recycling_disruption.yml",
        {"description": "single-file-scenario"},
    )

    root = Path(__file__).resolve().parents[1]
    config_path = tmp_path / "cfg.yml"
    _write_yaml(
        config_path,
        {
            "name": "scenario-file-test",
            "includes": {**_core_includes(root), "scenarios": "scenarios/recycling_disruption.yml"},
            "sd_parameters": {"price_base": 1.0},
        },
    )

    cfg = load_run_config(config_path)
    assert "recycling_disruption" in cfg.variants


def test_run_config_extends_merges_parent_and_child(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    parent = tmp_path / "runs" / "_core.yml"
    child = tmp_path / "runs" / "overlay.yml"
    _write_yaml(
        parent,
        {
            "name": "core",
            "includes": {**_core_includes(root), "scenarios": str((tmp_path / "scenarios" / "parent").resolve() / "*.yml")},
            "strategy": {"refinery_stockpile_release_rate": 0.2},
            "variants": {"baseline": {"description": "from-parent"}},
        },
    )
    _write_yaml(tmp_path / "scenarios" / "parent" / "baseline.yml", {"description": "baseline-parent"})
    _write_yaml(tmp_path / "scenarios" / "child" / "demand_surge.yml", {"description": "surge-child"})
    _write_yaml(
        child,
        {
            "name": "overlay",
            "extends": "./_core.yml",
            "includes": {"scenarios": str((tmp_path / "scenarios" / "child").resolve() / "*.yml")},
            "strategy": {"refinery_stockpile_release_rate": 0.35},
        },
    )

    cfg = load_run_config(child)
    assert cfg.strategy.refinery_stockpile_release_rate == 0.35
    assert "demand_surge" in cfg.variants


def test_run_config_extends_cycle_fails(tmp_path: Path):
    a = tmp_path / "a.yml"
    b = tmp_path / "b.yml"
    _write_yaml(a, {"name": "a", "extends": "./b.yml"})
    _write_yaml(b, {"name": "b", "extends": "./a.yml"})

    with pytest.raises(ValueError, match="Cyclic run-config extends chain"):
        load_run_config(a)


def test_multiple_end_use_include_aliases_fail(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    cfg = tmp_path / "bad.yml"
    core = _core_includes(root)
    core["applications"] = core["end_uses"]
    _write_yaml(
        cfg,
        {
            "name": "bad-aliases",
            "includes": core,
        },
    )

    with pytest.raises(ValueError, match="must define only one end-use key"):
        load_run_config(cfg)


def test_legacy_end_use_alias_emits_deprecation_warning(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    cfg = tmp_path / "legacy.yml"
    includes = _core_includes(root)
    includes["applications"] = includes.pop("end_uses")
    _write_yaml(
        cfg,
        {
            "name": "legacy-alias",
            "includes": includes,
        },
    )

    with pytest.warns(DeprecationWarning, match="includes.applications is deprecated"):
        load_run_config(cfg)


def test_extends_preserves_parent_relative_include_paths_across_directories(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    parent = tmp_path / "runs" / "_core.yml"
    child = tmp_path / "base.yml"
    _write_yaml(tmp_path / "scenarios" / "parent" / "baseline.yml", {"description": "parent-baseline"})
    _write_yaml(
        parent,
        {
            "name": "parent",
            "includes": {**_core_includes(root), "scenarios": "../scenarios/parent/*.yml"},
        },
    )
    _write_yaml(
        child,
        {
            "name": "child",
            "extends": "./runs/_core.yml",
        },
    )

    cfg = load_run_config(child)
    assert "baseline" in cfg.variants


def test_loader_accepts_temporal_sd_parameter_forms(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    cfg = tmp_path / "temporal-forms.yml"
    _write_yaml(
        cfg,
        {
            "name": "temporal-sd-forms",
            "includes": _core_includes(root),
            "sd_parameters": {
                "capacity_expansion_gain": 0.26,
                "capacity_adjustment_lag_years": {
                    "start_year": 2025,
                    "value": 4.0,
                    "before": 5.0,
                },
                "coupling_signal_smoothing": [0.5] * 200,
            },
            "variants": {
                "baseline": {
                    "description": "temporal forms",
                    "sd_parameters": {
                        "bottleneck_scarcity_gain": {
                            "start_year": 2025,
                            "value": 0.3,
                        }
                    },
                }
            },
        },
    )

    loaded = load_run_config(cfg)
    assert "baseline" in loaded.variants
    assert isinstance(loaded.sd_parameters["capacity_expansion_gain"], float)
    assert isinstance(loaded.sd_parameters["capacity_adjustment_lag_years"], dict)
    assert isinstance(loaded.sd_parameters["coupling_signal_smoothing"], list)


def test_strategy_legacy_collection_controls_fail_fast(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    cfg = tmp_path / "legacy-strategy-collection.yml"
    _write_yaml(
        cfg,
        {
            "name": "legacy-strategy-collection",
            "includes": _core_includes(root),
            "strategy": {
                "collection_multiplier_min": 0.9,
            },
        },
    )

    with pytest.raises(ValueError, match="no longer supported"):
        load_run_config(cfg)


def test_loader_accepts_transition_policy_and_demand_transformation_blocks(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    cfg = tmp_path / "transition-demand.yml"
    _write_yaml(
        cfg,
        {
            "name": "transition-demand",
            "includes": _core_includes(root),
            "transition_policy": {
                "enabled": True,
                "start_year": 2025,
                "adoption_target": 0.8,
            },
            "demand_transformation": {
                "enabled": True,
                "service_activity_source": "service_activity",
                "material_intensity_source": "material_intensity",
                "efficiency_improvement": 0.1,
            },
            "variants": {
                "baseline": {
                    "transition_policy": {
                        "collection_uplift_max": 0.2,
                    },
                    "demand_transformation": {
                        "transition_adoption_weight": 0.6,
                    },
                    "dimension_overrides": [
                        {
                            "materials": ["nickel"],
                            "regions": ["EU27"],
                            "transition_policy": {"adoption_target": 0.9},
                            "demand_transformation": {"min_demand_multiplier": 0.7},
                        }
                    ],
                }
            },
        },
    )

    loaded = load_run_config(cfg)
    assert bool(loaded.transition_policy.enabled) is True
    assert bool(loaded.demand_transformation.enabled) is True


def test_loader_normalizes_scenario_profiles_csv_globs(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    cfg = tmp_path / "runs" / "profiled.yml"
    _write_yaml(
        cfg,
        {
            "name": "profile-enabled",
            "includes": _core_includes(root),
            "scenario_profiles": {
                "enabled": True,
                "csv_globs": ["../profiles/*.csv"],
                "interpolation": "linear",
                "apply_precedence": "profile_overrides_variant",
                "emit_resolved_payload": True,
            },
        },
    )
    loaded = load_run_config(cfg)
    assert loaded.scenario_profiles.enabled is True
    assert len(loaded.scenario_profiles.csv_globs) == 1
    assert Path(loaded.scenario_profiles.csv_globs[0]).is_absolute()
