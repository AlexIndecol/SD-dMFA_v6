#!/usr/bin/env python
"""Thin wrapper around the canonical coupled-model CLI.

Usage example:
  python scripts/run_one.py --config configs/runs/mvp.yml --variant baseline --phase reporting --save-csv
"""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    cmd = [sys.executable, "-m", "crm_model.cli", *sys.argv[1:]]
    return int(subprocess.call(cmd))


if __name__ == "__main__":
    raise SystemExit(main())
