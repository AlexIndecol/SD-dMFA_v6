from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from crm_model.config.io import load_run_config


def _core_includes(root: Path, *, indicators_path: Path | None = None) -> dict[str, str]:
    cfg_dir = root / "configs"
    return {
        "time": str((cfg_dir / "time.yml").resolve()),
        "regions": str((cfg_dir / "regions.yml").resolve()),
        "materials": str((cfg_dir / "materials.yml").resolve()),
        "end_uses": str((cfg_dir / "end_use.yml").resolve()),
        "stages": str((cfg_dir / "stages.yml").resolve()),
        "qualities": str((cfg_dir / "qualities.yml").resolve()),
        "coupling": str((cfg_dir / "coupling.yml").resolve()),
        "indicators": str((indicators_path or (cfg_dir / "indicators.yml")).resolve()),
        "variables": str((root / "registry" / "variable_registry.yml").resolve()),
    }


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _assert_strict_partition(indicators: list[str], subsets: dict[str, list[str]]) -> None:
    seen: list[str] = []
    for members in subsets.values():
        seen.extend(members)
    assert len(seen) == len(set(seen))
    assert set(seen) == set(indicators)


def test_indicator_subsets_form_strict_partition_for_mvp_config():
    root = Path(__file__).resolve().parents[1]
    cfg = load_run_config(root / "configs" / "runs" / "mvp.yml")

    mfa_group = cfg.indicators.mfa_state_and_flow_metrics
    res_group = cfg.indicators.resilience_service_indicators

    _assert_strict_partition(mfa_group.indicators, mfa_group.logical_subsets)
    _assert_strict_partition(res_group.indicators, res_group.logical_subsets)


def test_indicator_subset_names_are_unique_across_groups(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    indicators_payload = _load_yaml(root / "configs" / "indicators.yml")
    res_subsets = indicators_payload["resilience_service_indicators"]["logical_subsets"]
    # Duplicate MFA subset key intentionally.
    res_subsets["diagnostics"] = list(res_subsets["service_outcomes"])

    bad_indicators = tmp_path / "indicators_bad_overlap.yml"
    _write_yaml(bad_indicators, indicators_payload)

    cfg_path = tmp_path / "cfg.yml"
    _write_yaml(
        cfg_path,
        {
            "name": "bad-overlap",
            "includes": _core_includes(root, indicators_path=bad_indicators),
        },
    )

    with pytest.raises(ValueError, match="Subset names must be unique across indicator groups"):
        load_run_config(cfg_path)


def test_indicator_subsets_reject_cross_subset_duplicates(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    indicators_payload = _load_yaml(root / "configs" / "indicators.yml")
    mfa_subsets = indicators_payload["mfa_state_and_flow_metrics"]["logical_subsets"]
    mfa_subsets["primary_secondary_supply"].append("Stock_in_use")

    bad_indicators = tmp_path / "indicators_bad_dup.yml"
    _write_yaml(bad_indicators, indicators_payload)

    cfg_path = tmp_path / "cfg.yml"
    _write_yaml(
        cfg_path,
        {
            "name": "bad-dup",
            "includes": _core_includes(root, indicators_path=bad_indicators),
        },
    )

    with pytest.raises(ValueError, match="assigns indicators to multiple subsets"):
        load_run_config(cfg_path)


def test_indicator_subsets_reject_missing_indicator_assignments(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    indicators_payload = _load_yaml(root / "configs" / "indicators.yml")
    mfa_subsets = indicators_payload["mfa_state_and_flow_metrics"]["logical_subsets"]
    mfa_subsets["circularity_ratios"] = ["EoL_RR"]

    bad_indicators = tmp_path / "indicators_bad_missing.yml"
    _write_yaml(bad_indicators, indicators_payload)

    cfg_path = tmp_path / "cfg.yml"
    _write_yaml(
        cfg_path,
        {
            "name": "bad-missing",
            "includes": _core_includes(root, indicators_path=bad_indicators),
        },
    )

    with pytest.raises(ValueError, match="must define a strict partition"):
        load_run_config(cfg_path)
