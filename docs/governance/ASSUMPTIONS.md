# Assumptions

This project uses a strict discipline:

- **CONFIRMED** assumptions are agreed design choices.
- **TEMP** assumptions exist only to keep the template runnable.

The canonical list is in `configs/assumptions.yml`.
Each run exports the exact assumptions used to `outputs/.../assumptions_used.yml`.

## CONFIRMED items relevant to v1
- **Region aliases accepted** in exogenous inputs (e.g., `EU-27` → `EU27`, `Rest of the World`/`ROW` → `RoW`).
- **Primary refined output meaning:** `primary_refined_output` is domestic primary refined metal production (metal content).
- **Primary availability balance (endogenous trade runtime):**
  `primary_available_to_refining = max(0, primary_refined_output + trade_refined_net_imports + concentrate_to_refined_coeff * trade_concentrate_net_imports)`.
- **Explicit stage yields/loss routing:** extraction, beneficiation, refining, and sorting use exogenous `stage_yields_losses.csv` controls.
- **Explicit scrap taxonomy:** new scrap (pre-use fabrication losses) and old scrap (post-use outflow) are tracked separately.
- **Secondary inventory mechanism:** secondary feed is buffered as `refinery_stockpile_native` at refining with release-rate control (`refinery_stockpile_release_rate`).
- **Strategic reserve mechanism:** a separate strategic inventory stock (`strategic_inventory_native`) is optional and disabled by default (`strategic_reserve_enabled=false`).
- **Strategic fill/release control split:** SD computes strategic fill/release intents, while MFA enforces physical stock accounting and mass balance.
- **Strategic sourcing rule:** strategic fill competes with current-year supply and prioritizes diversion from secondary release before primary diversion.
- **Terminal inventory interpretation:** any refinery stockpile remaining in the final simulated year is terminal inventory inside the modeled system boundary (it is not automatically flushed to disposal/sink).
- **Collection dynamics:** collection uses bounded first-order-lag multipliers (`sd_parameters.collection_multiplier_min/max/lag_years`) with SD price-linked response (`sd_parameters.collection_price_response_gain`).
- **Capacity/shortage loop:** SD includes a refining-first capacity envelope with lagged adjustment and bottleneck pressure that amplifies scarcity/price and throttles collection response.
- **SD heterogeneity by slice:** key SD behavioral parameters (e.g., `demand_price_elasticity`, `coupling_signal_smoothing`, `coupling_service_stress_gain`, `coupling_circular_supply_stress_gain`) can be specified by material-region rules (`sd_heterogeneity`) instead of one-size-fits-all values.
- **Two-signal coupling feedback:** SD stress input is derived from separate service-stress and circular-supply-stress signals (with configurable gains), not a single aggregate unmet-fraction term.
- **Remanufacturing scope:** remanufacturing is constrained by high-level end-use eligibility (`remanufacturing_end_use_eligibility.csv`) rather than material identity.
- **Supplier governance-risk proxy (optional):** `supplier_governance_risk.csv` provides an origin-level risk factor (`EU27`, `China`, `RoW`) for WGI-style concentration weighting; current template uses supplier-specific divergent era shifts and feeds OD supplier-risk diagnostics when `trade_od.enabled=true`.

## TEMP items shipped in the template
- **Identity upstream defaults:** stage yields default to `1.0` and loss routes to canonical sinks when detailed measured yields/loss splits are not yet available for all slices.
- **Incremental OD trade scope:** OD trade allocator is enabled only when `trade_od.enabled=true`.
  Runtime uses exogenous OD weights + endogenous constraints for 3 commodities and solves in-loop for calibration and reporting phases.

Replace TEMP items before using results for interpretation.
