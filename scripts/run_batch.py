#!/usr/bin/env python
"""Run all (or selected) variants via the canonical CLI.

By default this script executes all variants in the provided config and then
builds a scenario-comparison package.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List

from crm_model.common.io import load_run_config


def _run(cmd: List[str]) -> int:
    return int(subprocess.call(cmd))


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch runner for SD-dMFA variants")
    ap.add_argument("--config", default="configs/runs/mvp.yml")
    ap.add_argument("--phase", choices=["calibration", "reporting", "both"], default="reporting")
    ap.add_argument("--variants", default="", help="Comma-separated variant list. Empty means all variants in config.")
    ap.add_argument("--save-csv", action="store_true", help="Persist per-run outputs")
    ap.add_argument("--compare", action="store_true", help="Run compare_scenarios after all runs")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = load_run_config(cfg_path)

    if args.variants.strip():
        variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    else:
        variants = list(cfg.variants.keys())

    for variant in variants:
        cmd = [
            sys.executable,
            "-m",
            "crm_model.cli",
            "--config",
            args.config,
            "--variant",
            variant,
            "--phase",
            args.phase,
        ]
        if args.save_csv:
            cmd.append("--save-csv")
        rc = _run(cmd)
        if rc != 0:
            return rc

    if args.compare:
        rc = _run([sys.executable, "scripts/analysis/compare_scenarios.py", "--config", args.config])
        if rc != 0:
            return rc

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
