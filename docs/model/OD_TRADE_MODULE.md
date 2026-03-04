# OD Trade Module Operational Guide

This document operationalizes the OD trade module sections in `docs/model/ARCHITECTURE.md`.
It is aligned to:
- `src/crm_model/trade/od.py`
- `src/crm_model/cli.py` (runtime wiring and outer-loop orchestration)
- trade config surfaces in `configs/trade.yml` and run overlays.

## Document position

- You are here: Tier 2 canonical module deep-dive (OD trade).
- Canonical scope: OD activation behavior, endogenous mode, allocation/cap logic, diagnostics, and limits.
- Out of scope: full SD and MFA internal dynamics outside OD integration touchpoints.
- Related docs: [ARCHITECTURE.md](./ARCHITECTURE.md), [COUPLING_LOGIC.md](./COUPLING_LOGIC.md), [INDICATORS.md](./INDICATORS.md), [SCENARIOS.md](../workflows/SCENARIOS.md), [CONFIGS.md](../workflows/CONFIGS.md), [RISKS.md](../governance/RISKS.md)

## 1) Purpose and boundary

Purpose:
- explain how OD trade flows are computed and injected into runtime SD-dMFA,
- explain endogenous OD runtime execution,
- provide practical diagnostics and tuning guidance.

Boundary:
- OD module allocates inter-regional trade by commodity (`concentrates`, `refined_metal`, `scrap`),
- OD module does not solve physical stock/flow conservation directly; it consumes constraints from MFA and caps influenced by SD.

## 2) Mechanism structure and equation map

Section `2.x` is mechanism-first and self-contained; section 3 is a fast lookup index for the same `Eq-*` IDs.

### 2.1 Activation logic

How to read this mechanism:
- first check mode/phase booleans to confirm endogenous OD execution is active.

What happens:
1. Endogenous OD runtime activates only under the full mode/phase condition.
2. Trade state is solved iteratively and fed back into dMFA inputs.

Equation card:
- `Eq-OD-01`: `active_endogenous = trade_od.enabled and (trade_od.runtime_mode == \"endogenous\") and (phase in trade_od.activation_phases)`

Symbol notes:
- `phase`: current execution phase (`calibration` or `reporting`).
- `active_endogenous`: enables outer-loop OD integration with SD-dMFA runtime.

Practical controls:
- `trade_od.enabled`
- `trade_od.runtime_mode`
- `trade_od.activation_phases`

Diagnostics to watch:
- presence of `trade_od_outer_loop_convergence.csv` in endogenous runs.

### 2.2 Endogenous outer-loop placement

How to read this mechanism:
- inner SD-dMFA solves produce constraints; OD solve updates trade state; convergence stops iteration.

What happens:
1. For each material, run SD-dMFA across all regions with current trade state.
2. Build endogenous constraints from MFA diagnostics.
3. Allocate OD flows, then compute target net imports by commodity/region.
4. Relax-update trade state and evaluate max delta.
5. Stop when delta is below tolerance or max outer iterations reached.

Equation card:
- `Eq-OD-03`: `trade_state_next = (1 - coupling_relax_lambda_0_1) * trade_state_prev + coupling_relax_lambda_0_1 * trade_state_target`
- `Eq-OD-04`: `outer_trade_max_abs_delta = max_abs(trade_state_next - trade_state_prev)`
- `Eq-OD-05`: `outer_trade_converged = (outer_trade_max_abs_delta <= outer_trade_convergence_tol)`
- `Eq-OD-14`: `stop_outer = outer_trade_converged or (outer_iteration == outer_trade_max_iter)`

Symbol notes:
- `trade_state`: per material-region-commodity net import time series used by next outer iteration.

Practical controls:
- `outer_trade_max_iter`
- `outer_trade_convergence_tol`
- `coupling_relax_lambda_0_1`

Diagnostics to watch:
- `trade_od_outer_loop_convergence.csv` (`outer_trade_max_abs_delta_kt`, converged flag)

### 2.3 Constraints, caps, allocation, and feasibility

How to read this mechanism:
- constraints define needs/supplies, cap logic limits exportable amounts, allocator solves OD matrix under feasibility rules.

What happens:
1. Build commodity constraints from MFA shortage/surplus proxies.
2. Construct cap surfaces from empirical and SD capacity channels.
3. Smooth caps with relaxation memory, then compute exportable supply.
4. Allocate with normalized weights and destination absorption.
5. Enforce feasibility checks (no exports over supply, no imports over need).

Equation card:
- `Eq-OD-06`: `refined_need = max(refined_input_required_pre_cap - primary_available_to_refining, 0) * trade_refined_import_need_multiplier`
- `Eq-OD-07`: `conc_need = (upstream_concentrate_gap_refined_equiv_proxy / concentrate_to_refined_coeff) * trade_concentrate_import_need_multiplier`
- `Eq-OD-08`: `scrap_need = (secondary_feed_gap_proxy / scrap_to_secondary_coeff) * trade_scrap_import_need_multiplier`
- `Eq-OD-09`: `sd_cap = supply_avail * SD_capacity_envelope * capacity_cap_sd_multiplier`
- `Eq-OD-10`: `cap_raw = empirical_cap or sd_cap or min(empirical_cap, sd_cap)` (by `capacity_cap_hybrid_mode`)
- `Eq-OD-11`: `cap_smoothed = cap_raw (if cap_prev missing) else (1 - coupling_relax_lambda_0_1) * cap_prev + coupling_relax_lambda_0_1 * cap_raw`
- `Eq-OD-12`: `exportable = min(supply_avail, max(cap_smoothed, 0))`
- `Eq-OD-13`: `exports_modelled <= supply_avail` and `imports_modelled <= import_need` (feasibility checks)

Symbol notes:
- `supply_avail`: commodity-region available export-side volume from constraints.
- `import_need`: commodity-region required import-side volume from constraints.

Practical controls:
- `concentrate_to_refined_coeff`
- `scrap_to_secondary_coeff`
- `capacity_cap_hybrid_mode`
- `capacity_cap_sd_multiplier`
- `allocator_max_reallocation_passes`
- shock channels: `trade_*_import_need_multiplier`, `trade_export_capacity_multiplier`

Diagnostics to watch:
- `trade_od_flows.csv`
- `trade_od_allocator_diagnostics.csv`
- `trade_od_imports_exports.csv`
- `trade_od_supplier_diversification.csv`

## 3) Consolidated equation reference

Each equation ID below is defined in section 2 equation cards; use `Source` to trace the mechanism block.

| Equation ID | Formula | Source | Interpretation |
|---|---|---|---|
| `Eq-OD-01` | `active_endogenous = enabled and runtime_mode==\"endogenous\" and phase in activation_phases` | `2.1` | Endogenous runtime activation condition. |
| `Eq-OD-03` | `trade_state_next = (1 - lambda) * trade_state_prev + lambda * trade_state_target` | `2.2` | Relaxed outer-loop trade state update. |
| `Eq-OD-04` | `outer_trade_max_abs_delta = max_abs(trade_state_next - trade_state_prev)` | `2.2` | Outer-loop convergence norm. |
| `Eq-OD-05` | `outer_trade_converged = (outer_trade_max_abs_delta <= outer_trade_convergence_tol)` | `2.2` | Outer-loop stop condition. |
| `Eq-OD-14` | `stop_outer = outer_trade_converged or (outer_iteration == outer_trade_max_iter)` | `2.2` | Outer-loop termination logic. |
| `Eq-OD-06` | `refined_need = max(refined_input_required_pre_cap - primary_available_to_refining, 0) * trade_refined_import_need_multiplier` | `2.3` | Refined import requirement under shocks. |
| `Eq-OD-07` | `conc_need = (upstream_concentrate_gap_refined_equiv_proxy / concentrate_to_refined_coeff) * trade_concentrate_import_need_multiplier` | `2.3` | Concentrate import requirement from refined-equivalent gap. |
| `Eq-OD-08` | `scrap_need = (secondary_feed_gap_proxy / scrap_to_secondary_coeff) * trade_scrap_import_need_multiplier` | `2.3` | Scrap import requirement from secondary feed gap. |
| `Eq-OD-09` | `sd_cap = supply_avail * SD_capacity_envelope * capacity_cap_sd_multiplier` | `2.3` | SD-informed export cap surface. |
| `Eq-OD-10` | `cap_raw = empirical_cap or sd_cap or min(empirical_cap, sd_cap)` | `2.3` | Cap-mode selection logic. |
| `Eq-OD-11` | `cap_smoothed = cap_raw (if no previous cap) else (1 - lambda) * cap_prev + lambda * cap_raw` | `2.3` | Cap memory smoothing with first-iteration initialization. |
| `Eq-OD-12` | `exportable = min(supply_avail, max(cap_smoothed, 0))` | `2.3` | Effective exportable supply used by allocator. |
| `Eq-OD-13` | `exports_modelled <= supply_avail` and `imports_modelled <= import_need` | `2.3` | Allocation feasibility constraints. |

## 4) Parameter and control surfaces

Primary `trade_od` controls:
1. `enabled`
2. `runtime_mode`
3. `activation_phases`
4. `outer_trade_max_iter`
5. `outer_trade_convergence_tol`
6. `weight_extrapolation_policy` (`clamp_normalize`)
7. `commodities`
8. `concentrate_to_refined_coeff`
9. `scrap_to_secondary_coeff`
10. `allocator_max_reallocation_passes`
11. `capacity_cap_hybrid_mode`
12. `capacity_cap_sd_multiplier`
13. `coupling_relax_lambda_0_1`

Data sources:
- runtime-required: `trade_od_weights`
- calibration/backtesting utilities: `trade_od_observed`, `trade_od_constraints`
- optional risk weighting: `supplier_governance_risk`

Important current-runtime note:
- `historical_window_start_year`, `historical_window_end_year`, and `fallback_mode_outside_window` have been removed from active config/runtime interfaces.

## 5) Scenario design and stress-testing workflow

Recommended OD test sequence:
1. validate baseline endogenous OD convergence,
2. apply single-channel trade stress (import need or export capacity),
3. verify constraint-driven flow redistribution by commodity,
4. stress with simultaneous capacity and trade shocks,
5. evaluate supplier diversification and governance-risk indicators.

Practical shock channels:
- `trade_refined_import_need_multiplier`
- `trade_concentrate_import_need_multiplier`
- `trade_scrap_import_need_multiplier`
- `trade_export_capacity_multiplier`

## 6) Output interpretation and diagnostics

Primary OD outputs:
- `trade_od_flows.csv`
- `trade_od_supplier_shares.csv`
- `trade_od_supplier_diversification.csv`
- `trade_od_allocator_diagnostics.csv`
- `trade_od_imports_exports.csv`
- `trade_od_outer_loop_convergence.csv` (endogenous outer loop)

Interpretation cues:
1. falling outer-loop max delta indicates OD convergence progress,
2. supplier HHI/diversification shifts should align with stress design,
3. high residual export/import-need in diagnostics indicates restrictive caps/needs mismatch.

## 7) Failure modes and troubleshooting

1. Outer loop non-convergence:
- lower coupling relaxation (lambda) (`coupling_relax_lambda_0_1`),
- increase outer iterations,
- inspect unstable upstream constraints.

2. Infeasible allocation errors:
- verify constraints consistency and units,
- inspect cap construction and shock multipliers.

3. Flat trade response:
- check that endogenous mode is truly active,
- verify non-zero constraints and non-degenerate weights.

4. Unintended concentration spikes:
- inspect weights normalization and cap asymmetry,
- inspect region-specific constraint tightness.

## 8) Calibration and tuning guidance

Tuning order:
1. baseline stock/coupling calibration first,
2. OD controls second (`coupling_relax_lambda_0_1`, `capacity_cap_sd_multiplier`, cap mode),
3. validate against observed OD patterns where available.

Calibration principles:
- avoid overfitting one commodity at expense of others,
- keep convergence/stability as a hard acceptance gate,
- use supplier-risk indicators as interpretation checks, not sole objectives.

## 9) Interactions with other modules

With MFA:
- consumes MFA-derived shortages/surpluses to build constraints,
- writes net trade back into MFA availability channels.

With SD:
- uses SD capacity-envelope diagnostics in cap construction.

With coupling:
- endogenous OD introduces an outer loop around the inner SD-dMFA coupling loop.

## 10) Acceptance checklist

OD behavior is acceptable when:
1. mode activation behavior matches run config,
2. outer loop converges within configured bounds,
3. allocation feasibility checks pass,
4. commodity-level flow shifts are interpretable and scenario-consistent,
5. supplier concentration/risk outputs are coherent,
6. known limits are documented in interpretation (`R-OD-01`, `R-PRI-01`).

## 11) Related sections

- [ARCHITECTURE.md §6](./ARCHITECTURE.md#6-od-trade-module-across-mfa-and-sd) for overview-level OD integration.
- [COUPLING_LOGIC.md §2.2](./COUPLING_LOGIC.md#22-optional-outer-loop-per-material-across-regions) for outer-loop coupling mechanics.
- [INDICATORS.md §4.3](./INDICATORS.md#subset-trade_and_security) for trade and security indicator interpretation.
- [MODEL_GOVERNANCE.md §7](../governance/MODEL_GOVERNANCE.md#7-trade-and-od-assumptions-confirmed) for governance assumptions tied to OD runtime behavior.
