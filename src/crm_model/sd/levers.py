from __future__ import annotations

from typing import Any, Dict

from crm_model.scenarios import deep_update
from .params import normalize_and_validate_sd_parameters


def apply_sd_lever_overrides(sd_parameters: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Return SD parameters with lever overrides applied."""
    base = normalize_and_validate_sd_parameters(sd_parameters)
    merged = deep_update(base, dict(overrides or {}))
    return normalize_and_validate_sd_parameters(merged)


__all__ = ["apply_sd_lever_overrides"]
