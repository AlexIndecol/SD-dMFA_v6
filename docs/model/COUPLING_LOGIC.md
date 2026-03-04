# Coupling Logic Operational Guide

This document operationalizes the coupling sections in `docs/model/ARCHITECTURE.md`.
It is aligned to:
- `src/crm_model/coupling/runner.py`
- `src/crm_model/coupling/interface.py`
- `src/crm_model/cli.py` (outer-loop orchestration with OD mode)

## Document position

- You are here: Tier 2 canonical module deep-dive (coupling).
- Canonical scope: inner and outer loop signal exchange, convergence logic, stabilization controls, and diagnostics.
- Out of scope: standalone SD or MFA mechanism internals beyond coupling interfaces.
- Related docs: [ARCHITECTURE.md](./ARCHITECTURE.md), [SD_MODEL.md](./SD_MODEL.md), [MFA_MODEL.md](./MFA_MODEL.md), [OD_TRADE_MODULE.md](./OD_TRADE_MODULE.md), [INDICATORS.md](./INDICATORS.md), [CONFIGS.md](../workflows/CONFIGS.md)

## 1) Purpose and boundary

Purpose:
- define how SD and dMFA exchange signals,
- define convergence behavior and stabilization controls,
- explain inner-loop and outer-loop coupling when OD is active.

Boundary:
- coupling coordinates module interaction and convergence,
- coupling does not replace SD or MFA solvers.

## 2) Mechanism structure and equation map

Section `2.x` is mechanism-first and self-contained; section 3 is a fast lookup index for the same `Eq-*` IDs.

### 2.1 Inner loop (per material-region slice)

How to read this mechanism:
- each coupling iteration computes SD, then dMFA, then updates signals and checks convergence.

What happens:
1. Build SD inputs with prior-iteration feedback signals.
2. Run SD to get demand, collection multiplier, and strategic intents.
3. Build dMFA inputs using SD outputs and run dMFA.
4. Compute MFA-derived feedback targets.
5. Apply smoothing/gating to update feedback signals.
6. Compute convergence metric and decide stop/continue.

Equation card:
- `Eq-CPL-01`: `service_stress_t = unmet_service / max(service_demand, eps)`
- `Eq-CPL-02`: `circular_supply_stress_t = clip(1 - secondary_supply / max(primary_supply + secondary_supply, eps), 0, 1)`
- `Eq-CPL-03`: `strategic_stock_coverage_years_t = strategic_inventory_stock / max(service_demand, eps)`
- `Eq-CPL-04`: `stress_multiplier = min(1 + coupling_service_stress_gain * service_stress_signal + coupling_circular_supply_stress_gain * circular_supply_stress_signal, coupling_stress_multiplier_cap)`
- `Eq-CPL-05`: `signal_next = (1 - smoothing) * signal_prev + smoothing * signal_target`
- `Eq-CPL-06`: `strategic_signal_next = (1 - smoothing_strategic) * strategic_signal_prev + smoothing_strategic * strategic_signal_target`
- `Eq-CPL-07`: `convergence_metric = max(max_signal_delta, collection_multiplier_delta, strategic_intent_delta)`
- `Eq-CPL-08`: `inner_converged = (convergence_metric < coupling.convergence_tol)`

Symbol notes:
- `max_signal_delta`: max absolute delta across service/circular/strategic feedback signals.
- `collection_multiplier_delta`: max delta in SD collection multiplier across iterations.
- `strategic_intent_delta`: max delta in SD strategic intents across iterations.

Practical controls:
- `coupling.max_iter`
- `coupling.convergence_tol`
- `feedback_signal_mode`
- `feedback_on_report_years_only`
- `coupling_signal_smoothing`, `coupling_signal_smoothing_strategic`

Diagnostics to watch:
- `coupling_signals_iteration_year.csv`
- `coupling_convergence_iteration.csv`
- `summary.csv` coupling fields

### 2.2 Optional outer loop (per material, across regions)

How to read this mechanism:
- outer loop wraps inner coupling solves and updates OD trade state until trade convergence.

What happens:
1. Run inner-coupled slices for all regions of the material.
2. Build endogenous OD constraints from MFA diagnostics.
3. Solve OD allocation and compute target net trade by commodity/region.
4. Relax-update trade state and evaluate outer convergence.
5. Stop when converged or max outer iterations reached.

Equation card:
- `Eq-CPL-09`: `trade_state_next = (1 - coupling_relax_lambda_0_1) * trade_state_prev + coupling_relax_lambda_0_1 * trade_state_target`
- `Eq-CPL-10`: `outer_trade_max_abs_delta = max_abs(trade_state_next - trade_state_prev)`
- `Eq-CPL-11`: `outer_converged = (outer_trade_max_abs_delta <= outer_trade_convergence_tol)`
- `Eq-CPL-12`: `stop_outer = outer_converged or (outer_iteration == outer_trade_max_iter)`

Symbol notes:
- `trade_state`: per commodity-region net-trade series fed into next outer iteration.

Practical controls:
- `outer_trade_max_iter`
- `outer_trade_convergence_tol`
- `coupling_relax_lambda_0_1`

Diagnostics to watch:
- `trade_od_outer_loop_convergence.csv`
- `trade_od_imports_exports.csv`

## 3) Consolidated equation reference

Each equation ID below is defined in section 2 equation cards; use `Source` to trace the mechanism block.

| Equation ID | Formula | Source | Interpretation |
|---|---|---|---|
| `Eq-CPL-01` | `service_stress_t = unmet_service / max(service_demand, eps)` | `2.1` | Service-pressure feedback from dMFA to SD with denominator guard. |
| `Eq-CPL-02` | `circular_supply_stress_t = clip(1 - secondary_supply / max(primary_supply + secondary_supply, eps), 0, 1)` | `2.1` | Circular-supply-pressure feedback clipped to [0,1]. |
| `Eq-CPL-03` | `strategic_stock_coverage_years_t = strategic_inventory_stock / max(service_demand, eps)` | `2.1` | Strategic reserve coverage feedback with denominator guard. |
| `Eq-CPL-04` | `stress_multiplier = min(1 + gain_service * service_signal + gain_circular * circular_signal, cap)` | `2.1` | Effective SD scarcity multiplier with cap. |
| `Eq-CPL-05` | `signal_next = (1 - smoothing) * signal_prev + smoothing * signal_target` | `2.1` | Iterative signal smoothing update. |
| `Eq-CPL-06` | `strategic_signal_next = (1 - smoothing_strategic) * strategic_prev + smoothing_strategic * strategic_target` | `2.1` | Strategic-channel-specific smoothing update. |
| `Eq-CPL-07` | `convergence_metric = max(max_signal_delta, collection_multiplier_delta, strategic_intent_delta)` | `2.1` | Implemented inner-loop convergence norm. |
| `Eq-CPL-08` | `inner_converged = (convergence_metric < coupling.convergence_tol)` | `2.1` | Inner-loop stop criterion. |
| `Eq-CPL-09` | `trade_state_next = (1 - lambda) * trade_state_prev + lambda * trade_state_target` | `2.2` | Relaxed outer-loop trade-state update. |
| `Eq-CPL-10` | `outer_trade_max_abs_delta = max_abs(trade_state_next - trade_state_prev)` | `2.2` | Outer-loop trade convergence norm. |
| `Eq-CPL-11` | `outer_converged = (outer_trade_max_abs_delta <= outer_trade_convergence_tol)` | `2.2` | Outer-loop convergence criterion. |
| `Eq-CPL-12` | `stop_outer = outer_converged or (outer_iteration == outer_trade_max_iter)` | `2.2` | Outer-loop stop logic. |

## 4) Parameter and control surfaces

Coupling config (`configs/coupling.yml`):
1. `mode` (active mode: loose iterative)
2. `max_iter`
3. `convergence_tol`
4. `feedback_signal_mode` (`time_series` / `scalar_mean`)
5. `feedback_on_report_years_only`
6. `signals` registry names for SD->MFA and MFA->SD

SD-side coupling controls (`sd_parameters`):
- `coupling_service_stress_gain`
- `coupling_circular_supply_stress_gain`
- `coupling_signal_smoothing`
- `coupling_signal_smoothing_strategic`
- `service_stress_signal_cap`
- `coupling_stress_multiplier_cap`

OD outer-loop controls (when enabled):
- `outer_trade_max_iter`
- `outer_trade_convergence_tol`
- `coupling_relax_lambda_0_1`

## 5) Scenario design and stress-testing workflow

Recommended coupling test protocol:
1. run baseline with no scenario shocks,
2. apply one stress mechanism and verify inner-loop convergence behavior,
3. if OD enabled, verify outer-loop convergence separately,
4. add additional mechanisms incrementally,
5. inspect both signal-trace and convergence diagnostics before accepting scenario behavior.

Useful stress patterns:
- service stress signal dominant (demand surge),
- circular supply stress signal dominant (recycling disruption),
- mixed stress with strategic reserve response,
- OD-enabled supply redistribution stress.

## 6) Output interpretation and diagnostics

Primary diagnostics:
- `coupling_signals_iteration_year.csv`
- `coupling_convergence_iteration.csv`
- `summary.csv` convergence fields
- `trade_od_outer_loop_convergence.csv` (OD mode)

Interpretation:
1. shrinking signal deltas across iterations indicates inner-loop stabilization,
2. persistent collection or strategic-intent delta may dominate convergence metric,
3. in OD mode, inner loop may stabilize while outer loop still needs iterations.

## 7) Failure modes and troubleshooting

1. Inner loop non-convergence:
- reduce gains,
- increase smoothing,
- reduce shock severity for first pass,
- verify SD and MFA parameter plausibility.

2. Coupling over-damping:
- smoothing too high can hide signal response timing.

3. Signal clipping artifacts:
- aggressive caps can flatten dynamics and mask mechanism movement.

4. Outer-loop instability (OD mode):
- reduce OD coupling relaxation (lambda),
- inspect trade constraints for abrupt year-to-year discontinuities.

## 8) Calibration and tuning guidance

Practical sequence:
1. stabilize inner coupling baseline first,
2. tune SD dynamic controls second,
3. tune OD outer-loop controls last (if enabled),
4. only then expand scenario complexity.

Acceptance-first tuning:
- prioritize convergence reliability and interpretable mechanism movement over aggressive sensitivity.

## 9) Interactions with other modules

With SD:
- coupling sets scarcity-related inputs and receives demand/intent outputs.

With MFA:
- coupling converts SD demand to dMFA input structure,
- coupling reads dMFA supply/service outputs to compute feedback signals.

With OD trade:
- outer loop wraps repeated inner coupling solves and feeds net trade back into MFA inputs.

With indicators:
- coupling emits iteration-level diagnostics used to validate scenario plausibility.

## 10) Acceptance checklist

Coupling behavior is acceptable when:
1. inner-loop convergence metric drops below tolerance across slices,
2. signal traces are stable and interpretable,
3. reporting-year gating behavior matches design intent,
4. OD outer loop converges when enabled,
5. convergence is achieved without extreme clipping dependence,
6. documented coupling simplification risks are acknowledged (`R-CPG-01`, `R-OD-01`, `R-CAP-01`).

## 11) Related sections

- [ARCHITECTURE.md §7](./ARCHITECTURE.md#7-coupling-logic-inner-outer-loops) for architecture-level coupling overview.
- [INDICATORS.md §5](./INDICATORS.md#5-coupling-diagnostics-interpretation-dedicated-section) for coupling diagnostics interpretation.
- [OD_TRADE_MODULE.md §2.2](./OD_TRADE_MODULE.md#22-endogenous-outer-loop-placement) for OD outer-loop placement details.
- [SCENARIOS.md §3](../workflows/SCENARIOS.md#3-how-scenario-variants-are-executed-in-runtime) for scenario runtime ordering around coupling.
