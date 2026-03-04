# Risks & limitations

## Document position

- You are here: Tier 2 canonical risk register.
- Canonical scope: stable risk IDs, limitation statements, and mitigation direction.
- Out of scope: full governance decision rationale and implementation formulas.
- Related docs: [MODEL_GOVERNANCE.md](./MODEL_GOVERNANCE.md), [ARCHITECTURE.md](../model/ARCHITECTURE.md), [INDICATORS.md](../model/INDICATORS.md), [CHANGELOG.md](./CHANGELOG.md)

## Model-structure risks

- **R-SEC-01 Simplified secondary inventory policy:** secondary material is held in a refinery stockpile with an exogenous release-rate control; endogenous market/price-driven release behavior is not represented.
- **R-RES-01 Strategic reserve trigger sensitivity:** SD reserve fill/release intents depend on threshold settings (price/service) and can materially change unmet-service timing.
- **R-RES-02 Strategic release composition simplification:** strategic reserve is modeled as a single aggregate stock without explicit commodity-quality composition tracking.
- **R-COL-01 Collection-response simplification:** dynamic collection uses bounded/lagged multipliers with price and bottleneck channels, but without explicit disaggregated process-level collection assets.
- **R-CAP-01 Capacity-loop abstraction risk:** capacity expansion/retirement is represented as an envelope index rather than explicit stage-specific physical capacity stocks.
- **R-HET-01 Static SD heterogeneity (config-driven):** material-region SD differences are rule-based constants from config (no endogenous learning/adaptation process within SD).
- **R-CPG-01 Two-signal aggregation simplification:** service and circular supply stresses are fed back year-by-year but still combined into one effective SD scarcity multiplier (interaction nonlinearities are not represented explicitly).
- **R-OD-01 Incremental OD trade limitation:** OD trade remains limited to current commodity routing (`concentrates`, `refined_metal`, `scrap`) and simplified allocation/cap structures; runtime does not currently use historical-window fallback branching.
- **R-PRI-01 Refining-anchor simplification:** using `max(0, primary_refined_output + trade_refined_net_imports + concentrate_to_refined_coeff * trade_concentrate_net_imports)` as aggregate availability can under/over constrain supply where stock changes, quality effects, or unmodeled channels matter.
- **R-YLD-01 Stage-yield data quality risk:** explicit extraction/beneficiation/refining/sorting yields are structural drivers; weak or placeholder estimates can bias throughput and losses.
- **R-DMD-01 Simplified SD demand response:** single scalar scarcity -> price -> demand reduction; no substitution, technology switching, or sectoral elasticities.

## Indicator interpretation risks

- **R-IND-01 Threshold sensitivity:** resilience metrics depend strongly on chosen service threshold (see `configs/indicators.yml`).
- **R-INV-01 Terminal refinery stock interpretation:** positive final-year `Refinery_stockpile_stock` is terminal inventory, not losses.
- **R-INV-02 Terminal strategic stock interpretation:** positive final-year `Strategic_inventory_stock` is terminal policy inventory.

## Mitigations

- Replace TEMP assumptions and placeholders first (see canonical governance source: `docs/governance/MODEL_GOVERNANCE.md`).
- Expand OD trade coupling scope and validation coverage once additional calibration targets are available.

## Related sections

- [MODEL_GOVERNANCE.md §11](./MODEL_GOVERNANCE.md#11-risk-cross-reference-map) for where each assumption cluster maps to risk IDs.
- [ARCHITECTURE.md §9](../model/ARCHITECTURE.md#9-known-simplifications-and-risk-cross-reference) for implementation-level interpretation context.
