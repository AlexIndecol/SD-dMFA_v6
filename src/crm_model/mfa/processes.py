"""MFA process graph helpers."""

from __future__ import annotations

from typing import Any, Dict


def graph_payload_from_config(mfa_graph_config: Any) -> Dict[str, Any] | None:
    """Return a plain-dict graph payload from config objects or mappings."""
    if mfa_graph_config is None:
        return None
    if isinstance(mfa_graph_config, dict):
        return dict(mfa_graph_config)
    if hasattr(mfa_graph_config, "model_dump"):
        return mfa_graph_config.model_dump(by_alias=True)
    raise ValueError(f"Unsupported mfa_graph_config type: {type(mfa_graph_config)}")


__all__ = ["graph_payload_from_config"]
