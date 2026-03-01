#!/usr/bin/env python
"""Validate exogenous input files against the registry and dimensions.

Usage:
  python scripts/validation/validate_exogenous_inputs.py --config configs/runs/mvp.yml
"""

from __future__ import annotations

import argparse
from pathlib import Path

from crm_model.common.io import load_run_config, resolve_repo_root_from_config
from crm_model.common.validation import validate_exogenous_inputs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/runs/mvp.yml")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = load_run_config(cfg_path)

    repo_root = resolve_repo_root_from_config(cfg_path)
    warnings = validate_exogenous_inputs(cfg, repo_root=repo_root)

    if warnings:
        print("Validation warnings:")
        for w in warnings:
            print("-", w)

    print("OK: exogenous inputs validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
