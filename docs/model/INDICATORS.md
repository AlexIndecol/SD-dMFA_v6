# Indicators

This file documents indicator semantics, formulas, interpretation, and troubleshooting guidance.
The canonical indicator registry is [configs/indicators.yml](../../configs/indicators.yml).

## Document position

- You are here: Tier 2 canonical indicator reference.
- Canonical scope: indicator definitions, formulas, guards, interpretation, and coupling diagnostics semantics.
- Out of scope: scenario authoring contracts and full module tuning playbooks.
- Related docs: [ARCHITECTURE.md](./ARCHITECTURE.md), [MFA_MODEL.md](./MFA_MODEL.md), [SD_MODEL.md](./SD_MODEL.md), [COUPLING_LOGIC.md](./COUPLING_LOGIC.md), [GLOSSARY.md](./GLOSSARY.md), [CONFIGS.md](../workflows/CONFIGS.md)

## 1) Purpose and output files

This document is the operational reference for:
1. indicator names exported by runtime,
2. formulas and denominator guards,
3. meaning and interpretation by indicator,
4. subset-based navigation for analysis workflows.

Primary output files:
- `outputs/.../indicators/timeseries.csv`
- `outputs/.../indicators/scalar_metrics.csv`
- `outputs/.../indicators/coupling_signals_iteration_year.csv`
- `outputs/.../indicators/coupling_convergence_iteration.csv`

`timeseries.csv` rows are keyed by:
- `phase, variant, material, region, year, indicator, value`

`scalar_metrics.csv` rows are keyed by:
- `phase, variant, material, region, metric, value`

## 2) Global conventions for formulas and guards

Formula notation conventions:
1. `replace(0, nan)` means zero-denominator protection before division.
2. `fillna(v)` means nulls created by denominator guards are replaced with `v`.
3. `clip(lower, upper)` means numeric clipping to a bounded interval.
4. `max(a, 0)` or `np.maximum(a, 0)` means non-negative proxy construction.

Runtime guard conventions used in current implementation:
1. Service level uses `fillna(1.0)` for zero-demand years.
2. Most stress ratios use `fillna(0.0)` for zero-denominator years.
3. Circular stress is clipped to `[0, 1]`.
4. OD supplier concentration metrics are bounded by construction from normalized shares.

Identity-formula convention in this file:
- When a metric is a direct runtime export (not newly derived in indicator module), formula is shown as:
  - `Metric = exported_runtime_series`

## 3) Definitions: `mfa_state_and_flow_metrics` (organized by logical subsets)

### Subset: `stocks_and_use_phase`

#### `Stock_in_use`
- Definition: total in-use stock for the `(material, region, year)` slice after cohort aging and inflow/outflow updates.
- Formula: `Stock_in_use = last_mfa.stock_in_use`.
- Interpretation: rising values indicate net accumulation in the use phase; falling values indicate net drawdown or shorter lifetimes.
- Source in runtime: `MFATimeseries.stock_in_use` exported in [run_mfa.py](../../src/crm_model/mfa/run_mfa.py).
- Practical check: compare against `Inflow_to_use_total - Outflow_from_use` direction year-to-year.

#### `Inflow_to_use_total`
- Definition: total delivered flow into use, combining new fabrication and remanufactured inflow.
- Formula: `Inflow_to_use_total = Inflow_to_use_new + Inflow_to_use_reman`.
- Interpretation: this is the effective service-feeding flow; it should track delivered service trends.
- Source in runtime: aggregated in [run_mfa.py](../../src/crm_model/mfa/run_mfa.py).
- Practical check: ensure `Inflow_to_use_total` matches the sum of its two components in diagnostics.

#### `Inflow_to_use_new`
- Definition: new-material fabrication flow entering use.
- Formula: `Inflow_to_use_new = sum(flow[fabrication -> use_stock])`.
- Interpretation: high values indicate system reliance on new production instead of circular channels.
- Source in runtime: MFA flow aggregation in [run_mfa.py](../../src/crm_model/mfa/run_mfa.py).
- Practical check: inspect with `Primary_supply` and `Secondary_supply` to understand source composition.

#### `Inflow_to_use_reman`
- Definition: remanufactured flow entering use.
- Formula: `Inflow_to_use_reman = sum(flow[remanufacture -> use_stock])`.
- Interpretation: higher values indicate stronger reman channel contribution to delivered service.
- Source in runtime: MFA flow aggregation in [run_mfa.py](../../src/crm_model/mfa/run_mfa.py).
- Practical check: assess together with `EoL_remanufactured` and `Remanufacture_process_losses`.

#### `Outflow_from_use`
- Definition: outflow leaving use phase and entering end-of-life generation.
- Formula: `Outflow_from_use = Old_scrap_generated`.
- Interpretation: this is the physical retirement stream that drives EoL routing pressure.
- Source in runtime: cohort-convolution output in [system.py](../../src/crm_model/mfa/system.py).
- Practical check: compare against lifetime policy shifts (`lifetime_multiplier`) in scenarios.

### Subset: `primary_secondary_supply`

#### `Primary_supply`
- Definition: primary material input actually used in fabrication-equivalent service path.
- Formula: `Primary_supply = sum(__primary_supply_used)`.
- Interpretation: higher values indicate stronger dependence on primary feed.
- Source in runtime: aggregation in [run_mfa.py](../../src/crm_model/mfa/run_mfa.py).
- Practical check: interpret jointly with `Secondary_supply` and `RIR`.

#### `Primary_refined_net_trade_endogenous`
- Definition: refined-equivalent endogenous trade contribution from refined and concentrate channels.
- Formula: `Primary_refined_net_trade_endogenous = Trade_refined_net_imports + concentrate_to_refined_coeff * Trade_concentrate_net_imports`.
- Interpretation: positive values indicate net external support to refined-stage primary availability.
- Source in runtime: computed aggregation in [run_mfa.py](../../src/crm_model/mfa/run_mfa.py).
- Practical check: verify sign and magnitude against OD-mode shocks and trade constraints.

#### `Trade_refined_net_imports`
- Definition: net refined-metal trade input used by MFA slice.
- Formula: `Trade_refined_net_imports = last_mfa.trade_refined_net_imports`.
- Interpretation: positive is net imports; negative is net exports.
- Source in runtime: `MFATimeseries.trade_refined_net_imports`.
- Practical check: compare with OD `trade_od_imports_exports.csv` for refined commodity.

#### `Trade_concentrate_net_imports`
- Definition: net concentrate trade input used by MFA slice.
- Formula: `Trade_concentrate_net_imports = last_mfa.trade_concentrate_net_imports`.
- Interpretation: affects primary availability after refined-equivalent conversion.
- Source in runtime: `MFATimeseries.trade_concentrate_net_imports`.
- Practical check: inspect with `concentrate_to_refined_coeff` assumptions.

#### `Trade_scrap_net_imports`
- Definition: net scrap trade input used by MFA slice.
- Formula: `Trade_scrap_net_imports = last_mfa.trade_scrap_net_imports`.
- Interpretation: positive values support secondary feed; negative values drain domestic scrap availability.
- Source in runtime: `MFATimeseries.trade_scrap_net_imports`.
- Practical check: check consistency with `Secondary_feed_gap_proxy` direction.

#### `Primary_available_to_refining`
- Definition: non-negative primary availability at refining anchor after trade adjustments.
- Formula: `Primary_available_to_refining = max(primary_refined_output + trade_refined_net_imports + concentrate_to_refined_coeff * trade_concentrate_net_imports, 0)`.
- Interpretation: this is the supply-side ceiling for primary withdrawal in the slice.
- Source in runtime: `_resolve_primary_available_to_refining` in [run_mfa.py](../../src/crm_model/mfa/run_mfa.py).
- Practical check: persistent deficits versus `Refined_input_required_pre_cap` indicate pressure before OD reallocation.

#### `Secondary_supply`
- Definition: secondary material input used in satisfying required fabrication input.
- Formula: `Secondary_supply = sum(__secondary_supply_used)`.
- Interpretation: higher values indicate stronger circular-feed contribution.
- Source in runtime: aggregation in [run_mfa.py](../../src/crm_model/mfa/run_mfa.py).
- Practical check: read with `Collection_rate_effective`, `EoL_recycled`, and `RIR`.

#### `Refined_input_required_pre_cap`
- Definition: required refining input before primary/secondary caps and release constraints are applied.
- Formula: `Refined_input_required_pre_cap = sum(required_input)`.
- Interpretation: captures gross process need implied by demand and fabrication yield.
- Source in runtime: `__refined_input_required_pre_cap` in [system.py](../../src/crm_model/mfa/system.py).
- Practical check: rising values with flat availability implies gap growth and stress propagation.

#### `Refinery_stockpile_inflow`
- Definition: inflow entering refinery stockpile from secondary channels and scrap trade imports.
- Formula: `Refinery_stockpile_inflow = Recycled_secondary + New_scrap_to_secondary + Scrap_trade_imports_effective`.
- Interpretation: reflects buffer build potential from circular material streams.
- Source in runtime: `stockpile_inflow` in [system.py](../../src/crm_model/mfa/system.py).
- Practical check: compare against `Refinery_stockpile_outflow` to explain stock changes.

#### `Refinery_stockpile_outflow`
- Definition: outflow leaving refinery stockpile to demand use, strategic diversion, and scrap exports.
- Formula: `Refinery_stockpile_outflow = Secondary_used + Secondary_diverted_to_strategic + Scrap_trade_exports_effective`.
- Interpretation: high outflow with weak inflow drains short-term buffer capacity.
- Source in runtime: `stockpile_outflow` in [system.py](../../src/crm_model/mfa/system.py).
- Practical check: inspect with `Refinery_stockpile_release_rate` controls.

#### `Refinery_stockpile_stock`
- Definition: non-negative stock level in refinery stockpile state.
- Formula: `Refinery_stockpile_stock_t = max(Refinery_stockpile_stock_(t-1) + Refinery_stockpile_inflow - Refinery_stockpile_outflow, 0)`.
- Interpretation: positive terminal value is inventory carry-over, not model loss.
- Source in runtime: native stock update in [system.py](../../src/crm_model/mfa/system.py).
- Practical check: verify stock trajectory under build/drawdown scenarios.

#### `Extraction_losses`
- Definition: losses in extraction stage before beneficiation feed.
- Formula: `Extraction_losses = Extraction_input_required - Extraction_output_required`.
- Interpretation: structurally set by extraction yield; not necessarily scenario noise.
- Source in runtime: stage-loss reconstruction in [system.py](../../src/crm_model/mfa/system.py).
- Practical check: if spikes appear, inspect extraction yield shocks.

#### `Beneficiation_losses`
- Definition: losses in beneficiation/concentration stage.
- Formula: `Beneficiation_losses = Beneficiation_input_required - Beneficiation_output_required`.
- Interpretation: maps upstream reconstruction burden under constrained yields.
- Source in runtime: stage-loss reconstruction in [system.py](../../src/crm_model/mfa/system.py).
- Practical check: confirm trends against beneficiation yield assumptions.

#### `Refining_losses`
- Definition: losses in refining stage from primary-throughput reconstruction.
- Formula: `Refining_losses = Refining_input_primary - Primary_total_withdrawn`.
- Interpretation: increases when refining yield decreases or required throughput rises.
- Source in runtime: stage-loss reconstruction in [system.py](../../src/crm_model/mfa/system.py).
- Practical check: inspect with `Refined_input_required_pre_cap` and refining yield series.

### Subset: `eol_and_routing`

#### `EoL_generated`
- Definition: total end-of-life generated material from use outflow.
- Formula: `EoL_generated = Old_scrap_generated`.
- Interpretation: baseline retirement pressure entering collection/routing system.
- Source in runtime: aggregated from `__old_scrap_generated`.
- Practical check: compare against lifetime and demand-shift scenario periods.

#### `EoL_collected`
- Definition: collected fraction of generated EoL material.
- Formula: `EoL_collected = EoL_generated * collection_rate_effective_path`.
- Interpretation: operational collection performance channel before routing split.
- Source in runtime: aggregated from `__old_scrap_collected`.
- Practical check: interpret with `Collection_rate_effective` and collection multiplier channels.

#### `Collection_rate_effective`
- Definition: realized collection fraction for each year.
- Formula: `Collection_rate_effective = (EoL_collected / EoL_generated.replace(0, nan)).fillna(0.0)`.
- Interpretation: shows how much generated EoL actually enters controllable routing.
- Source in runtime: computed in [runner.py](../../src/crm_model/coupling/runner.py).
- Practical check: if near zero under stress, inspect `Coupling_collection_multiplier` and bounds.

#### `EoL_recycled`
- Definition: recycled output from the recycling branch after sorting and recycling yields.
- Formula: `EoL_recycled = sum(sort_to_recycling * recycling_yield)` (or direct recycle path when sorting stage absent).
- Interpretation: high values indicate effective recycling recovery, not just high collection.
- Source in runtime: aggregated in [run_mfa.py](../../src/crm_model/mfa/run_mfa.py).
- Practical check: inspect with `Sorting_rejects_*` and `Recycling_process_losses`.

#### `EoL_remanufactured`
- Definition: remanufactured output from collected reman-eligible stream after reman yield.
- Formula: `EoL_remanufactured = sum(collection_to_reman) * reman_yield`.
- Interpretation: captures recovery through product-life extension path.
- Source in runtime: aggregated in [run_mfa.py](../../src/crm_model/mfa/run_mfa.py).
- Practical check: read with reman eligibility and reman yield assumptions.

#### `EoL_disposal`
- Definition: disposed portion of EoL flows (including routed disposals and rejects to disposal).
- Formula: `EoL_disposal = last_mfa.eol_disposal`.
- Interpretation: higher values indicate weaker circular retention.
- Source in runtime: `MFATimeseries.eol_disposal`.
- Practical check: compare with `EoL_recycled` and `EoL_remanufactured` shares.

#### `EoL_uncollected`
- Definition: generated EoL not captured by collection system.
- Formula: `EoL_uncollected = EoL_generated - EoL_collected`.
- Interpretation: direct leakage from circular processing system.
- Source in runtime: `__eol_uncollected` aggregation.
- Practical check: sustained high values usually reflect low collection rate or adverse shocks.

#### `Old_scrap_generated`
- Definition: old-scrap generation from use outflows before collection split.
- Formula: `Old_scrap_generated = Outflow_from_use`.
- Interpretation: same physical quantity as use retirement in old-scrap representation.
- Source in runtime: `__old_scrap_generated`.
- Practical check: should track `Outflow_from_use` exactly.

#### `Old_scrap_collected`
- Definition: old-scrap stream that is collected and available for routing.
- Formula: `Old_scrap_collected = Old_scrap_generated * collection_rate`.
- Interpretation: upstream feeder for recycling/reman/disposal routing triad.
- Source in runtime: `__old_scrap_collected`.
- Practical check: compare against `Collection_rate_effective` for consistency.

#### `Old_scrap_uncollected`
- Definition: old-scrap stream that bypasses collection.
- Formula: `Old_scrap_uncollected = Old_scrap_generated * (1 - collection_rate)`.
- Interpretation: non-recoverable leakage unless collection system improves.
- Source in runtime: `__old_scrap_uncollected`.
- Practical check: should equal `EoL_uncollected` at aggregate level.

#### `Sorting_rejects_to_disposal`
- Definition: sorting rejects routed to disposal.
- Formula: `Sorting_rejects_to_disposal = sort_reject * sorting_reject_to_disposal_share`.
- Interpretation: high values indicate quality mismatch or weak preprocessing performance.
- Source in runtime: `__sorting_rejects_to_disposal`.
- Practical check: evaluate with `sorting_yield` and reject-share assumptions.

#### `Sorting_rejects_to_sysenv`
- Definition: sorting rejects routed to environment/system boundary.
- Formula: `Sorting_rejects_to_sysenv = sort_reject * sorting_reject_to_sysenv_share`.
- Interpretation: represents unrecovered reject leakage outside controlled material loops.
- Source in runtime: `__sorting_rejects_to_sysenv`.
- Practical check: verify disposal/share pair sums to 1 for reject split assumptions.

### Subset: `losses_surplus_and_stockpile`

#### `Fabrication_losses`
- Definition: fabrication-stage losses from total process input before use inflow.
- Formula: `Fabrication_losses = Total_input_used * (1 - fabrication_yield)`.
- Interpretation: higher values reduce direct conversion from input to delivered-use flow.
- Source in runtime: `__fabrication_losses`.
- Practical check: inspect together with `New_scrap_generated` and fabrication yield.

#### `New_scrap_generated`
- Definition: new scrap generated from fabrication losses.
- Formula: `New_scrap_generated = Fabrication_losses`.
- Interpretation: not all fabrication loss exits system; some may loop to secondary.
- Source in runtime: `__new_scrap_generated`.
- Practical check: reconcile with split into `New_scrap_to_secondary` and `New_scrap_to_residue`.

#### `New_scrap_to_secondary`
- Definition: portion of new scrap routed back into secondary channel.
- Formula: `New_scrap_to_secondary = New_scrap_generated * new_scrap_to_secondary_share`.
- Interpretation: higher values strengthen circular short-loop recovery.
- Source in runtime: `__new_scrap_to_secondary`.
- Practical check: compare with `New_scrap_to_residue` under strategy changes.

#### `New_scrap_to_residue`
- Definition: portion of new scrap not returned to secondary channel.
- Formula: `New_scrap_to_residue = New_scrap_generated - New_scrap_to_secondary`.
- Interpretation: reflects avoidable or unavoidable fabrication leakage.
- Source in runtime: `__new_scrap_to_residue`.
- Practical check: should move inversely to `new_scrap_to_secondary_share` ramps.

#### `Recycling_process_losses`
- Definition: losses during recycling process after sorting pass.
- Formula: `Recycling_process_losses = sorting_to_recycling * (1 - recycling_yield)`.
- Interpretation: process-efficiency loss, distinct from sorting rejects.
- Source in runtime: `__recycling_process_losses`.
- Practical check: verify relation to `EoL_recycled` and recycling yield.

#### `Recycling_surplus_unused`
- Definition: recycled material not immediately used in current-year input balance.
- Formula: `Recycling_surplus_unused = last_mfa.recycling_surplus_unused`.
- Interpretation: indicates recycled output exceeding immediate absorptive need.
- Source in runtime: `__recycling_surplus_unused`.
- Practical check: persistent surpluses may signal cap/dispatch imbalance.

#### `Remanufacture_process_losses`
- Definition: losses along remanufacturing path.
- Formula: `Remanufacture_process_losses = collection_to_reman * (1 - reman_yield)`.
- Interpretation: efficiency loss in reman channel.
- Source in runtime: `__remanufacture_process_losses`.
- Practical check: evaluate with `EoL_remanufactured` to tune reman yield.

#### `Remanufacture_surplus_unused`
- Definition: reman output not used immediately in meeting desired inflow.
- Formula: `Remanufacture_surplus_unused = max(reman_to_use - reman_direct_used, 0)` (aggregated).
- Interpretation: indicates reman flow exceeds current inflow demand slot.
- Source in runtime: `__remanufacture_surplus_unused`.
- Practical check: high sustained values can indicate timing mismatch between reman and demand.

### Subset: `circularity_ratios`

#### `EoL_RR`
- Definition: end-of-life recycling rate.
- Formula: `EoL_RR = (EoL_recycled / EoL_generated).replace([inf, -inf], nan).fillna(0.0)`.
- Interpretation: ratio of generated EoL captured as recycled output.
- Source in runtime: [circularity.py](../../src/crm_model/indicators/circularity.py).
- Practical check: ensure numerator and denominator trends are both inspected, not ratio alone.

#### `RIR`
- Definition: recycling input rate (secondary-share of total input).
- Formula: `RIR = (Secondary_supply / (Primary_supply + Secondary_supply)).replace([inf, -inf], nan).fillna(0.0)`.
- Interpretation: system-level circular feed dependence indicator.
- Source in runtime: [circularity.py](../../src/crm_model/indicators/circularity.py).
- Practical check: interpret with absolute `Primary_supply` and `Secondary_supply` levels.

### Subset: `diagnostics`

#### `Secondary_feed_gap_proxy`
- Definition: non-negative proxy for required input not met by available secondary feed.
- Formula: `Secondary_feed_gap_proxy = max(required_input - available_for_secondary, 0)` (aggregated).
- Interpretation: large values indicate stress on secondary adequacy before primary/strategic compensation.
- Source in runtime: `__secondary_feed_gap_proxy` in [system.py](../../src/crm_model/mfa/system.py).
- Practical check: compare with `Secondary_feed_surplus_proxy` and trade-scrap assumptions.

#### `Secondary_feed_surplus_proxy`
- Definition: non-negative proxy for secondary availability above required input.
- Formula: `Secondary_feed_surplus_proxy = max(available_for_secondary - required_input, 0)` (aggregated).
- Interpretation: high values indicate potential unused secondary opportunity or dispatch constraints.
- Source in runtime: `__secondary_feed_surplus_proxy` in [system.py](../../src/crm_model/mfa/system.py).
- Practical check: review with `Recycling_surplus_unused` and stockpile behavior.

#### `Upstream_concentrate_gap_refined_equiv_proxy`
- Definition: refined-equivalent upstream shortfall proxy after strategic release contribution.
- Formula: `Upstream_concentrate_gap_refined_equiv_proxy = max(input_shortfall - strategic_release_to_fabrication, 0)` (aggregated).
- Interpretation: persistent gaps indicate upstream pressure likely to propagate into trade or unmet service risk.
- Source in runtime: `__upstream_concentrate_gap_refined_equiv_proxy` in [system.py](../../src/crm_model/mfa/system.py).
- Practical check: compare with `Trade_concentrate_net_imports` and conversion coefficients.

#### `Upstream_concentrate_surplus_refined_equiv_proxy`
- Definition: refined-equivalent upstream surplus proxy from unused primary capacity allocation.
- Formula: `Upstream_concentrate_surplus_refined_equiv_proxy = share * primary_surplus_total` (aggregated).
- Interpretation: indicates potential upstream overcapacity relative to current need.
- Source in runtime: `__upstream_concentrate_surplus_refined_equiv_proxy` in [system.py](../../src/crm_model/mfa/system.py).
- Practical check: check with OD exports and cap constraints before concluding structural surplus.

#### `Mass_balance_residual_max_abs`
- Definition: maximum absolute annual mass-balance residual after stage/stock accounting.
- Formula: `Mass_balance_residual_max_abs = annual max(|residual_terms|)`; acceptance gate is `residual <= mass_balance_tolerance * flow_scale`.
- Interpretation: should stay near zero; spikes indicate numerical/config consistency problems.
- Source in runtime: residual checks in [system.py](../../src/crm_model/mfa/system.py).
- Practical check: if breaches occur, inspect routing normalization, yields, and stock accounting inputs.

## 4) Definitions: `resilience_service_indicators` (organized by logical subsets)

### Subset: `service_outcomes`

#### `Service_demand`
- Definition: total requested service demand entering dMFA for each year.
- Formula: `Service_demand = last_mfa.service_demand`.
- Interpretation: demand-side reference baseline for delivery and shortfall indicators.
- Source in runtime: `MFATimeseries.service_demand`.
- Practical check: confirm scenario demand ramps and transformation policies are reflected.

#### `Delivered_service`
- Definition: service actually delivered by modeled inflows to use.
- Formula: `Delivered_service = last_mfa.delivered_service`.
- Interpretation: realized service performance channel.
- Source in runtime: `MFATimeseries.delivered_service`.
- Practical check: compare with `Service_demand` and `Service_level` around stress windows.

#### `Unmet_service`
- Definition: non-negative service shortfall.
- Formula: `Unmet_service = max(Service_demand - Delivered_service, 0)`.
- Interpretation: absolute demand not served in each year.
- Source in runtime: [resilience.py](../../src/crm_model/indicators/resilience.py).
- Practical check: if non-zero in calm periods, inspect baseline supply-demand consistency.

#### `Service_level`
- Definition: delivered fraction of service demand.
- Formula: `Service_level = clip((Delivered_service / Service_demand.replace(0, nan)).fillna(1.0), 0, 1)`.
- Interpretation: normalized performance score; 1 means fully served, lower values indicate degradation.
- Source in runtime: [resilience.py](../../src/crm_model/indicators/resilience.py).
- Practical check: zero-demand years should show `1.0` by design.

#### `Service_deficit`
- Definition: non-negative shortfall from baseline service level (`1.0`).
- Formula: `Service_deficit = max(1.0 - Service_level, 0)`.
- Interpretation: transformed performance-loss series used by resilience scalars.
- Source in runtime: [resilience.py](../../src/crm_model/indicators/resilience.py).
- Practical check: equals `0` when `Service_level == 1`.

### Subset: `coupling_signals`

#### `Coupling_service_stress`
- Definition: demand-side stress signal derived from unmet service share.
- Formula: `Coupling_service_stress = (Unmet_service / Service_demand.replace(0, nan)).fillna(0.0)`.
- Interpretation: higher values indicate stronger service insufficiency pressure into coupling feedback.
- Source in runtime: computed in [runner.py](../../src/crm_model/coupling/runner.py).
- Practical check: verify with `Service_level` drops in same years.

#### `Coupling_circular_supply_stress`
- Definition: circular supply stress signal based on secondary share shortfall.
- Formula: `Coupling_circular_supply_stress = clip(1 - (Secondary_supply / (Primary_supply + Secondary_supply).replace(0, nan)).fillna(0.0), 0, 1)`.
- Interpretation: high values indicate weak circular contribution relative to total supply.
- Source in runtime: computed in [runner.py](../../src/crm_model/coupling/runner.py).
- Practical check: confirm behavior against `RIR` direction.

#### `Coupling_strategic_stock_coverage_signal`
- Definition: converged strategic coverage feedback signal used by SD strategic policy channel.
- Formula: `Coupling_strategic_stock_coverage_signal = final strategic coverage signal after smoothing/gating`.
- Interpretation: reflects how many years of demand are covered by strategic stock in signal space.
- Source in runtime: final signal export in [runner.py](../../src/crm_model/coupling/runner.py).
- Practical check: compare with direct `Strategic_stock_coverage_years` to understand lag/smoothing effects.

#### `Coupling_stress_multiplier`
- Definition: effective scarcity multiplier fed to SD after combining coupling stress channels.
- Formula: `Coupling_stress_multiplier = min(1 + coupling_service_stress_gain * service_signal + coupling_circular_supply_stress_gain * circular_signal, coupling_stress_multiplier_cap)`.
- Interpretation: this is the net coupling pressure scalar applied to SD scarcity dynamics.
- Source in runtime: `_stress_multiplier` in [runner.py](../../src/crm_model/coupling/runner.py).
- Practical check: check cap effects if multiplier saturates during high stress.

#### `Coupling_collection_multiplier`
- Definition: converged collection multiplier output from SD, used to scale base collection rate.
- Formula: `Coupling_collection_multiplier = final SD collection_multiplier series`.
- Interpretation: values above 1 increase collection pressure; below 1 suppress collection.
- Source in runtime: final export from SD outputs in [runner.py](../../src/crm_model/coupling/runner.py).
- Practical check: compare with `Collection_rate_effective` to ensure expected transmission.

#### `SD_scarcity_multiplier_effective`
- Definition: SD scarcity multiplier after bottleneck amplification.
- Formula: `SD_scarcity_multiplier_effective = scarcity_multiplier * (1 + bottleneck_scarcity_gain * bottleneck_pressure)`.
- Interpretation: direct SD internal scarcity pressure state.
- Source in runtime: [bptk_model.py](../../src/crm_model/sd/bptk_model.py).
- Practical check: spikes should coincide with bottleneck pressure spikes.

#### `SD_capacity_envelope`
- Definition: SD capacity envelope index after lagged adjustment.
- Formula: `SD_capacity_envelope = smooth(capacity_target, capacity_adjustment_lag_years, capacity_envelope_initial)`.
- Interpretation: delayed system capacity adaptation state.
- Source in runtime: [bptk_model.py](../../src/crm_model/sd/bptk_model.py).
- Practical check: verify lag behavior under shock/recovery transitions.

#### `SD_flow_utilization`
- Definition: desired-demand pressure against available capacity.
- Formula: `SD_flow_utilization = demand_desired / flow_capacity` with `flow_capacity = max(1e-12, demand_exogenous * max(capacity_envelope, 1e-6))`.
- Interpretation: values above 1 imply overload and activate bottleneck pressure.
- Source in runtime: [bptk_model.py](../../src/crm_model/sd/bptk_model.py).
- Practical check: prolonged values above 1 indicate structural tightness.

#### `SD_bottleneck_pressure`
- Definition: non-negative bottleneck indicator derived from utilization exceedance.
- Formula: `SD_bottleneck_pressure = max(SD_flow_utilization - 1, 0)`.
- Interpretation: core congestion signal driving scarcity amplification and collection throttle.
- Source in runtime: [bptk_model.py](../../src/crm_model/sd/bptk_model.py).
- Practical check: ensure near-zero in balanced baseline runs.

#### `SD_collection_bottleneck_throttle`
- Definition: damping factor applied to collection target under bottlenecks.
- Formula: `SD_collection_bottleneck_throttle = 1 / (1 + bottleneck_collection_sensitivity * SD_bottleneck_pressure)`.
- Interpretation: lowers collection responsiveness when system is congested.
- Source in runtime: [bptk_model.py](../../src/crm_model/sd/bptk_model.py).
- Practical check: should decrease when bottleneck pressure rises.

### Subset: `trade_and_security`

#### `Supplier_HHI`
- Definition: import supplier concentration index by destination region.
- Formula: `Supplier_HHI = sum(share_origin_frac^2)`.
- Interpretation: higher values mean higher concentration and lower supplier diversity.
- Source in runtime: `compute_supplier_diversification_indices` in [od.py](../../src/crm_model/trade/od.py).
- Practical check: inspect with top supplier share when concentration spikes.

#### `Supplier_Diversification`
- Definition: complement of concentration index.
- Formula: `Supplier_Diversification = clip(1 - Supplier_HHI, 0, 1)`.
- Interpretation: higher values mean broader supplier base.
- Source in runtime: `compute_supplier_diversification_indices` in [od.py](../../src/crm_model/trade/od.py).
- Practical check: should move inversely with `Supplier_HHI`.

#### `Supplier_Effective_suppliers`
- Definition: effective-number proxy derived from concentration.
- Formula: `Supplier_Effective_suppliers = (1 / Supplier_HHI) if Supplier_HHI > 0 else 0`.
- Interpretation: approximates equivalent number of equally weighted suppliers.
- Source in runtime: `compute_supplier_diversification_indices` in [od.py](../../src/crm_model/trade/od.py).
- Practical check: very high values can occur when shares are very evenly distributed.

#### `Supplier_Governance_risk_weighted`
- Definition: import-share-weighted supplier governance risk score.
- Formula: `Supplier_Governance_risk_weighted = sum(share_origin_frac * governance_risk_origin)` when risk data exists, otherwise null/empty path.
- Interpretation: higher values indicate higher exposure to governance risk in import mix.
- Source in runtime: governance merge path in [od.py](../../src/crm_model/trade/od.py), injected to indicators in [cli.py](../../src/crm_model/cli.py).
- Practical check: if missing, verify `supplier_governance_risk` source availability.

#### `Strategic_inventory_inflow`
- Definition: material entering strategic reserve stock.
- Formula: `Strategic_inventory_inflow = secondary_diverted_to_strategic + primary_diverted_to_strategic`.
- Interpretation: reserve build channel intensity.
- Source in runtime: `__strategic_inventory_inflow` in [system.py](../../src/crm_model/mfa/system.py).
- Practical check: interpret with strategic fill intent activation periods.

#### `Strategic_inventory_outflow`
- Definition: material released from strategic reserve to fabrication.
- Formula: `Strategic_inventory_outflow = strategic_release_to_fabrication`.
- Interpretation: emergency support channel under service/price stress.
- Source in runtime: `__strategic_inventory_outflow` in [system.py](../../src/crm_model/mfa/system.py).
- Practical check: should increase when release intent and shortfall are active.

#### `Strategic_inventory_stock`
- Definition: non-negative strategic reserve stock level.
- Formula: `Strategic_inventory_stock_t = max(Strategic_inventory_stock_(t-1) + Strategic_inventory_inflow - Strategic_inventory_outflow, 0)`.
- Interpretation: positive terminal stock is carry-over inventory, not unresolved loss.
- Source in runtime: native stock update in [system.py](../../src/crm_model/mfa/system.py).
- Practical check: verify stock accumulation/depletion behavior against intent controls.

#### `Strategic_stock_coverage_years`
- Definition: direct reserve coverage ratio based on strategic stock and service demand.
- Formula: `Strategic_stock_coverage_years = Strategic_inventory_stock / max(Service_demand, 1e-12)` where demand is positive, else `0`.
- Interpretation: years-equivalent reserve coverage proxy.
- Source in runtime: aggregation in [run_mfa.py](../../src/crm_model/mfa/run_mfa.py).
- Practical check: compare with coupling signal variant to see smoothing/gating impacts.

#### `Strategic_fill_intent`
- Definition: averaged fill-intent signal applied by MFA from SD strategic policy outputs.
- Formula: `Strategic_fill_intent = mean(__strategic_fill_intent over region/end_use axes)`.
- Interpretation: higher values increase reserve build aggressiveness.
- Source in runtime: aggregation in [run_mfa.py](../../src/crm_model/mfa/run_mfa.py).
- Practical check: verify alignment with low-price and low service stress signal periods.

#### `Strategic_release_intent`
- Definition: averaged release-intent signal applied by MFA from SD strategic policy outputs.
- Formula: `Strategic_release_intent = mean(__strategic_release_intent over region/end_use axes)`.
- Interpretation: higher values increase emergency reserve release tendency.
- Source in runtime: aggregation in [run_mfa.py](../../src/crm_model/mfa/run_mfa.py).
- Practical check: should rise in stressed years with elevated service or price pressure.

### Subset: `resilience_scalars`

#### `Resilience_triangle_area`
- Definition: cumulative service shortfall area over selected evaluation years.
- Formula: `Resilience_triangle_area = sum(max(1 - Service_level, 0))` over scalar-evaluation window.
- Interpretation: larger values mean deeper and/or longer performance loss.
- Source in runtime: [resilience.py](../../src/crm_model/indicators/resilience.py), window selection in [runner.py](../../src/crm_model/coupling/runner.py).
- Practical check: compare with run-specific shock duration and recovery speed.

#### `Years_below_service_threshold`
- Definition: count of years below configured minimum service level.
- Formula: `Years_below_service_threshold = count(Service_level < threshold_service_level)` over scalar-evaluation window.
- Interpretation: frequency-of-underperformance measure.
- Source in runtime: [resilience.py](../../src/crm_model/indicators/resilience.py), threshold from config through [cli.py](../../src/crm_model/cli.py).
- Practical check: verify threshold value and evaluation years before cross-run comparisons.

#### `Max_consecutive_years_below_threshold`
- Definition: longest continuous run of years below threshold.
- Formula: `Max_consecutive_years_below_threshold = max_run_length(Service_level < threshold_service_level)` over scalar-evaluation window.
- Interpretation: duration-of-stress persistence measure.
- Source in runtime: [resilience.py](../../src/crm_model/indicators/resilience.py).
- Practical check: inspect time-series to confirm run segmentation around threshold crossings.

## 5) Coupling diagnostics interpretation (dedicated section)

### 5.1 `coupling_signals_iteration_year.csv` (year-level, per iteration)

Core field families:
1. Signal-state fields:
   - `*_signal_prev`: signal value at iteration start.
   - `*_signal_target`: unsmoothed evaluation from current dMFA outputs.
   - `*_signal_next`: value after smoothing/gating update.
   - `*_residual_lag = *_signal_target - *_signal_next`.
2. Delta and convergence fields:
   - `max_signal_delta`: max absolute change across service/circular/strategic signals.
   - `collection_multiplier_delta`: max change in collection multiplier between iterations.
   - `strategic_intent_delta`: max change across fill/release intents.
   - `convergence_metric = max(max_signal_delta, collection_multiplier_delta, strategic_intent_delta)`.
3. SD state context fields:
   - `sd_scarcity_multiplier_effective`, `sd_capacity_envelope`, `sd_flow_utilization`, `sd_bottleneck_pressure`, `sd_collection_bottleneck_throttle`.
4. Control-mode fields:
   - `feedback_signal_mode` (`time_series` or `scalar_mean`).
   - `feedback_on_report_years_only`.

How to interpret this table:
1. Stable convergence: all deltas shrink over iterations and `convergence_metric` moves below tolerance.
2. Over-damping: `*_signal_next` changes very slowly with persistent `*_residual_lag`.
3. Oscillation: alternating high/low `*_signal_next` with non-decreasing deltas.
4. Report-year gating artifact: large adjustments concentrated only in reporting years when gating is active.

### 5.2 `coupling_convergence_iteration.csv` (iteration summary)

This table gives one row per iteration with aggregated means and deltas.

Key interpretation fields:
1. `convergence_metric` vs `coupling_tolerance`:
   - stop criterion is `convergence_metric < coupling_tolerance`.
2. `converged` boolean:
   - true when iteration satisfied stop condition.
3. `stress_multiplier_prev/next`:
   - net pressure update from coupling feedback.
4. `collection_multiplier_prev/target/next`:
   - collection-control settling behavior.
5. `strategic_fill_intent_mean`, `strategic_release_intent_mean`:
   - strategic channel stabilization pattern.

Practical troubleshooting patterns:
1. Stable and plausible:
   - convergence reached in few iterations with smooth signal contraction.
2. Over-damped:
   - convergence reached but mechanism response is weak; check excessive smoothing/lag.
3. Oscillatory or non-convergent:
   - raise smoothing or reduce gains/shock intensity.
4. Gating mismatch:
   - if `feedback_on_report_years_only=true`, expect staircase-like updates in non-report years.

## 6) Scalar metric windowing and threshold semantics

Scalar metrics (`Resilience_triangle_area`, `Years_below_service_threshold`, `Max_consecutive_years_below_threshold`) are computed over:
1. reporting window (`sd_parameters.report_years`) when present and non-empty,
2. otherwise full simulated horizon.

Threshold source:
- `threshold_service_level` from [configs/indicators.yml](../../configs/indicators.yml) under `service_risk`.

Operational implication:
- two runs with identical yearly curves can yield different scalar metrics if they use different reporting windows or thresholds.

## 7) Validation and usage notes

Validation rules enforced by configuration model:
1. subset names must be unique across the two indicator groups,
2. each group must be a strict partition of its own indicator list,
3. duplicate indicators within or across groups are invalid.

Usage guidance:
1. Use subset names for plotting/dashboard grouping only; subsets do not alter runtime behavior.
2. Read ratio indicators together with numerator and denominator channels to avoid false interpretation.
3. For stress analysis, pair timeseries indicators with coupling diagnostics tables.
4. For OD concentration/risk indicators, verify OD mode activation and source data availability.

## 8) Related sections

- [GLOSSARY.md](./GLOSSARY.md) for term definitions used in indicator cards.
- [ARCHITECTURE.md §8](./ARCHITECTURE.md#8-diagnostics-and-verification) for model-level diagnostic verification flow.
- [COUPLING_LOGIC.md §6](./COUPLING_LOGIC.md#6-output-interpretation-and-diagnostics) for iteration-level coupling interpretation.
- [VARIABLES_AND_PARAMETERS.md §5](./VARIABLES_AND_PARAMETERS.md#5-endogenous-variables-list-runtime-facing-canonical) for endogenous-output taxonomy context.
