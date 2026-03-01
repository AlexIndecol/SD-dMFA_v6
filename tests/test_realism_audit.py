from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


def _load_audit_module():
    root = Path(__file__).resolve().parents[1]
    module_path = root / "scripts" / "analysis" / "audit_scenario_realism.py"
    spec = importlib.util.spec_from_file_location("audit_scenario_realism", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_summary_df() -> pd.DataFrame:
    mats = ["tin", "zinc", "nickel"]
    regs = ["EU27", "China", "RoW"]
    rows = []
    for m in mats:
        for r in regs:
            rows.append(
                {
                    "variant": "baseline",
                    "phase": "reporting",
                    "material": m,
                    "region": r,
                    "iterations": 5,
                    "final_stress_multiplier": 2.4,
                    "final_bottleneck_pressure_mean": 0.002,
                    "coupling_converged": True,
                }
            )
            rows.append(
                {
                    "variant": "r36_lifetime_reman_low",
                    "phase": "reporting",
                    "material": m,
                    "region": r,
                    "iterations": 5,
                    "final_stress_multiplier": 2.0,
                    "final_bottleneck_pressure_mean": 0.004,
                    "coupling_converged": True,
                }
            )
            rows.append(
                {
                    "variant": "r36_lifetime_reman_high",
                    "phase": "reporting",
                    "material": m,
                    "region": r,
                    "iterations": 5,
                    "final_stress_multiplier": 1.7,
                    "final_bottleneck_pressure_mean": 0.006,
                    "coupling_converged": True,
                }
            )
            rows.append(
                {
                    "variant": "r79_recovery_loops_high",
                    "phase": "reporting",
                    "material": m,
                    "region": r,
                    "iterations": 6,
                    "final_stress_multiplier": 1.8,
                    "final_bottleneck_pressure_mean": 0.02,
                    "coupling_converged": True,
                }
            )

    rows.append(
        {
            "variant": "strategic_reserve_build_release",
            "phase": "reporting",
            "material": "tin",
            "region": "EU27",
            "iterations": 8,
            "final_stress_multiplier": 2.1,
            "final_bottleneck_pressure_mean": 0.003,
            "coupling_converged": True,
        }
    )
    return pd.DataFrame(rows)


def _make_scalar_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "variant": "baseline",
                "phase": "reporting",
                "material": "tin",
                "region": "EU27",
                "metric": "Years_below_service_threshold",
                "value": 50.0,
            },
            {
                "variant": "baseline",
                "phase": "reporting",
                "material": "nickel",
                "region": "EU27",
                "metric": "Years_below_service_threshold",
                "value": 55.0,
            },
        ]
    )


def test_realism_audit_gates_pass_with_consistent_inputs():
    mod = _load_audit_module()
    audit = mod.evaluate_realism_gates(_make_summary_df(), _make_scalar_df())
    assert not audit.empty
    assert bool(audit["passed"].all())


def test_realism_audit_flags_chronic_under_service_failure():
    mod = _load_audit_module()
    scalar = _make_scalar_df()
    scalar.loc[(scalar["material"] == "tin") & (scalar["region"] == "EU27"), "value"] = 81.0
    audit = mod.evaluate_realism_gates(_make_summary_df(), scalar)
    hit = audit[audit["gate_id"] == "baseline_chronic_under_service"]
    assert not hit.empty
    assert bool(hit.iloc[0]["passed"]) is False
