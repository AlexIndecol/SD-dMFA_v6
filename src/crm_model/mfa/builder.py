from __future__ import annotations

"""Backward-compatible MFA builder surface.

This module is retained as a compatibility shim while implementation logic is
split across dedicated modules:
- `crm_model.mfa.dimensions`
- `crm_model.mfa.parameters`
- `crm_model.mfa.system`
- `crm_model.mfa.run_mfa`
"""

from .dimensions import _subset_dims
from .parameters import _as_timeseries, _resolve_routing_rates
from .run_mfa import run_flodym_mfa
from .system import MFATimeseries, SimpleMetalCycleWithReman

__all__ = [
    "_subset_dims",
    "_as_timeseries",
    "_resolve_routing_rates",
    "MFATimeseries",
    "SimpleMetalCycleWithReman",
    "run_flodym_mfa",
]
