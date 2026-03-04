from __future__ import annotations

import numpy as np
import pandas as pd

from crm_model.trade import (
    build_endogenous_trade_constraints,
    prepare_trade_weights_for_runtime,
    run_trade_od_allocator,
    validate_trade_od_sources,
)


def _base_trade_inputs():
    years = [2000]
    materials = ["tin"]
    commodities = ["concentrates", "refined_metal", "scrap"]
    regions = ["EU27", "China", "RoW"]

    observed_rows = []
    weight_rows = []
    for commodity in commodities:
        for origin in regions:
            for dest in regions:
                observed_rows.append(
                    {
                        "year": 2000,
                        "material": "tin",
                        "commodity": commodity,
                        "origin_region": origin,
                        "destination_region": dest,
                        "flow_kt": 10.0,
                    }
                )
                weight_rows.append(
                    {
                        "year": 2000,
                        "material": "tin",
                        "commodity": commodity,
                        "origin_region": origin,
                        "destination_region": dest,
                        "weight_0_1": 1.0 / 3.0,
                    }
                )

    constraints_rows = []
    for commodity in commodities:
        for region in regions:
            constraints_rows.append(
                {
                    "year": 2000,
                    "material": "tin",
                    "commodity": commodity,
                    "region": region,
                    "supply_avail_kt": 90.0,
                    "import_need_kt": 70.0,
                    "export_cap_raw_kt": 80.0,
                    "exportable_kt": 80.0,
                }
            )

    observed = pd.DataFrame(observed_rows)
    weights = pd.DataFrame(weight_rows)
    constraints = pd.DataFrame(constraints_rows)
    return years, materials, commodities, regions, observed, weights, constraints


def test_trade_od_allocator_respects_supply_and_import_constraints():
    years, materials, commodities, regions, observed, weights, constraints = _base_trade_inputs()
    validate_trade_od_sources(
        observed_flows=observed,
        weights=weights,
        constraints=constraints,
        materials=materials,
        regions=regions,
        commodities=commodities,
    )

    sd_caps = {(materials[0], r): np.array([1.0], dtype=float) for r in regions}
    out = run_trade_od_allocator(
        years=years,
        materials=materials,
        regions=regions,
        commodities=commodities,
        weights=weights,
        constraints=constraints,
        sd_capacity_envelope_by_material_region=sd_caps,
        capacity_cap_hybrid_mode="min_empirical_sd",
        capacity_cap_sd_multiplier=1.0,
        coupling_relax_lambda_0_1=0.3,
        max_reallocation_passes=1,
    )

    con_export = (
        out.flows.groupby(["year", "material", "commodity", "origin_region"], as_index=False)["flow_kt"]
        .sum()
        .rename(columns={"origin_region": "region", "flow_kt": "con_export"})
    )
    con_import = (
        out.flows.groupby(["year", "material", "commodity", "destination_region"], as_index=False)["flow_kt"]
        .sum()
        .rename(columns={"destination_region": "region", "flow_kt": "con_import"})
    )
    chk = (
        constraints.merge(con_export, on=["year", "material", "commodity", "region"], how="left")
        .merge(con_import, on=["year", "material", "commodity", "region"], how="left")
        .fillna(0.0)
    )
    assert (chk["con_export"] <= chk["supply_avail_kt"] + 1.0e-9).all()
    assert (chk["con_import"] <= chk["import_need_kt"] + 1.0e-9).all()


def test_trade_od_allocator_hybrid_cap_respects_sd_capacity_ceiling():
    years, materials, commodities, regions, observed, weights, constraints = _base_trade_inputs()
    sd_caps = {
        ("tin", "EU27"): np.array([0.20], dtype=float),
        ("tin", "China"): np.array([1.00], dtype=float),
        ("tin", "RoW"): np.array([1.00], dtype=float),
    }
    out = run_trade_od_allocator(
        years=years,
        materials=materials,
        regions=regions,
        commodities=commodities,
        weights=weights,
        constraints=constraints,
        sd_capacity_envelope_by_material_region=sd_caps,
        capacity_cap_hybrid_mode="min_empirical_sd",
        capacity_cap_sd_multiplier=1.0,
        coupling_relax_lambda_0_1=0.3,
        max_reallocation_passes=1,
    )

    exports = out.imports_exports[
        (out.imports_exports["material"] == "tin")
        & (out.imports_exports["region"] == "EU27")
        & (out.imports_exports["year"] == 2000)
    ]["exports_kt"].to_numpy(dtype=float)
    # supply_avail=90 and sd cap factor=0.2 => export cap is at most 18.
    assert np.all(exports <= 18.0 + 1.0e-9)


def test_trade_od_supplier_diversification_indices_with_governance_risk():
    years, materials, commodities, regions, observed, weights, constraints = _base_trade_inputs()
    sd_caps = {(materials[0], r): np.array([1.0], dtype=float) for r in regions}
    risk = pd.DataFrame(
        [
            {"year": 2000, "origin_region": "EU27", "value": 0.2},
            {"year": 2000, "origin_region": "China", "value": 0.5},
            {"year": 2000, "origin_region": "RoW", "value": 0.8},
        ]
    )

    out = run_trade_od_allocator(
        years=years,
        materials=materials,
        regions=regions,
        commodities=commodities,
        weights=weights,
        constraints=constraints,
        sd_capacity_envelope_by_material_region=sd_caps,
        supplier_governance_risk=risk,
        capacity_cap_hybrid_mode="min_empirical_sd",
        capacity_cap_sd_multiplier=1.0,
        coupling_relax_lambda_0_1=0.3,
        max_reallocation_passes=1,
    )

    row = out.supplier_diversification[
        (out.supplier_diversification["year"] == 2000)
        & (out.supplier_diversification["material"] == "tin")
        & (out.supplier_diversification["region"] == "EU27")
    ].iloc[0]
    assert np.isclose(float(row["supplier_hhi_0_1"]), 1.0 / 3.0, atol=1.0e-9)
    assert np.isclose(float(row["supplier_diversification_0_1"]), 2.0 / 3.0, atol=1.0e-9)
    assert np.isclose(float(row["effective_supplier_count"]), 3.0, atol=1.0e-9)
    assert np.isclose(float(row["supplier_governance_risk_weighted_0_1"]), 0.5, atol=1.0e-9)


def test_prepare_trade_weights_for_runtime_clamp_and_normalize():
    weights = pd.DataFrame(
        [
            {"year": 2000, "material": "tin", "commodity": "refined_metal", "origin_region": "EU27", "destination_region": "EU27", "weight_0_1": 0.2},
            {"year": 2000, "material": "tin", "commodity": "refined_metal", "origin_region": "EU27", "destination_region": "China", "weight_0_1": 0.8},
            {"year": 2000, "material": "tin", "commodity": "refined_metal", "origin_region": "EU27", "destination_region": "RoW", "weight_0_1": 0.0},
        ]
    )
    out = prepare_trade_weights_for_runtime(
        weights=weights,
        years=[1999, 2000, 2001],
        materials=["tin"],
        regions=["EU27", "China", "RoW"],
        commodities=["refined_metal"],
        policy="clamp_normalize",
    )
    sub = out[
        (out["material"] == "tin")
        & (out["commodity"] == "refined_metal")
        & (out["origin_region"] == "EU27")
    ].sort_values(["year", "destination_region"])
    # Pre/post window years are clamped to boundary rows.
    first = sub[sub["year"] == 1999]["weight_0_1"].to_numpy(dtype=float)
    mid = sub[sub["year"] == 2000]["weight_0_1"].to_numpy(dtype=float)
    last = sub[sub["year"] == 2001]["weight_0_1"].to_numpy(dtype=float)
    assert np.allclose(first, mid)
    assert np.allclose(last, mid)
    for year in [1999, 2000, 2001]:
        row_sum = float(sub[sub["year"] == year]["weight_0_1"].sum())
        assert np.isclose(row_sum, 1.0, atol=1.0e-12)


def test_build_endogenous_constraints_applies_refined_need_multiplier():
    years = [2000, 2001]
    diag = {
        "EU27": {
            "refined_input_required_pre_cap": np.array([120.0, 120.0]),
            "primary_available_to_refining": np.array([100.0, 100.0]),
            "secondary_feed_gap_proxy": np.array([40.0, 40.0]),
            "secondary_feed_surplus_proxy": np.array([0.0, 0.0]),
            "upstream_concentrate_gap_refined_equiv_proxy": np.array([10.0, 10.0]),
            "upstream_concentrate_surplus_refined_equiv_proxy": np.array([0.0, 0.0]),
        }
    }
    shocks = {
        "EU27": {
            "trade_refined_import_need_multiplier": {
                "start_year": 2000,
                "duration_years": 2,
                "multiplier": 2.0,
            }
        }
    }
    out = build_endogenous_trade_constraints(
        years=years,
        material="tin",
        regions=["EU27"],
        commodities=["refined_metal"],
        mfa_diagnostics_by_region=diag,
        shocks_by_region=shocks,
        concentrate_to_refined_coeff=1.0,
        scrap_to_secondary_coeff=1.0,
    )
    assert not out.empty
    need = out["import_need_kt"].to_numpy(dtype=float)
    # Base need is 20 kt, doubled by refined-need multiplier shock.
    assert np.allclose(need, np.array([40.0, 40.0]))
