# Quickstart

This guide gives a minimal, reproducible path from baseline run to scenario comparison.

## 1) Validate config + exogenous inputs

```bash
PYTHONPATH=src python scripts/validation/lint_run_configs.py
PYTHONPATH=src python scripts/validation/validate_exogenous_inputs.py --config configs/runs/mvp.yml
```

## 2) Run baseline (reporting phase)

```bash
PYTHONPATH=src python scripts/run_one.py \
  --config configs/runs/mvp.yml \
  --variant baseline \
  --phase reporting \
  --save-csv
```

Output root:

`outputs/runs/mvp/baseline/<timestamp>/`

## 3) Run a stress scenario targeting SD capacity/scarcity loop

```bash
PYTHONPATH=src python scripts/run_one.py \
  --config configs/runs/mvp.yml \
  --variant capacity_crunch_recovery \
  --phase reporting \
  --save-csv
```

## 4) Run all variants in the run pack

```bash
PYTHONPATH=src python scripts/run_batch.py \
  --config configs/runs/mvp.yml \
  --save-csv
```

## 5) Build scenario comparison package

```bash
PYTHONPATH=src python scripts/analysis/compare_scenarios.py --config configs/runs/mvp.yml
PYTHONPATH=src python scripts/analysis/plots/plot_scenario_subset_panels.py --config configs/runs/mvp.yml
```

Outputs:

`outputs/analysis/scenario_comparison/mvp/latest/`

## 6) Minimum acceptance checks

1. `summary.csv` shows `coupling_converged == True` for each material-region slice.
2. Stress scenarios have higher `final_bottleneck_pressure_mean` than baseline in expected slices.
3. `indicators/coupling_convergence_iteration.csv` has final `max_signal_delta < convergence_tol`.

## 7) When runs fail or behave unexpectedly

Use [TROUBLESHOOTING.md](./TROUBLESHOOTING.md), especially sections on:

- non-convergence,
- inactive bottleneck loop,
- activation-floor failure.
