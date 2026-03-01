# Calibration Notes

This file captures high-value calibration clarifications for this repository.

## 1) What the calibration objective is actually fitting

- The calibration objective is based on **observed stock-in-use fit** (train/validation windows from `configs/calibration.yml`).
- `stock_in_use.csv` is used for metrics only; it does not directly drive dMFA state equations.
- `final_demand.csv` is exogenous desired demand. During calibration years (`year < report_start_year`), SD demand response is forced off, so modeled demand follows the exogenous series.

Implication:
- It is possible for final demand (modeled vs observed proxy) to match closely while primary production use and stock-in-use fit remain imperfect.
- Strategic reserve mechanism should remain disabled (`strategy.strategic_reserve_enabled=false`) during baseline calibration to avoid confounding stock-fit objective with policy inventory dynamics.

## 2) Why production and stock can diverge from observed

Even with good demand alignment, modeled production and in-use stock remain endogenous outcomes of:
- fabrication yield and collection/routing constraints
- recycling/remanufacturing yields and refinery stockpile dynamics
- lifetime distributions and lifetime multiplier
- primary availability constraint (`primary_available_to_refining`)
- upstream stage yields/loss routing (`stage_yields_losses.csv`)
- iterative SD-dMFA coupling stress feedback

When misfit remains after parameter tuning, the residual is often **structural** (missing mechanisms/data detail), not only a poor scalar parameter choice.

## 3) `mfa_parameters` vs `strategy` and precedence

- `mfa_parameters`: core MFA parameter values (base inputs).
- `strategy`: policy/behavioral overrides used by scenarios and runtime controls.

For overlapping keys, runtime takes `strategy` first, then falls back to `mfa_parameters`.
Examples in runtime:
- `recycling_yield = strategy.get("recycling_yield", params.get("recycling_yield", ...))`
- `reman_yield = strategy.get("reman_yield", params.get("reman_yield", ...))`
- routing rates (`recycling_rate`, `remanufacturing_rate`, `disposal_rate`) resolve `strategy` before `params`.

Guideline:
- Avoid duplicating the same key in both blocks unless the override is intentional.

## 4) Lifetime distributions: required parameterization

`data/exogenous/lifetime_distributions.csv` is validated strictly (duplicates/invalid parameterization fail fast).

Accepted families and required fields:
- `fixed`: requires `mean_years`
- `weibull`: requires `shape` and one of `{scale, mean_years}`
- `lognormal`: requires `sigma` and one of `{mu, mean_years}`

Switching family from Weibull to Lognormal in CSV:
- change `dist` from `weibull` to `lognormal`
- replace Weibull-only parameter `shape` with Lognormal `sigma`
- keep/provide `mean_years` (or provide `mu`)

## 5) What `lifetime_multiplier` does

`lifetime_multiplier` scales lifetime duration after parameterization:
- `> 1.0`: longer average service life (slower retirements)
- `< 1.0`: shorter average service life (faster retirements)

Applied in adapter logic:
- Weibull: scales the effective `scale`
- Lognormal: scales the effective mean and standard deviation
- Must always remain `> 0`

## 6) Global vs region-material-specific calibration

Global-only parameters are stable and interpretable but can underfit slices (for example EU-specific behavior).

Current preferred approach is hybrid:
- calibrate a small global core
- add selected region-material slice adjustments through `parameters.slice_adjustments` in `configs/calibration.yml`
- materialize slice changes via `dimension_overrides` during evaluation/export

## 7) Lessons learned (this iteration)

- **Data quality beats optimizer effort.** Fixing observed stock units had larger impact than tuning additional optimizer settings.
- **Global-only calibration is robust but can leave regional bias.** EU-specific stock misfit improved only after introducing slice-level adjustments.
- **Parameter overlap creates confusion if not explicit.** Keeping the same key in both `mfa_parameters` and `strategy` is error-prone unless intended as an override.
- **Distribution-family switches require schema-consistent CSV edits.** Moving from Weibull to Lognormal requires both `dist` and parameter-name changes (`shape` -> `sigma`).
- **Residual error can be structural.** After a point, tuning yields diminishing returns unless model structure/data granularity is improved.

## 8) Further improvements (next calibration increments)

- **Reduce overlap ambiguity:** move duplicated runtime knobs to a single canonical block where possible, and keep only intentional overrides in `strategy`.
- **Strengthen identifiability controls:** calibrate in stages (global core first, then limited slice adjustments) and keep parameter sets minimal.
- **Add richer slice diagnostics:** export per material-region contribution to objective and residual decomposition by driver (lifetime/routing/primary constraint).
- **Improve structural realism where bias persists:** prioritize EU-focused mechanisms (trade detail, end-use split quality, and reman eligibility realism) before adding many new free parameters.
- **Harden calibration QA:** add a preflight check that asserts expected units/scales for observed stock and key exogenous inputs before optimization starts.

## 9) Simplified calibration cycle (current default)

To keep calibration runtime practical for iterative model development, the default spec was simplified:

- `configs/calibration.yml` is now the **fast baseline cycle** (global core parameters only, lower evaluation budget, local refinement off by default).
- `configs/calibration_full.yml` keeps the previous **high-budget** setup (including slice adjustments) for deeper runs.

Operational improvements in `scripts/calibration/calibrate_model.py`:

- **Live artifacts at run start**: run directory is created immediately.
- **Checkpointing during search**: partial outputs are written every `outputs.autosave_every_evaluations`.
- **Interrupt-safe behavior**: interrupted runs keep best-so-far artifacts/metadata.
- **Patience stopping active**: `optimization.stopping.min_improvement` + `patience_rounds` are now enforced in DE callback.
- **Optional wall-clock cap**: `--max-runtime-minutes` stops search and keeps best-so-far.

Recommended commands:

```bash
# Fast/default cycle
PYTHONPATH=src python scripts/calibration/calibrate_model.py \
  --config configs/runs/mvp.yml \
  --calibration-spec configs/calibration.yml \
  --variant baseline \
  --max-runtime-minutes 90

# Full/high-budget cycle
PYTHONPATH=src python scripts/calibration/calibrate_model.py \
  --config configs/runs/mvp.yml \
  --calibration-spec configs/calibration_full.yml \
  --variant baseline
```

## 10) Upstream stage-yield fitting workflow

For upstream diagnostics alignment, use:

```bash
PYTHONPATH=src python scripts/calibration/fit_stage_yields_losses.py \
  --run-config configs/runs/mvp.yml \
  --variant baseline \
  --output-stage-file data/exogenous/stage_yields_losses_v3.csv \
  --outdir data/exogenous/diagnostics/stage_yield_fit_v3 \
  --pair-specific-smoothing
```

This produces:
- `data/exogenous/stage_yields_losses_v3.csv` (new fitted file)
- diagnostics under `data/exogenous/diagnostics/stage_yield_fit_v3/`
- candidate diagnostics for selection and guardrail checks.

Region-targeted constrained mode (per-region lambdas):

```bash
PYTHONPATH=src python scripts/calibration/fit_stage_yields_losses.py \
  --run-config configs/runs/mvp.yml \
  --variant baseline \
  --region-targeted \
  --region-hard-constraint \
  --output-stage-file data/exogenous/stage_yields_losses_v3_region.csv \
  --outdir data/exogenous/diagnostics/stage_yield_fit_v3_region
```

This produces:
- `data/exogenous/stage_yields_losses_v3_region.csv`
- diagnostics under `data/exogenous/diagnostics/stage_yield_fit_v3_region/`.

Promotion pattern:
- replace `data/exogenous/stage_yields_losses.csv` with the selected fitted file
- move superseded stage-yield files to `data/exogenous/_archive/<date>/`.

Observed-vs-modeled comparisons are centered on:
- `primary_refined_observed.csv`
- `beneficiation_output_observed.csv`
- `primary_extraction_observed.csv`

`primary_refined_output.csv` is the canonical primary availability series in plotting workflows.

## 11) Should SD dynamics be included in calibration?

Short answer: include them selectively, in stages.

Pros:

1. Better dynamic realism for reporting-phase stress behavior.
2. Parameters become consistent with intended coupling and scarcity-response behavior.
3. Reduces risk of post-calibration retuning that breaks calibrated baselines.

Cons:

1. Larger parameter space reduces identifiability.
2. Higher risk of overfitting dynamics to limited observed targets.
3. Longer runtime and less stable optimization in highly coupled settings.

Recommended staged policy:

1. Stage A: calibrate core MFA fit parameters first (stock-fit objective primary).
2. Stage B: tune SD loop parameters with deterministic stress-test acceptance gates.
3. Stage C: optionally run constrained joint refinement on a small SD subset only.

Guardrails:

1. Keep strategic reserve disabled during baseline calibration.
2. Keep SD gates in reporting phase unless historical reconstruction is explicitly intended.
3. Require convergence and baseline-drift checks after any SD-parameter updates.
