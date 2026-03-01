from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping


@dataclass(frozen=True)
class VariableSpec:
    name: str
    shape: str
    units: str
    description: str


SD_TO_MFA_VARIABLES: Dict[str, VariableSpec] = {
    "desired_demand_t": VariableSpec(
        name="desired_demand_t",
        shape="(t)",
        units="t metal / year",
        description="Desired final-demand trajectory entering SD.",
    ),
    "end_use_shares_te": VariableSpec(
        name="end_use_shares_te",
        shape="(t,e)",
        units="fraction",
        description="End-use share split of SD realized demand before dMFA allocation.",
    ),
    "strategic_fill_intent_t": VariableSpec(
        name="strategic_fill_intent_t",
        shape="(t)",
        units="fraction",
        description="SD control intent for strategic reserve fill intensity.",
    ),
    "strategic_release_intent_t": VariableSpec(
        name="strategic_release_intent_t",
        shape="(t)",
        units="fraction",
        description="SD control intent for strategic reserve release intensity.",
    ),
}

MFA_TO_SD_VARIABLES: Dict[str, VariableSpec] = {
    "service_stress_t": VariableSpec(
        name="service_stress_t",
        shape="(t)",
        units="fraction",
        description="unmet_service / service_demand",
    ),
    "circular_supply_stress_t": VariableSpec(
        name="circular_supply_stress_t",
        shape="(t)",
        units="fraction",
        description="1 - secondary_supply / (primary_supply + secondary_supply)",
    ),
    "strategic_stock_coverage_years_t": VariableSpec(
        name="strategic_stock_coverage_years_t",
        shape="(t)",
        units="years",
        description="strategic_inventory_stock / service_demand",
    ),
}


def _as_name_set(value: Any, *, field_name: str) -> set[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        raise ValueError(f"coupling.signals.{field_name} must be a list of signal names.")
    out: set[str] = set()
    for item in value:
        out.add(str(item).strip())
    out.discard("")
    return out


def validate_coupling_signal_registry(coupling: Mapping[str, Any] | None) -> None:
    """Validate configured signal names against canonical coupling interface specs.

    This is intentionally strict when a `coupling.signals` block is present:
    unknown names are rejected to prevent silent interface drift.
    """
    if not coupling:
        return
    signals = coupling.get("signals")
    if signals is None:
        return
    if not isinstance(signals, Mapping):
        raise ValueError("coupling.signals must be a mapping with sd_to_mfa and mfa_to_sd lists.")

    sd_to_mfa = _as_name_set(signals.get("sd_to_mfa", []), field_name="sd_to_mfa")
    mfa_to_sd = _as_name_set(signals.get("mfa_to_sd", []), field_name="mfa_to_sd")

    allowed_sd_to_mfa = set(SD_TO_MFA_VARIABLES.keys())
    allowed_mfa_to_sd = set(MFA_TO_SD_VARIABLES.keys())

    unknown_sd_to_mfa = sorted(list(sd_to_mfa - allowed_sd_to_mfa))
    unknown_mfa_to_sd = sorted(list(mfa_to_sd - allowed_mfa_to_sd))
    if unknown_sd_to_mfa or unknown_mfa_to_sd:
        parts = []
        if unknown_sd_to_mfa:
            parts.append(
                "Unknown coupling signals in signals.sd_to_mfa: "
                + ", ".join(unknown_sd_to_mfa)
                + f". Allowed: {sorted(list(allowed_sd_to_mfa))}"
            )
        if unknown_mfa_to_sd:
            parts.append(
                "Unknown coupling signals in signals.mfa_to_sd: "
                + ", ".join(unknown_mfa_to_sd)
                + f". Allowed: {sorted(list(allowed_mfa_to_sd))}"
            )
        raise ValueError(" | ".join(parts))


__all__ = [
    "VariableSpec",
    "SD_TO_MFA_VARIABLES",
    "MFA_TO_SD_VARIABLES",
    "validate_coupling_signal_registry",
]
