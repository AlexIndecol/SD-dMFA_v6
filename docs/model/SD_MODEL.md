# SD Model Operational Guide

This document operationalizes the SD sections in `docs/model/ARCHITECTURE.md`.
It is aligned to the implemented SD runtime in:
- `src/crm_model/sd/bptk_model.py`
- `src/crm_model/sd/run_sd.py`
- SD parameter normalization/validation in `src/crm_model/sd/params.py`

## Document position

- You are here: Tier 2 canonical module deep-dive (SD).
- Canonical scope: SD dynamics, mechanism-to-equation mapping, controls, diagnostics, and tuning guidance.
- Out of scope: full MFA conservation mechanics and full scenario catalog documentation.
- Related docs: [ARCHITECTURE.md](./ARCHITECTURE.md), [MFA_MODEL.md](./MFA_MODEL.md), [COUPLING_LOGIC.md](./COUPLING_LOGIC.md), [INDICATORS.md](./INDICATORS.md), [SCENARIOS.md](../workflows/SCENARIOS.md), [CONFIGS.md](../workflows/CONFIGS.md)

## 1) Purpose and boundary

Purpose:
- explain the implemented SD mechanisms controlling demand, scarcity/price, capacity, collection, and reserve intents,
- provide practical design/tuning guidance for scenario work.

Boundary:
- SD is a behavioral/dynamic layer; physical conservation is handled in dMFA,
- SD consumes demand and feedback signals, then returns demand and control intents to coupling/dMFA.

## 2) Mechanism structure and equation map

Section `2.x` is mechanism-first and self-contained; section 3 is a fast lookup index for the same `Eq-*` IDs.

### 2.1 Scarcity-price-demand channel

How to read this mechanism:
- coupling stress enters first, then bottleneck amplification affects scarcity and price, then demand response gate applies.

What happens:
1. Coupling provides `scarcity_multiplier`.
2. Bottlenecks amplify it to `scarcity_multiplier_effective`.
3. Price responds to effective scarcity.
4. Demand response applies only after `demand_response_start_year`.

Equation card:
- `Eq-SD-01`: `scarcity_multiplier_effective = scarcity_multiplier * (1 + bottleneck_scarcity_gain * bottleneck_pressure)`
- `Eq-SD-02`: `price = price_base * (1 + price_scarcity_sensitivity * (scarcity_multiplier_effective - 1))`
- `Eq-SD-03`: `price_ratio = price / max(price_base, eps)`
- `Eq-SD-04`: `demand_price_elasticity_eff = 0 if current_year < demand_response_start_year else demand_price_elasticity`
- `Eq-SD-05`: `demand = demand_desired * max(0, 1 - demand_price_elasticity_eff * (price_ratio - 1))`

Symbol notes:
- `scarcity_multiplier`: coupling-driven scarcity baseline.
- `price_ratio`: relative price pressure channel used by multiple loops.

Practical controls:
- `price_base`
- `price_scarcity_sensitivity`
- `demand_price_elasticity`
- `demand_response_start_year`

Diagnostics to watch:
- `SD_scarcity_multiplier_effective`
- `SD_price`
- `Service_demand`

### 2.2 Capacity envelope and bottleneck loop

How to read this mechanism:
- utilization creates bottlenecks, bottlenecks create capacity pressure, and lagged adjustment closes the loop.

What happens:
1. Flow capacity is set by exogenous demand scale and envelope.
2. Utilization > 1 creates bottleneck pressure.
3. Capacity pressure combines shortage and price channels.
4. Capacity target is bounded and smoothed into realized envelope.

Equation card:
- `Eq-SD-06`: `flow_capacity = max(eps, demand_exogenous * max(capacity_envelope, eps))`
- `Eq-SD-07`: `flow_utilization = demand_desired / flow_capacity`
- `Eq-SD-08`: `bottleneck_pressure = max(0, flow_utilization - 1)`
- `Eq-SD-09`: `capacity_pressure = capacity_pressure_shortage_weight * bottleneck_pressure + (1 - capacity_pressure_shortage_weight) * max(0, price_ratio - 1)`
- `Eq-SD-10`: `capacity_target_raw = 1 + capacity_expansion_gain * capacity_pressure - capacity_retirement_gain * max(0, 1 - price_ratio)`
- `Eq-SD-11`: `capacity_target = clamp(capacity_target_raw, capacity_envelope_min, capacity_envelope_max)`
- `Eq-SD-12`: `capacity_envelope = smooth(capacity_target, capacity_adjustment_lag_years, capacity_envelope_initial)`

Symbol notes:
- `capacity_envelope`: aggregate capacity index, not explicit plant stock.
- `capacity_pressure_shortage_weight`: blend between physical shortage and price pressure.

Practical controls:
- `capacity_envelope_initial`, `capacity_envelope_min`, `capacity_envelope_max`
- `capacity_expansion_gain`, `capacity_retirement_gain`
- `capacity_adjustment_lag_years`
- `capacity_pressure_shortage_weight`
- `bottleneck_scarcity_gain`

Diagnostics to watch:
- `SD_flow_utilization`
- `SD_bottleneck_pressure`
- `SD_capacity_envelope`

### 2.3 Collection response loop

How to read this mechanism:
- price/bottleneck define target collection pressure, then bounds and lag shape realized response.

What happens:
1. Price pressure raises collection target.
2. Bottleneck can throttle collection responsiveness.
3. Target is clipped to configured bounds.
4. Realized multiplier is direct or lagged.

Equation card:
- `Eq-SD-13`: `collection_bottleneck_throttle = 1 / (1 + bottleneck_collection_sensitivity * bottleneck_pressure)`
- `Eq-SD-14`: `collection_multiplier_target_raw = (1 + collection_price_response_gain * max(0, price_ratio - 1)) * collection_shock_mult * collection_bottleneck_throttle`
- `Eq-SD-15`: `collection_multiplier_target = clamp(collection_multiplier_target_raw, collection_multiplier_min, collection_multiplier_max)`
- `Eq-SD-16`: `collection_multiplier = collection_multiplier_target (if lag<=0) else smooth(collection_multiplier_target, collection_multiplier_lag_years)`

Symbol notes:
- `collection_shock_mult`: scenario-driven shock multiplier channel.
- `collection_multiplier`: final SD output used to scale dMFA base collection rate.

Practical controls:
- `collection_price_response_gain`
- `collection_multiplier_min`, `collection_multiplier_max`
- `collection_multiplier_lag_years`
- `bottleneck_collection_sensitivity`

Diagnostics to watch:
- `Coupling_collection_multiplier`
- `SD_collection_bottleneck_throttle`
- `Collection_rate_effective`

### 2.4 Strategic reserve intent policy

How to read this mechanism:
- fill intent is coverage-gap/low-stress logic; release intent is emergency-pressure logic.

What happens:
1. Fill channel activates when price/service thresholds allow reserve build.
2. Release channel activates when service or price pressure exceeds release thresholds.
3. Both channels are clipped and gated by reserve enable flag.

Equation card:
- `Eq-SD-17`: `strategic_coverage_gap = max(0, strategic_reserve_target_coverage_years - strategic_stock_coverage_years)`
- `Eq-SD-18`: `strategic_fill_active = 1 if (price_ratio <= fill_price_threshold and service_stress_signal <= fill_service_threshold) else 0`
- `Eq-SD-19`: `strategic_fill_intent = clamp(min(strategic_reserve_max_fill_rate, strategic_reserve_fill_gain * strategic_coverage_gap) if strategic_fill_active else 0, 0, 1)` (and 0 if reserve disabled)
- `Eq-SD-20`: `strategic_emergency_pressure = max(0, max(service_stress_signal - release_service_threshold, price_ratio - release_price_threshold))`
- `Eq-SD-21`: `strategic_release_intent = clamp(min(strategic_reserve_max_release_rate, strategic_reserve_release_gain * strategic_emergency_pressure), 0, 1)` (and 0 if reserve disabled)

Symbol notes:
- `strategic_stock_coverage_years`: coupling signal from dMFA reserve stock relative to service demand.

Practical controls:
- `strategic_reserve_enabled`
- `strategic_reserve_target_coverage_years`
- `strategic_reserve_fill_*`
- `strategic_reserve_release_*`

Diagnostics to watch:
- `Strategic_fill_intent`
- `Strategic_release_intent`
- `Strategic_inventory_stock`

## 3) Consolidated equation reference

Each equation ID below is defined in section 2 equation cards; use `Source` to trace the mechanism block.

| Equation ID | Formula | Source | Interpretation |
|---|---|---|---|
| `Eq-SD-01` | `scarcity_multiplier_effective = scarcity_multiplier * (1 + bottleneck_scarcity_gain * bottleneck_pressure)` | `2.1` | Bottleneck-amplified scarcity channel. |
| `Eq-SD-02` | `price = price_base * (1 + price_scarcity_sensitivity * (scarcity_multiplier_effective - 1))` | `2.1` | Scarcity-to-price transmission. |
| `Eq-SD-03` | `price_ratio = price / max(price_base, eps)` | `2.1` | Normalized price pressure with denominator guard. |
| `Eq-SD-04` | `demand_price_elasticity_eff = 0 if current_year < demand_response_start_year else demand_price_elasticity` | `2.1` | Calendar gating of demand response. |
| `Eq-SD-05` | `demand = demand_desired * max(0, 1 - demand_price_elasticity_eff * (price_ratio - 1))` | `2.1` | Realized demand after price response. |
| `Eq-SD-06` | `flow_capacity = max(eps, demand_exogenous * max(capacity_envelope, eps))` | `2.2` | Capacity surface that sets utilization denominator. |
| `Eq-SD-07` | `flow_utilization = demand_desired / flow_capacity` | `2.2` | Utilization pressure indicator. |
| `Eq-SD-08` | `bottleneck_pressure = max(0, flow_utilization - 1)` | `2.2` | Bottleneck activation function. |
| `Eq-SD-09` | `capacity_pressure = capacity_pressure_shortage_weight * bottleneck_pressure + (1 - capacity_pressure_shortage_weight) * max(0, price_ratio - 1)` | `2.2` | Blended capacity pressure driver. |
| `Eq-SD-10` | `capacity_target_raw = 1 + capacity_expansion_gain * capacity_pressure - capacity_retirement_gain * max(0, 1 - price_ratio)` | `2.2` | Raw expansion/retirement response. |
| `Eq-SD-11` | `capacity_target = clamp(capacity_target_raw, capacity_envelope_min, capacity_envelope_max)` | `2.2` | Bounded target envelope. |
| `Eq-SD-12` | `capacity_envelope = smooth(capacity_target, capacity_adjustment_lag_years, capacity_envelope_initial)` | `2.2` | Delayed envelope adjustment. |
| `Eq-SD-13` | `collection_bottleneck_throttle = 1 / (1 + bottleneck_collection_sensitivity * bottleneck_pressure)` | `2.3` | Bottleneck damping on collection response. |
| `Eq-SD-14` | `collection_multiplier_target_raw = (1 + collection_price_response_gain * max(0, price_ratio - 1)) * collection_shock_mult * collection_bottleneck_throttle` | `2.3` | Raw collection pressure target. |
| `Eq-SD-15` | `collection_multiplier_target = clamp(collection_multiplier_target_raw, collection_multiplier_min, collection_multiplier_max)` | `2.3` | Bounded collection target. |
| `Eq-SD-16` | `collection_multiplier = collection_multiplier_target (if lag<=0) else smooth(collection_multiplier_target, collection_multiplier_lag_years)` | `2.3` | Realized collection response with lag option. |
| `Eq-SD-17` | `strategic_coverage_gap = max(0, strategic_reserve_target_coverage_years - strategic_stock_coverage_years)` | `2.4` | Reserve coverage shortfall signal. |
| `Eq-SD-18` | `strategic_fill_active = 1 if (price_ratio <= fill_price_threshold and service_stress_signal <= fill_service_threshold) else 0` | `2.4` | Fill permission condition. |
| `Eq-SD-19` | `strategic_fill_intent = clamp(min(max_fill_rate, fill_gain * coverage_gap) if fill_active else 0, 0, 1)` | `2.4` | Fill intent output (enable-gated). |
| `Eq-SD-20` | `strategic_emergency_pressure = max(0, max(service_stress_signal - release_service_threshold, price_ratio - release_price_threshold))` | `2.4` | Emergency pressure driver. |
| `Eq-SD-21` | `strategic_release_intent = clamp(min(max_release_rate, release_gain * strategic_emergency_pressure), 0, 1)` | `2.4` | Release intent output (enable-gated). |

## 4) Parameter and control surfaces

Primary controls are in `sd_parameters` (run/scenario/overrides):

Scarcity-price-demand:
1. `price_base`
2. `price_scarcity_sensitivity`
3. `demand_price_elasticity`

Capacity and bottlenecks:
4. `capacity_envelope_initial`
5. `capacity_envelope_min`, `capacity_envelope_max`
6. `capacity_expansion_gain`
7. `capacity_retirement_gain`
8. `capacity_adjustment_lag_years`
9. `capacity_pressure_shortage_weight`
10. `bottleneck_scarcity_gain`
11. `bottleneck_collection_sensitivity`

Collection:
12. `collection_price_response_gain`
13. `collection_multiplier_min`, `collection_multiplier_max`
14. `collection_multiplier_lag_years`

Coupling stabilization:
15. `coupling_service_stress_gain`
16. `coupling_circular_supply_stress_gain`
17. `coupling_signal_smoothing`
18. `coupling_signal_smoothing_strategic`
19. `service_stress_signal_cap`
20. `coupling_stress_multiplier_cap`

Strategic reserve intent controls:
21. `strategic_reserve_enabled`
22. `strategic_reserve_target_coverage_years`
23. `strategic_reserve_fill_gain`, `strategic_reserve_release_gain`
24. `strategic_reserve_max_fill_rate`, `strategic_reserve_max_release_rate`
25. `strategic_reserve_fill_price_threshold`, `strategic_reserve_release_price_threshold`
26. `strategic_reserve_fill_service_threshold`, `strategic_reserve_release_service_threshold`

Practical guardrails:
- keep envelope min <= envelope max,
- keep multipliers and lags within plausible ranges,
- tune gains and delays gradually to avoid oscillations.

## 5) Scenario design and stress-testing workflow

Recommended SD stress protocol:
1. Baseline stability run.
2. Crunch window (demand surge and/or supply pressure).
3. Recovery window (remove shock, keep same SD parameters).
4. Evaluate bottleneck, price, capacity-envelope, and convergence behavior.

Pattern examples:
- acute demand shock to trigger utilization/bottlenecks,
- import squeeze to test scarcity and recovery,
- delayed policy ramps to test smooth adoption impacts,
- collection shock and throttle response tests.

Use reporting-phase gates by default for strong SD overrides.

## 6) Output interpretation and diagnostics

Key SD fields in indicator outputs:
- `SD_scarcity_multiplier_effective`
- `SD_capacity_envelope`
- `SD_flow_utilization`
- `SD_bottleneck_pressure`
- `SD_collection_bottleneck_throttle`
- `Coupling_collection_multiplier`
- `SD_price`

Interpretation:
1. Crunch phase should show rising utilization, bottleneck, and price.
2. Recovery should show delayed capacity rise and pressure relaxation.
3. If price stays elevated post-recovery, inspect envelope caps and persistent scarcity signals.
4. If collection response stays flat, inspect throttle and min/max/lag settings.

## 7) Failure modes and troubleshooting

1. Flat SD response under strong shock:
- likely low bottleneck/capacity gains or high envelope headroom.

2. Oscillation/instability:
- gains too high relative to lag settings.

3. Over-damped response:
- smoothing or lag settings too strong.

4. Non-physical demand collapse:
- overly aggressive elasticity or scarcity amplification.

5. Strategic reserve overreaction:
- thresholds/gains too aggressive, causing pronounced feedback artifacts.

## 8) Calibration and tuning guidance

Practical sequence:
1. tune baseline stability and convergence first,
2. excite loop with realistic stress,
3. tune bottleneck intensity controls,
4. tune capacity response speed,
5. tune collection response,
6. tune strategic reserve intents last.

Calibration principles:
- keep historical phase conservative,
- avoid simultaneous broad parameter sweeps on strongly coupled controls,
- validate both fit and dynamic plausibility.

## 9) Interactions with other modules

With MFA:
- SD demand and collection multiplier affect dMFA demand and collection flows.
- Strategic intents affect strategic inventory allocation decisions in dMFA.

With coupling:
- SD receives stress/coverage signals from dMFA and returns updated stress-driven dynamics.

With transition policy and demand transformation:
- these modify demand and selected SD/MFA behavior before and during coupling cycles.

With OD trade:
- SD capacity envelope influences OD export-cap construction in endogenous trade mode.

## 10) Acceptance diagnostics and checklist

SD behavior is acceptable when:
1. stress-recovery signatures are present and plausible,
2. coupling convergence remains stable,
3. no persistent unexplained oscillation appears,
4. collection response behavior matches configured intent,
5. strategic reserve behavior is interpretable under configured thresholds,
6. documented simplification risks are acknowledged (`R-CAP-01`, `R-COL-01`, `R-DMD-01`, `R-RES-01`, `R-RES-02`).

## 11) Related sections

- [ARCHITECTURE.md §4-5](./ARCHITECTURE.md#4-sd-model-key-mechanisms-and-dynamics) for overview-level SD mechanisms and design implications.
- [INDICATORS.md §4](./INDICATORS.md#4-definitions-resilience_service_indicators-organized-by-logical-subsets) for SD-linked service and resilience indicators.
- [COUPLING_LOGIC.md §2](./COUPLING_LOGIC.md#2-mechanism-structure-and-equation-map) for SD feedback update behavior inside coupling.
- [SCENARIOS.md §3-5](../workflows/SCENARIOS.md#3-how-scenario-variants-are-executed-in-runtime) for runtime execution context of SD overrides.
