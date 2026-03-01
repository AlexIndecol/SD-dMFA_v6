# Endogenous Capacity-Scarcity-Price Loop With Bottleneck Delays

This note explains how to interpret, parameterize, and scenario-test the SD dynamic implemented in the BPTK layer.

## 1) Causal structure

Core reinforcing and balancing channels:

1. `capacity_envelope` sets effective flow capacity relative to exogenous desired demand.
2. Higher demand pressure raises `flow_utilization`.
3. If `flow_utilization > 1`, bottleneck pressure appears (`bottleneck_pressure`).
4. Bottlenecks amplify effective scarcity (`scarcity_multiplier_effective`).
5. Higher scarcity raises `price` (via scarcity-price sensitivity).
6. Higher price and bottleneck pressure increase `capacity_target`.
7. `capacity_envelope` moves to `capacity_target` with a delay (`capacity_adjustment_lag_years`).
8. As capacity catches up, bottleneck pressure relaxes.

Collection dynamics are coupled into the same stress:

1. Price pressure increases collection target.
2. Bottleneck pressure can throttle collection response (`collection_bottleneck_throttle`).
3. Bounded + lagged collection multiplier feeds effective dMFA collection rate.

## 2) Equation-level interpretation

Key SD equations (conceptually):

- `flow_capacity = demand_exogenous * capacity_envelope`
- `flow_utilization = demand_desired / flow_capacity`
- `bottleneck_pressure = max(0, flow_utilization - 1)`
- `scarcity_effective = scarcity_multiplier * (1 + bottleneck_scarcity_gain * bottleneck_pressure)`
- `price = price_base * (1 + price_scarcity_sensitivity * (scarcity_effective - 1))`
- `capacity_pressure = w_shortage * bottleneck_pressure + (1 - w_shortage) * max(0, price_ratio - 1)`
- `capacity_target_raw = 1 + capacity_expansion_gain * capacity_pressure - capacity_retirement_gain * max(0, 1 - price_ratio)`
- `capacity_target = clamp(capacity_target_raw, capacity_envelope_min, capacity_envelope_max)`
- `capacity_envelope = smooth(capacity_target, capacity_adjustment_lag_years, capacity_envelope_initial)`

Collection sub-loop:

- `collection_bottleneck_throttle = 1 / (1 + bottleneck_collection_sensitivity * bottleneck_pressure)`
- `collection_multiplier_target_raw = (1 + collection_price_response_gain * max(0, price_ratio - 1)) * collection_shock_mult * collection_bottleneck_throttle`
- `collection_multiplier_target = clamp(collection_multiplier_target_raw, collection_multiplier_min, collection_multiplier_max)`
- `collection_multiplier = lag(collection_multiplier_target, collection_multiplier_lag_years)`

## 3) Parameter roles

Capacity/scarcity/price controls:

- `price_scarcity_sensitivity`: scarcity -> price amplification.
- `capacity_expansion_gain`: price/shortage pressure -> capacity expansion intensity.
- `capacity_retirement_gain`: low-price pressure -> capacity down-adjustment.
- `capacity_adjustment_lag_years`: delay from pressure to realized capacity.
- `capacity_pressure_shortage_weight`: weight on physical bottleneck vs price channel.
- `capacity_envelope_min/max`: hard envelope bounds.
- `bottleneck_scarcity_gain`: bottleneck -> scarcity amplification.
- `bottleneck_collection_sensitivity`: bottleneck -> collection throttling.

Collection response controls:

- `collection_price_response_gain`
- `collection_multiplier_min/max`
- `collection_multiplier_lag_years`

Coupling realism/stability controls:

- `service_stress_signal_cap`: upper cap applied to the service-stress coupling signal before stress amplification.
- `coupling_stress_multiplier_cap`: hard cap on computed stress multiplier.
- `coupling_signal_smoothing_strategic`: smoothing applied only to strategic-stock coverage feedback (separate from general coupling smoothing).

## 4) How to model scenarios

Use shocks to excite the loop, then rely on endogenous recovery:

1. Shock demand (`demand_surge`) and/or tighten primary availability.
2. Keep recovery endogenous by ending shocks while retaining capacity dynamics.
3. Use `capacity_adjustment_lag_years` and `capacity_expansion_gain` to tune recovery speed.
4. Use bottleneck gains to tune crisis severity and collection friction.

Recommended stress-test design:

1. Baseline run.
2. Crunch window (demand up + primary down).
3. Recovery window (shocks removed, same SD parameters).
4. Compare `final_bottleneck_pressure_mean`, `final_capacity_envelope_mean`, convergence flags.

Practical scenario examples in this repo:

1. `capacity_crunch_recovery`: pure crunch-recovery loop excitation.
2. `import_squeeze_circular_ramp`: external import squeeze with delayed circular/policy response ramp.

## 5) How to interpret outputs

During crunch:

- `SD_flow_utilization` and `SD_bottleneck_pressure` should rise.
- `SD_scarcity_multiplier_effective` and `SD_price` should peak.
- `Collection_rate_effective` may rise less than expected if bottleneck throttle is active.

During recovery:

- `SD_capacity_envelope` should rise with delay.
- `SD_bottleneck_pressure` should decline as capacity catches up.
- `SD_price` should partially/fully relax depending on envelope bounds and exogenous scarcity.

## 6) Common failure modes

1. Flat bottleneck pressure:
   - demand shock too weak, primary constraints too loose, or capacity max too high.
2. Non-activation under stress:
   - `bottleneck_scarcity_gain` / `capacity_expansion_gain` too low.
3. Oscillatory behavior:
   - lag too short with gains too high.
4. Slow/no recovery:
   - lag too long or envelope max too tight.

## 7) Calibration guidance

When calibrating with this dynamic:

1. Keep historic phase conservative; avoid aggressive gates before reporting.
2. Constrain gains and lags to plausible ranges before tuning shocks.
3. Validate both fit and dynamic plausibility (pressure peak + delayed capacity response + relaxation).

## 8) Interaction with other SD and strategy mechanisms

### Operational refinery stockpile (`refinery_stockpile_native`)

1. Higher bottleneck pressure can raise price and collection pressure, but realized collection response can still be throttled by `collection_bottleneck_throttle`.
2. If collection and recycling are strong, secondary inflow to refining can increase stockpile build, which then buffers later years through `refinery_stockpile_release_rate`.
3. A high fixed release rate can mask some bottleneck severity by softening unmet service during crunch years.

### Strategic reserve (`strategic_inventory_native`)

1. Strategic fill diverts material from current availability and can deepen near-term scarcity if thresholds and gains are aggressive.
2. Strategic release can reduce service stress and moderate the effective scarcity multiplier in crisis years.
3. Reserve policy can therefore damp or amplify apparent loop intensity depending on trigger thresholds and timing.

### Coupling feedback and SD heterogeneity

1. The loop operates on top of coupling stress inputs (`service_stress`, `circular_supply_stress`), so convergence/smoothing settings change apparent loop activation.
2. Slice-level SD heterogeneity can create different activation thresholds for the same shock profile across material-region slices.

### Transition-policy and demand-transformation loops

1. `transition_policy` introduces an adoption stock with start year, compliance delay, and lagged ramp to a target adoption share.
2. As adoption rises, policy can:
   - increase baseline collection and recycling yield,
   - increase capacity expansion responsiveness,
   - reduce bottleneck amplification gains.
3. `demand_transformation` modifies exogenous demand before coupling by combining:
   - optional service-activity and material-intensity drivers,
   - scenario multipliers,
   - efficiency improvement and rebound,
   - optional coupling to transition adoption (`transition_adoption_weight`).
4. This creates a second demand-side loop interacting with price elasticity:
   transformed desired demand -> utilization/bottlenecks -> scarcity/price -> realized demand and capacity response.

## 9) Practical tuning sequence

1. Tune baseline stability first (`coupling_converged`, low drift vs previous baseline).
2. Excite loop via scenario stress (demand up and/or primary down) before increasing gains.
3. Tune bottleneck intensity (`bottleneck_scarcity_gain`, `bottleneck_collection_sensitivity`).
4. Tune capacity response speed (`capacity_expansion_gain`, `capacity_adjustment_lag_years`).
5. Re-check interaction with stockpile and strategic reserve controls.

## 10) Acceptance diagnostics for loop quality

For a stress-recovery scenario:

1. Crunch window: `SD_bottleneck_pressure`, `SD_flow_utilization`, and `SD_price` should rise.
2. Recovery window: `SD_capacity_envelope` should rise with delay and `SD_bottleneck_pressure` should relax.
3. Convergence: all slices should remain converged under configured tolerance.
4. Interaction sanity: strategic and stockpile channels should explain, not obscure, major deviations.
