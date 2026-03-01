# Troubleshooting

This guide focuses on common runtime and interpretation failures in the coupled SD-dMFA workflow.

## 1) `coupling_converged == False`

Symptoms:

- `summary.csv` shows non-converged slices.
- `coupling_convergence_iteration.csv` has `max_signal_delta` plateauing above tolerance.

Checks:

1. Verify shock severity is not unrealistically high for current gains.
2. Inspect `Coupling_service_stress` and `Coupling_circular_supply_stress` volatility by iteration.
3. Confirm `coupling_signal_smoothing` is not too low for stressed runs.

Typical fixes:

1. Increase smoothing moderately.
2. Reduce aggressive SD gains (`capacity_expansion_gain`, bottleneck gains) before changing coupling mode.
3. Ensure scenario gates begin in reporting years unless intentionally historical.

## 2) Capacity/bottleneck loop does not activate

Symptoms:

- `SD_bottleneck_pressure` stays ~0 even in stress scenarios.
- `SD_price` and `SD_capacity_envelope` remain flat.

Checks:

1. Stress window is long/strong enough (demand up and/or primary down).
2. `capacity_envelope_max` is not already too high.
3. Bottleneck gains are non-zero.

Typical fixes:

1. Increase stress amplitude or reduce primary availability.
2. Lower baseline envelope headroom.
3. Increase `bottleneck_scarcity_gain` carefully.

## 3) Activation floor failed (default + fallbacks)

Meaning:

- Even after fallback parameter sets, no slice crossed the minimum activation criterion
  (for example `final_bottleneck_pressure_mean > 0.005`).

Interpretation:

1. The loop is present but under-excited by current data and shock profile.
2. Dynamics are too damped by envelope headroom, low stress intensity, or conservative gains.

Actions:

1. Verify stress scenario is actually being applied to intended slices.
2. Strengthen stress window before increasing gains further.
3. Re-check that fallback logic changed the expected keys.
4. Document the non-activation and keep defaults conservative if baseline drift constraints are priority.

## 4) Large baseline drift after SD tuning

Symptoms:

- Baseline summary metrics shift beyond tolerance after parameter updates.

Checks:

1. Compare before/after `summary.csv` per slice.
2. Focus on `final_stress_multiplier`, `final_collection_rate_mean`, `final_service_stress_signal`.

Typical fixes:

1. Roll back bottleneck gains first.
2. Then roll back capacity response aggressiveness.
3. Preserve bounded collection controls to avoid runaway multipliers.

## 5) Unexpected scenario behavior in historic years

Symptoms:

- Scenario overrides affecting pre-report years.

Checks:

1. Search scenario for year-gates with `start_year < report_start_year`.
2. Confirm inherited overrides are not injected from run/base layers unexpectedly.

Typical fixes:

1. Shift scenario gates to reporting start.
2. Keep historic phase as reconstruction-only baseline.

## 6) Mass-balance diagnostics are non-trivial

Symptoms:

- `Mass_balance_residual_max_abs` too high for some slices.

Checks:

1. Validate exogenous routing rates and stage yields.
2. Check that routing rates normalize to 1 by year/material/region.
3. Inspect scenario routing shocks for unintended combinations.

Typical fixes:

1. Correct exogenous input inconsistencies first.
2. Simplify scenario overrides and reintroduce complexity incrementally.

## 7) Strategic reserve dominates service outcomes

Symptoms:

- Reserve fill/release decisions overshadow intended scenario effects.

Checks:

1. `strategy.strategic_reserve_enabled` status.
2. Thresholds and fill/release gains.
3. `Coupling_strategic_stock_coverage_signal` trajectory.

Typical fixes:

1. Disable reserve for baseline calibration and mechanism-isolation tests.
2. Tune thresholds before gains.
3. Re-enable once baseline behavior is stable.
