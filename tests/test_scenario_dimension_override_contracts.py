from __future__ import annotations

from pathlib import Path

from crm_model.config.io import load_run_config


def _to_dict(node):
    if node is None:
        return {}
    if isinstance(node, dict):
        return node
    if hasattr(node, "model_dump"):
        return node.model_dump(exclude_none=True, exclude_unset=True)
    return {}


def test_mvp_targeted_scenarios_define_dimension_overrides():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "mvp.yml")

    required = {
        "capacity_crunch_recovery",
        "recycling_disruption",
        "combined_shocks",
        "transition_policy_acceleration",
        "demand_transformation_shift",
        "surplus_build_drawdown",
        "strategic_reserve_build_release",
        "import_squeeze_circular_ramp",
    }
    for name in required:
        ov = cfg.variants[name].dimension_overrides
        assert ov, f"{name} must define at least one dimension override."


def test_r_strategy_variants_keep_three_region_override_ladder():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "r-strategies.yml")

    for name, variant in cfg.variants.items():
        if name == "baseline":
            continue
        overrides = variant.dimension_overrides
        assert len(overrides) >= 3, f"{name} should expose explicit regional heterogeneity."
        region_sets = {tuple(_to_dict(ov).get("regions", [])) for ov in overrides}
        assert ("EU27",) in region_sets, f"{name}: missing EU27 override."
        assert ("China",) in region_sets, f"{name}: missing China override."
        assert ("RoW",) in region_sets, f"{name}: missing RoW override."

