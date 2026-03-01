"""Data I/O utilities.

All exogenous inputs are expected as one-file-per-variable under `data/exogenous/`,
with a long format that includes a `value` column.
"""

from .io import (
    load_end_use_shares,
    end_use_shares_te,
    load_primary_refined_output,
    primary_refined_output_tr,
    load_primary_refined_net_imports,
    primary_refined_net_imports_tr,
    load_stage_yields_losses,
    stage_yields_losses_t,
    load_collection_routing_rates,
    collection_routing_rates_t,
    load_remanufacturing_end_use_eligibility,
    remanufacturing_eligibility_tre,
    load_final_demand,
    final_demand_t,
    load_service_activity,
    service_activity_t,
    load_material_intensity,
    material_intensity_t,
    load_stock_in_use,
    stock_in_use_t,
    load_lifetime_distributions,
)
