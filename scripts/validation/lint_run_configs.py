#!/usr/bin/env python
"""Lint run configs for canonical structure and loadability.

Usage:
  python scripts/validation/lint_run_configs.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from crm_model.common.io import load_run_config


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML file must be a mapping: {path}")
    return payload


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    run_dir = repo_root / "configs" / "runs"
    run_files = sorted(p for p in run_dir.glob("*.yml") if p.is_file())

    errors: list[str] = []

    for cfg_path in run_files:
        try:
            raw = _read_yaml(cfg_path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{cfg_path}: failed to parse YAML ({exc})")
            continue

        includes = raw.get("includes", {})
        if includes is None:
            includes = {}
        if not isinstance(includes, dict):
            errors.append(f"{cfg_path}: includes must be a mapping when present")
            includes = {}

        alias_keys = [k for k in ["applications", "end_use", "end_uses"] if includes.get(k) is not None]
        if len(alias_keys) > 1:
            errors.append(
                f"{cfg_path}: multiple end-use include aliases found ({alias_keys}); use only 'end_uses'"
            )
        if "applications" in alias_keys or "end_use" in alias_keys:
            errors.append(
                f"{cfg_path}: deprecated include key in use ({alias_keys}); replace with 'end_uses'"
            )

        try:
            cfg = load_run_config(cfg_path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{cfg_path}: load_run_config failed ({exc})")
            continue

        if not cfg.variants:
            errors.append(f"{cfg_path}: no variants resolved")

    if errors:
        print("Run-config lint FAILED")
        for err in errors:
            print("-", err)
        return 1

    print("Run-config lint OK")
    for cfg_path in run_files:
        print("-", cfg_path.relative_to(repo_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
