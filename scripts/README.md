# Scripts Layout

Canonical script locations:

- `scripts/validation/` - data/input validation
- `scripts/calibration/` - calibration and promotion/restore workflow
  - includes baseline stock-fit calibration and `calibrate_trade_od.py` for OD trade-layer calibration
- `scripts/analysis/` - scenario comparison and plotting
- `scripts/data/` - data-building utilities

The top-level `scripts/` folder intentionally contains only these logical subfolders.
Use subfolder paths in docs and automation.
