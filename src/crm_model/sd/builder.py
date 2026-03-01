from __future__ import annotations

"""Backward-compatible SD builder surface.

This module is retained as a compatibility shim while implementation logic is
split across dedicated modules:
- `crm_model.sd.bptk_model`
- `crm_model.sd.run_sd`
- `crm_model.sd.levers`
- `crm_model.sd.shocks`
- `crm_model.sd.scenario`
"""

from .bptk_model import DemandModel, SDTimeseries
from .levers import apply_sd_lever_overrides
from .run_sd import run_bptk_sd
from .scenario import resolve_sd_parameters_for_slice
from .shocks import shock_multiplier_series

__all__ = [
    "SDTimeseries",
    "DemandModel",
    "run_bptk_sd",
    "apply_sd_lever_overrides",
    "shock_multiplier_series",
    "resolve_sd_parameters_for_slice",
]
