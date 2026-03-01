from __future__ import annotations

from pathlib import Path

from crm_model.config.io import load_run_config
from crm_model.scenario_profiles import load_reporting_profile_csv


def _as_dict(node):
    if node is None:
        return {}
    if isinstance(node, dict):
        return node
    if hasattr(node, "model_dump"):
        return node.model_dump(exclude_none=True, exclude_unset=True)
    return {}


def test_mvp_demand_surge_is_global_with_regional_modulation():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "mvp.yml")
    variant = cfg.variants["demand_surge"]

    global_shocks = _as_dict(variant.shocks)
    global_evt = _as_dict(global_shocks.get("demand_surge"))
    assert int(global_evt["start_year"]) == 2025
    assert int(global_evt["duration_years"]) == 15
    assert float(global_evt["multiplier"]) == 1.35

    overrides = variant.dimension_overrides or []
    by_region = {}
    for ov in overrides:
        ovd = _as_dict(ov)
        regions = tuple(ovd.get("regions", []))
        if len(regions) == 1:
            by_region[regions[0]] = ovd

    assert set(by_region.keys()) == {"EU27", "China", "RoW"}
    vals = {}
    for region in ("EU27", "China", "RoW"):
        evt = _as_dict(_as_dict(by_region[region].get("shocks")).get("demand_surge"))
        assert int(evt["start_year"]) == 2025
        assert int(evt["duration_years"]) == 15
        vals[region] = float(evt["multiplier"])
    assert vals["China"] > vals["EU27"] > vals["RoW"]


def test_mvp_recycling_disruption_is_global_with_all_region_overrides():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "mvp.yml")
    variant = cfg.variants["recycling_disruption"]

    global_evt = _as_dict(_as_dict(variant.shocks).get("recycling_disruption"))
    assert int(global_evt["start_year"]) == 2025
    assert int(global_evt["duration_years"]) == 15

    overrides = variant.dimension_overrides or []
    by_region = {}
    for ov in overrides:
        ovd = _as_dict(ov)
        regions = tuple(ovd.get("regions", []))
        if len(regions) == 1:
            by_region[regions[0]] = ovd

    assert set(by_region.keys()) == {"EU27", "China", "RoW"}

    expected_keys = {
        "recycling_disruption",
        "primary_refined_net_imports",
        "collection_rate",
        "recycling_rate",
        "remanufacturing_rate",
    }
    for region in ("EU27", "China", "RoW"):
        shocks = _as_dict(by_region[region].get("shocks"))
        assert expected_keys.issubset(set(shocks.keys()))
        for key in expected_keys:
            evt = _as_dict(shocks[key])
            assert int(evt["start_year"]) == 2025
            assert int(evt["duration_years"]) == 15


def test_mvp_combined_shocks_harmonized_window_and_targeted_layers():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "mvp.yml")
    variant = cfg.variants["combined_shocks"]

    global_evt = _as_dict(_as_dict(variant.shocks).get("demand_surge"))
    assert int(global_evt["start_year"]) == 2025
    assert int(global_evt["duration_years"]) == 15
    assert float(global_evt["multiplier"]) == 1.45

    overrides = variant.dimension_overrides or []
    names = {_as_dict(ov).get("name") for ov in overrides}
    assert {"nickel_eu27_joint_stress", "zinc_china_collection_stress"}.issubset(names)

    for ov in overrides:
        ovd = _as_dict(ov)
        shocks = _as_dict(ovd.get("shocks"))
        for evt in shocks.values():
            e = _as_dict(evt)
            assert int(e["start_year"]) == 2025
            assert int(e["duration_years"]) == 15


def test_circularity_push_profile_has_2039_anchor_for_ramp_channels():
    root = Path(__file__).resolve().parents[1]
    profile = load_reporting_profile_csv(root / "data" / "ramp_profiles" / "mvp" / "circularity_push.csv")
    subset = profile[profile["variant"] == "circularity_push"]
    assert not subset.empty

    required_pairs = {
        ("mfa_parameters", "collection_rate", "", ""),
        ("strategy", "recycling_yield", "", ""),
        ("strategy", "reman_yield", "", ""),
        ("mfa_parameters", "collection_rate", "nickel", "EU27"),
        ("strategy", "recycling_rate", "nickel", "EU27"),
        ("strategy", "remanufacturing_rate", "nickel", "EU27"),
        ("strategy", "disposal_rate", "nickel", "EU27"),
    }
    for block, key, mat, reg in required_pairs:
        hit = subset[
            (subset["block"] == block)
            & (subset["key"] == key)
            & (subset["material"] == mat)
            & (subset["region"] == reg)
        ]
        assert not hit.empty
        assert 2039 in set(hit["year"].astype(int).tolist())


def test_mvp_circularity_push_declares_exogenous_ramp_keys():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "mvp.yml")
    variant = cfg.variants["circularity_push"]

    mfa = _as_dict(variant.mfa_parameters)
    strategy = _as_dict(variant.strategy)
    assert "exogenous_ramp" in _as_dict(mfa.get("collection_rate"))
    assert "exogenous_ramp" in _as_dict(strategy.get("recycling_yield"))
    assert "exogenous_ramp" in _as_dict(strategy.get("reman_yield"))

    hit = cfg.variants["circularity_push"].dimension_overrides or []
    scoped = None
    for ov in hit:
        ovd = _as_dict(ov)
        if ovd.get("materials") == ["nickel"] and ovd.get("regions") == ["EU27"]:
            scoped = ovd
            break
    assert scoped is not None
    scoped_mfa = _as_dict(scoped.get("mfa_parameters"))
    scoped_strategy = _as_dict(scoped.get("strategy"))
    assert "exogenous_ramp" in _as_dict(scoped_mfa.get("collection_rate"))
    assert "exogenous_ramp" in _as_dict(scoped_strategy.get("recycling_rate"))
    assert "exogenous_ramp" in _as_dict(scoped_strategy.get("remanufacturing_rate"))
    assert "exogenous_ramp" in _as_dict(scoped_strategy.get("disposal_rate"))


def test_mvp_import_squeeze_declares_exogenous_ramp_keys():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "mvp.yml")
    variant = cfg.variants["import_squeeze_circular_ramp"]
    dt = _as_dict(variant.demand_transformation)
    assert "exogenous_ramp" in _as_dict(dt.get("material_intensity_multiplier"))
    assert "exogenous_ramp" in _as_dict(dt.get("efficiency_improvement"))


def test_mvp_run_config_no_runtime_scenario_profiles_block():
    root = Path(__file__).resolve().parents[1]
    text = (root / "configs" / "runs" / "mvp.yml").read_text(encoding="utf-8")
    assert "scenario_profiles:" not in text


def test_strategic_reserve_build_release_prefill_controls_are_enabled():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "mvp.yml")
    variant = cfg.variants["strategic_reserve_build_release"]

    strategy = _as_dict(variant.strategy)
    shocks = _as_dict(variant.shocks)

    enabled = _as_dict(strategy.get("strategic_reserve_enabled"))
    fill_gain = _as_dict(strategy.get("strategic_reserve_fill_gain"))
    target_cov = _as_dict(strategy.get("strategic_reserve_target_coverage_years"))
    fill_price = _as_dict(strategy.get("strategic_reserve_fill_price_threshold"))
    fill_service = _as_dict(strategy.get("strategic_reserve_fill_service_threshold"))
    fill_intent = _as_dict(shocks.get("strategic_fill_intent"))
    release_intent = {}
    for ov in variant.dimension_overrides or []:
        shocks_ov = _as_dict(_as_dict(ov).get("shocks"))
        if "strategic_release_intent" in shocks_ov:
            release_intent = _as_dict(shocks_ov.get("strategic_release_intent"))
            break

    assert bool(enabled.get("value")) is True
    assert float(fill_gain.get("value")) >= 0.6
    assert float(target_cov.get("value")) >= 0.7
    assert float(fill_price.get("value")) >= 1.2
    assert float(fill_service.get("value")) >= 0.2
    assert int(fill_intent.get("start_year")) == 2025
    assert int(fill_intent.get("duration_years")) >= 10
    assert int(release_intent.get("start_year")) == 2040
