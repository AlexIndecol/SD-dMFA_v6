# BACI OD Matrices Assumptions and Diagnostics

This file mirrors the assumptions generated in:
`data/exogenous/trade_od/baci_od_assumptions.md`
and serves as the documentation-side source for Phase 0 trade data foundations.

## Scope
- Region OD matrix level: `EU27`, `China`, `RoW` (3x3).
- Materials: `nickel`, `tin`, `zinc`.
- Commodities: `concentrates`, `refined_metal`, `scrap`.
- Units: metric tons (`flow_kt`, annual flow semantics).

## BACI period bridge
- HS92 years: 1995-2021.
- HS22 years: 2022-2024.
- No year overlap between HS sources.

## Mapping reuse
- HS code mapping is reused from:
  - `scripts/data/build_baci_od_matrices.py` via the existing trade-observed mapping module.
- Includes strict codes + targeted ambiguous/intermediate codes with deterministic split shares.

## Weighting
- Annual OD share per origin: `s[t,o->d,m,c] = x_obs / sum_d x_obs`.
- Rolling preference weights: trailing 3-year mean over available annual shares.
- Fallback hierarchy:
1. Same-year global destination mix for `(t,m,c)`.
2. Uniform `[1/3, 1/3, 1/3]` when global mix unavailable.

- No weight fallback events were needed in the current generated dataset.

## Export ceiling and allocator
- Export cap quantile: `q=0.75`, trailing window `5` years.
- `exportable = min(supply_avail, export_cap_raw)`.
- Allocator:
1. Pass 0: `x0 = exportable * w`, then destination absorption scaling to `x1`.
2. Pass 1: one residual reallocation pass (`1` pass total) to produce `x_final`.

## Aggregate effect of constraints
- Total observed OD flow: 1,581,967,642.35 t
- Total constrained OD flow: 1,431,169,250.88 t
- Total reduction: 150,798,391.47 t (9.53%)

## Largest cap-induced deviations by year/material/commodity
- 2013 | nickel | concentrates: delta=24,831,299.79 t (23.29%)
- 2011 | nickel | concentrates: delta=23,424,912.06 t (37.00%)
- 2012 | nickel | concentrates: delta=18,325,248.77 t (22.46%)
- 2019 | nickel | concentrates: delta=15,540,426.03 t (21.63%)
- 2010 | nickel | concentrates: delta=13,788,050.25 t (34.51%)
- 2007 | nickel | concentrates: delta=11,652,626.73 t (45.61%)
- 2024 | zinc | refined_metal: delta=4,972,917.77 t (48.26%)
- 2006 | nickel | concentrates: delta=4,013,102.46 t (28.83%)
- 1999 | zinc | refined_metal: delta=3,061,655.78 t (41.89%)
- 2014 | tin | concentrates: delta=2,874,227.92 t (97.26%)
- 2018 | nickel | concentrates: delta=2,332,179.59 t (4.14%)
- 2006 | zinc | refined_metal: delta=1,818,528.71 t (25.40%)

