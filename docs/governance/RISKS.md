# Risks & limitations

## Model-structure risks
- **Simplified secondary inventory policy:** secondary material is held in a refinery stockpile with an exogenous release-rate control; endogenous market/price-driven release behavior is not represented.
- **Strategic reserve trigger sensitivity:** SD reserve fill/release intents depend on threshold settings (price/service) and can materially change unmet-service timing.
- **Strategic release composition simplification:** strategic reserve is modeled as a single aggregate stock without explicit commodity-quality composition tracking.
- **Collection-response simplification:** dynamic collection uses bounded/lagged multipliers with price and bottleneck channels, but without explicit disaggregated process-level collection assets.
- **Capacity-loop abstraction risk:** capacity expansion/retirement is represented as an envelope index rather than explicit stage-specific physical capacity stocks.
- **Static SD heterogeneity (config-driven):** material-region SD differences are rule-based constants from config (no endogenous learning/adaptation process within SD).
- **Two-signal aggregation simplification:** service and circular supply stresses are now fed back year-by-year, but are still combined into one effective SD scarcity multiplier (interaction nonlinearities are not represented explicitly).
- **No trade / inter-regional exchange (MVP):** each region is independent; results may overstate scarcity in one region and understate global buffering.
- **Refining-anchor simplification:** using `max(0, primary_refined_output + primary_refined_net_imports)` as aggregate availability can under/over constrain supply where stock changes, quality effects, or unmodeled trade channels matter.
- **Stage-yield data quality risk:** explicit extraction/beneficiation/refining/sorting yields are now structural drivers; weak or placeholder estimates can bias upstream throughput and losses.
- **Simplified SD demand response:** single scalar scarcity → price → demand reduction; no substitution, technology switching, or sectoral elasticities.

## Data risks
- The repository ships with **synthetic placeholder data** in `data/exogenous/`.
  Do not interpret outputs as real-world results until replaced.

## Indicator interpretation risks
- Resilience metrics depend strongly on the chosen **service threshold** (see `configs/indicators.yml`).
- Stockpile can remain positive in the last modeled year; treat final-year `Refinery_stockpile_stock` as terminal inventory, not losses.
- Strategic reserve can remain positive in the last modeled year; treat final-year `Strategic_inventory_stock` as terminal policy inventory.

## Mitigations
- Replace TEMP datasets first (see `configs/assumptions.yml` + `docs/governance/ASSUMPTIONS.md`).
- Add trade and/or multi-region production allocation once base dMFA is validated.
