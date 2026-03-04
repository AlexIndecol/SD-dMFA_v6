# MFA Model Operational Guide

This document operationalizes the MFA sections in `docs/model/ARCHITECTURE.md`.
It focuses on the implemented dMFA behavior in:
- `src/crm_model/mfa/system.py`
- `src/crm_model/mfa/run_mfa.py`
- `src/crm_model/cli.py` (runtime wiring)

## Document position

- You are here: Tier 2 canonical module deep-dive (MFA).
- Canonical scope: MFA mechanism structure, equations, controls, diagnostics, and acceptance checks.
- Out of scope: cross-module architecture rationale and full scenario catalog behavior.
- Related docs: [ARCHITECTURE.md](./ARCHITECTURE.md), [SD_MODEL.md](./SD_MODEL.md), [OD_TRADE_MODULE.md](./OD_TRADE_MODULE.md), [COUPLING_LOGIC.md](./COUPLING_LOGIC.md), [INDICATORS.md](./INDICATORS.md), [SCENARIOS.md](../workflows/SCENARIOS.md)

## 1) Purpose and boundary

Purpose:
- explain how demand is converted into physical flows/stocks,
- explain how circular loops and upstream chain reconstruction are computed,
- provide practical tuning and diagnostics guidance.

Boundary:
- core process graph and roles come from `configs/stages.yml`,
- time/region/material/end-use dimensions come from run includes,
- this module solves physical balance and inventory dynamics; it does not solve behavioral demand.

Key in-boundary stocks:
- `stock_in_use`
- `refinery_stockpile_native`
- `strategic_inventory_native`

## 2) Mechanism structure and equation map

Section `2.x` is mechanism-first and self-contained; section 3 is a fast lookup index for the same `Eq-*` IDs.

### 2.1 Demand to use-stock pipeline

How to read this mechanism:
- first read the flow sequence, then read the equation card, then confirm in diagnostics.

What happens:
1. SD realized demand is split by end-use shares and enters dMFA as service demand.
2. Delivered inflow to use comes from reman + new production inflows.
3. Cohort lifetimes convert past inflows into current outflows.
4. Outflow becomes old scrap generation, then collection applies.

Equation card:
- `Eq-MFA-01`: `old_scrap_generated = outflow_from_use`
- `Eq-MFA-02`: `old_scrap_collected = old_scrap_generated * collection_rate`
- `Eq-MFA-03`: `old_scrap_uncollected = old_scrap_generated * (1 - collection_rate)`

Symbol notes:
- `old_scrap_generated`: end-of-life scrap from use outflow.
- `collection_rate`: effective collection fraction applied in the year.

Practical controls:
- `mfa_parameters.collection_rate`
- `strategy.lifetime_multiplier`
- lifetime inputs in `lifetime_distributions.csv`

Diagnostics to watch:
- `Outflow_from_use`
- `EoL_generated`
- `EoL_collected`
- `EoL_uncollected`

### 2.2 Circular routing and process chain

How to read this mechanism:
- routing split decides material destination; yields then decide recoverable output vs losses.

What happens:
1. Collected old scrap is split into recycling/reman/disposal (triad).
2. Recycling path passes through sorting (with rejects) and recycling yield.
3. Reman path applies eligibility and reman yield.
4. Fabrication losses create new scrap and split to secondary vs residue.

Equation card:
- `Eq-MFA-04`: `recycling_rate + remanufacturing_rate + disposal_rate = 1`
- `Eq-MFA-23`: `eff_reman_rate = remanufacturing_rate * reman_eligibility`
- `Eq-MFA-24`: `eff_recycling_rate = (1 - eff_reman_rate) * ((recycling_rate / (recycling_rate + disposal_rate)) if (recycling_rate + disposal_rate) > eps else 1)`
- `Eq-MFA-25`: `eff_disposal_rate = (1 - eff_reman_rate) - eff_recycling_rate`
- `Eq-MFA-26`: `collection_to_reman = old_scrap_collected * eff_reman_rate`
- `Eq-MFA-27`: `collection_to_recycling = old_scrap_collected * eff_recycling_rate`
- `Eq-MFA-05`: `sort_pass = collection_to_recycling * sorting_yield`
- `Eq-MFA-06`: `sort_reject = collection_to_recycling - sort_pass`
- `Eq-MFA-07`: `recycled_secondary = sort_pass * recycling_yield`
- `Eq-MFA-08`: `recycling_loss = sort_pass * (1 - recycling_yield)`
- `Eq-MFA-09`: `reman_to_use = collection_to_reman * reman_yield`
- `Eq-MFA-10`: `new_scrap_generated = total_input_used * (1 - fabrication_yield)`
- `Eq-MFA-11`: `new_scrap_to_secondary = new_scrap_generated * new_scrap_to_secondary_share`

Symbol notes:
- `sorting_yield`: fraction of recycling stream passing sorting.
- `recycled_secondary`: recoverable secondary output after sorting and recycling yields.
- `reman_eligibility`: end-use eligibility gate for remanufacturing share.

Practical controls:
- `strategy.recycling_rate`, `strategy.remanufacturing_rate`, `strategy.disposal_rate`
- `mfa_parameters.sorting_yield`, `mfa_parameters.recycling_yield`, `strategy.reman_yield`
- `mfa_parameters.fabrication_yield`, `strategy.new_scrap_to_secondary_share`

Diagnostics to watch:
- `EoL_recycled`
- `EoL_remanufactured`
- `EoL_disposal`
- `Sorting_rejects_to_disposal`
- `Sorting_rejects_to_sysenv`
- `New_scrap_generated`
- `New_scrap_to_secondary`

### 2.3 Secondary and strategic inventories

How to read this mechanism:
- inflow/outflow accounting determines how much material is buffered vs immediately used.

What happens:
1. Secondary sources and scrap imports feed refinery stockpile.
2. Stockpile outflow is constrained by release dynamics and competing uses.
3. Strategic reserve fills from available streams when fill intent is active.
4. Strategic reserve releases to fabrication under stress when release intent is active.

Equation card:
- `Eq-MFA-12`: `refinery_stockpile_inflow = recycled_secondary + new_scrap_to_secondary + scrap_trade_imports_effective`
- `Eq-MFA-13`: `refinery_stockpile_outflow = secondary_used + secondary_diverted_to_strategic + scrap_trade_exports_effective`
- `Eq-MFA-14`: `refinery_stockpile_stock_t = max(refinery_stockpile_stock_(t-1) + inflow - outflow, 0)`
- `Eq-MFA-15`: `strategic_inventory_inflow = secondary_diverted_to_strategic + primary_diverted_to_strategic`
- `Eq-MFA-16`: `strategic_inventory_outflow = strategic_release_to_fabrication`
- `Eq-MFA-17`: `strategic_inventory_stock_t = max(strategic_inventory_stock_(t-1) + inflow - outflow, 0)`

Symbol notes:
- `secondary_diverted_to_strategic`: secondary stream withheld for reserve build.
- `strategic_release_to_fabrication`: reserve material released to reduce current shortfall.

Practical controls:
- `strategy.refinery_stockpile_release_rate`
- `strategy.strategic_reserve_*`
- `sd_parameters` strategic-intent drivers through coupling

Diagnostics to watch:
- `Refinery_stockpile_inflow`
- `Refinery_stockpile_outflow`
- `Refinery_stockpile_stock`
- `Strategic_inventory_inflow`
- `Strategic_inventory_outflow`
- `Strategic_inventory_stock`

### 2.4 Refining anchor and upstream reconstruction

How to read this mechanism:
- compute refining-level availability first, then reconstruct upstream throughput backwards.

What happens:
1. Primary availability is anchored at refined stage and includes endogenous trade adjustments.
2. Required primary refining input is reconstructed from withdrawn primary and refining yield.
3. Beneficiation and extraction requirements are back-calculated via yields.
4. Stage losses are routed by configured shares.
5. System performs fail-fast mass-balance residual checks.

Equation card:
- `Eq-MFA-18`: `primary_available_to_refining = max(0, primary_refined_output + trade_refined_net_imports + concentrate_to_refined_coeff * trade_concentrate_net_imports)`
- `Eq-MFA-19`: `refining_input_primary = primary_total_withdrawn / refining_yield`
- `Eq-MFA-20`: `beneficiation_input_required = refining_input_primary / beneficiation_yield`
- `Eq-MFA-21`: `extraction_input_required = beneficiation_input_required / extraction_yield`
- `Eq-MFA-22`: `max_abs_residual <= mass_balance_tolerance * flow_scale` (acceptance gate)

Symbol notes:
- `primary_total_withdrawn`: primary used for current demand plus strategic diversion.
- `flow_scale`: normalization scale used in residual gate.

Practical controls:
- `mfa_parameters.extraction_yield`, `beneficiation_yield`, `refining_yield`
- loss-share controls in `stage_yields_losses.csv`
- `mfa_parameters.mass_balance_tolerance`
- trade conversion controls: `concentrate_to_refined_coeff`, `scrap_to_secondary_coeff`

Diagnostics to watch:
- `Primary_available_to_refining`
- `Refined_input_required_pre_cap`
- `Upstream_concentrate_gap_refined_equiv_proxy`
- `Upstream_concentrate_surplus_refined_equiv_proxy`
- `Mass_balance_residual_max_abs`

## 3) Consolidated equation reference

Each equation ID below is defined in section 2 equation cards; use `Source` to trace the mechanism block.

| Equation ID | Formula | Source | Interpretation |
|---|---|---|---|
| `Eq-MFA-01` | `old_scrap_generated = outflow_from_use` | `2.1` | Use outflow becomes old scrap generation. |
| `Eq-MFA-02` | `old_scrap_collected = old_scrap_generated * collection_rate` | `2.1` | Collected share of old scrap. |
| `Eq-MFA-03` | `old_scrap_uncollected = old_scrap_generated * (1 - collection_rate)` | `2.1` | Uncollected leakage from old scrap. |
| `Eq-MFA-04` | `recycling_rate + remanufacturing_rate + disposal_rate = 1` | `2.2` | Routing triad normalization constraint. |
| `Eq-MFA-05` | `sort_pass = collection_to_recycling * sorting_yield` | `2.2` | Fraction passing sorting to recycling. |
| `Eq-MFA-06` | `sort_reject = collection_to_recycling - sort_pass` | `2.2` | Sorting reject stream. |
| `Eq-MFA-07` | `recycled_secondary = sort_pass * recycling_yield` | `2.2` | Secondary output after recycling. |
| `Eq-MFA-08` | `recycling_loss = sort_pass * (1 - recycling_yield)` | `2.2` | Recycling process loss. |
| `Eq-MFA-09` | `reman_to_use = collection_to_reman * reman_yield` | `2.2` | Remanufactured flow returning to use. |
| `Eq-MFA-10` | `new_scrap_generated = total_input_used * (1 - fabrication_yield)` | `2.2` | Fabrication-loss-generated new scrap. |
| `Eq-MFA-11` | `new_scrap_to_secondary = new_scrap_generated * new_scrap_to_secondary_share` | `2.2` | New scrap routed to secondary loop. |
| `Eq-MFA-12` | `refinery_stockpile_inflow = recycled_secondary + new_scrap_to_secondary + scrap_trade_imports_effective` | `2.3` | Stockpile build channels. |
| `Eq-MFA-13` | `refinery_stockpile_outflow = secondary_used + secondary_diverted_to_strategic + scrap_trade_exports_effective` | `2.3` | Stockpile depletion channels. |
| `Eq-MFA-14` | `refinery_stockpile_stock_t = max(refinery_stockpile_stock_(t-1) + inflow - outflow, 0)` | `2.3` | Non-negative stockpile stock evolution. |
| `Eq-MFA-15` | `strategic_inventory_inflow = secondary_diverted_to_strategic + primary_diverted_to_strategic` | `2.3` | Strategic reserve fill channels. |
| `Eq-MFA-16` | `strategic_inventory_outflow = strategic_release_to_fabrication` | `2.3` | Strategic reserve release channel. |
| `Eq-MFA-17` | `strategic_inventory_stock_t = max(strategic_inventory_stock_(t-1) + inflow - outflow, 0)` | `2.3` | Non-negative strategic stock evolution. |
| `Eq-MFA-18` | `primary_available_to_refining = max(0, primary_refined_output + trade_refined_net_imports + concentrate_to_refined_coeff * trade_concentrate_net_imports)` | `2.4` | Refining-anchor primary availability. |
| `Eq-MFA-19` | `refining_input_primary = primary_total_withdrawn / refining_yield` | `2.4` | Back-calculated primary refining input. |
| `Eq-MFA-20` | `beneficiation_input_required = refining_input_primary / beneficiation_yield` | `2.4` | Back-calculated beneficiation input. |
| `Eq-MFA-21` | `extraction_input_required = beneficiation_input_required / extraction_yield` | `2.4` | Back-calculated extraction input. |
| `Eq-MFA-22` | `max_abs_residual <= mass_balance_tolerance * flow_scale` | `2.4` | Fail-fast mass-balance acceptance gate. |
| `Eq-MFA-23` | `eff_reman_rate = remanufacturing_rate * reman_eligibility` | `2.2` | Eligibility-adjusted reman routing share. |
| `Eq-MFA-24` | `eff_recycling_rate = (1 - eff_reman_rate) * ((recycling_rate / (recycling_rate + disposal_rate)) if (recycling_rate + disposal_rate) > eps else 1)` | `2.2` | Post-reman recycling share on remaining flow with zero-denominator fallback. |
| `Eq-MFA-25` | `eff_disposal_rate = (1 - eff_reman_rate) - eff_recycling_rate` | `2.2` | Residual disposal share after reman/recycling. |
| `Eq-MFA-26` | `collection_to_reman = old_scrap_collected * eff_reman_rate` | `2.2` | Collected old scrap sent to reman path. |
| `Eq-MFA-27` | `collection_to_recycling = old_scrap_collected * eff_recycling_rate` | `2.2` | Collected old scrap sent to recycling path. |

## 4) Parameter and control surfaces

Primary config blocks:
- `mfa_parameters` in run/scenario configs,
- `strategy` in run/scenario configs,
- `shocks` in scenario configs,
- exogenous tables in registry sources.

High-impact controls:
1. `fabrication_yield`
2. `collection_rate`
3. `recycling_yield`
4. `reman_yield`
5. `recycling_rate`, `remanufacturing_rate`, `disposal_rate`
6. `sorting_yield`
7. `refinery_stockpile_release_rate`
8. `new_scrap_to_secondary_share`
9. `strategic_*` reserve controls
10. `mass_balance_tolerance`

Trade-related MFA controls:
- `concentrate_to_refined_coeff`
- `scrap_to_secondary_coeff`
- `trade_refined_net_imports_tr`
- `trade_concentrate_net_imports_tr`
- `trade_scrap_net_imports_tr`

Practical guardrails:
- keep yields/rates in [0,1],
- maintain routing triad normalization,
- tune stockpile release conservatively before stressing demand/supply shocks.

## 5) Scenario design and stress-testing workflow

Recommended sequence:
1. Baseline check with no new scenario overrides.
2. Isolate one mechanism per first scenario pass.
3. Add only the smallest override set needed.
4. Validate convergence before adding second mechanism.
5. Inspect mass-balance and routing diagnostics every run.

Useful stress patterns:
- collection disruption (routing + collection channel),
- recycling/disposal trade-offs,
- primary squeeze with circular recovery,
- stockpile build/drawdown with strategic reserve activation.

For region/material targeting:
- use `dimension_overrides` with explicit `materials`/`regions` filters.

## 6) Output interpretation and diagnostics

Core MFA indicators in `indicators/timeseries.csv`:
- `Stock_in_use`
- `Primary_supply`
- `Secondary_supply`
- `Primary_available_to_refining`
- `Refined_input_required_pre_cap`
- `Secondary_feed_gap_proxy`
- `Upstream_concentrate_gap_refined_equiv_proxy`
- `EoL_generated`, `EoL_collected`, `EoL_recycled`, `EoL_disposal`, `EoL_uncollected`
- `Refinery_stockpile_inflow/outflow/stock`
- `Strategic_inventory_inflow/outflow/stock`
- `Mass_balance_residual_max_abs`

Interpretation cues:
1. Rising `Secondary_feed_gap_proxy` means secondary feed shortage pressure.
2. Persistently high `Upstream_concentrate_gap_refined_equiv_proxy` means primary chain shortage pressure.
3. Large end-year inventory stocks are terminal stocks, not losses.
4. Non-trivial `Mass_balance_residual_max_abs` near tolerance requires immediate inspection.

## 7) Failure modes and troubleshooting

1. Routing inconsistency:
- symptom: runtime error on routing triad sum.
- cause: recycling/reman/disposal rates not summing to 1.

2. Stage-throughput distortion:
- symptom: unrealistic upstream requirements.
- cause: implausible stage yields or loss splits.

3. Apparent resilience masking:
- symptom: low unmet service despite shocks.
- cause: aggressive stockpile release and/or strategic release settings.

4. Mass-balance failure:
- symptom: fail-fast conservation error.
- cause: incompatible combination of yields/rates/flows after overrides.

5. Over-tight primary anchor behavior:
- symptom: exaggerated shortage/surplus swings.
- cause: simplified refined-equivalent anchor under missing channels.

## 8) Calibration and tuning guidance

Calibration use cases:
1. stock-fit calibration (`stock_in_use`) with conservative mechanism changes,
2. mechanism realism tuning after baseline fit,
3. trade-aware calibration in OD-enabled workflows.

Practical tuning order:
1. validate stage yields and routing data quality,
2. tune collection and recycling yields before strategic policy,
3. tune stockpile release rate before reserve aggressiveness,
4. re-check mass balance and convergence after each change.

Avoid:
- changing many highly coupled controls in one iteration,
- compensating poor yields with extreme stockpile/strategic settings.

## 9) Interactions with other modules

SD interactions:
- SD determines demand and collection multiplier dynamics upstream of dMFA inputs,
- SD strategic intents directly affect strategic inventory flow decisions.

OD trade interactions:
- OD net imports affect primary/scrap availability,
- MFA diagnostics build endogenous trade constraints in OD mode.

Coupling interactions:
- dMFA outputs feed service stress signal, circular supply stress signal, and strategic coverage signal back to SD.

## 10) Acceptance checklist

A run is MFA-acceptable when all hold:
1. Mass balance passes (`Mass_balance_residual_max_abs` within tolerance behavior).
2. Routing triad remains normalized for all years.
3. Key scenario effects appear in expected channels.
4. Terminal inventory interpretation is explicit in reporting.
5. Coupling convergence diagnostics are acceptable for all active slices.
6. Risk-sensitive assumptions are documented when used (`R-PRI-01`, `R-YLD-01`, `R-SEC-01`, `R-RES-02`, `R-COL-01`).

## 11) Related sections

- [ARCHITECTURE.md §2-3](./ARCHITECTURE.md#2-mfa-model-key-mechanisms) for the overview-level mechanism rationale.
- [INDICATORS.md §3](./INDICATORS.md#3-definitions-mfa_state_and_flow_metrics-organized-by-logical-subsets) for indicator cards tied to MFA outputs.
- [COUPLING_LOGIC.md §2](./COUPLING_LOGIC.md#2-mechanism-structure-and-equation-map) for how MFA signals are fed back to SD.
- [CONFIGS.md §6](../workflows/CONFIGS.md#6-temporal-interface-contract) for temporal override forms affecting MFA parameters.
