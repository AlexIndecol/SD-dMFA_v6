"""Config and YAML I/O adapters for migration-safe usage."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from crm_model.config.io import load_run_config, resolve_repo_root_from_config


def read_yaml(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML file must contain a mapping at top level: {p}")
    return data


def write_yaml(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


__all__ = ["load_run_config", "resolve_repo_root_from_config", "read_yaml", "write_yaml"]
