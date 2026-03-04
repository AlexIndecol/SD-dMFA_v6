from __future__ import annotations

import glob
from pathlib import Path

import pandas as pd

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


def test_r_strategy_variants_encode_heterogeneity_via_overrides_or_profiles():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "r-strategies.yml")
    scenario_profiles = getattr(cfg, "scenario_profiles", None)

    profile_variants = set()
    if scenario_profiles is not None and bool(getattr(scenario_profiles, "enabled", False)):
        csv_globs = list(getattr(scenario_profiles, "csv_globs", []) or [])
        frames = []
        for spec in csv_globs:
            for p in sorted(glob.glob(str(spec))):
                path = Path(p)
                if path.is_file():
                    frames.append(pd.read_csv(path))
        if frames:
            profile_df = pd.concat(frames, ignore_index=True)
            profile_variants = set(profile_df["variant"].astype(str).unique().tolist())

    for name, variant in cfg.variants.items():
        if name == "baseline":
            continue
        overrides = variant.dimension_overrides
        if overrides:
            region_sets = {tuple(_to_dict(ov).get("regions", [])) for ov in overrides}
            assert any(rs in region_sets for rs in (("EU27",), ("China",), ("RoW",))), (
                f"{name} has overrides but no region-specific scope."
            )
            continue

        assert (
            name in profile_variants
        ), f"{name} has no explicit dimension_overrides and no profile CSV payload."
