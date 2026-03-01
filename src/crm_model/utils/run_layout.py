from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List

_STAMP_DIR_RE = re.compile(r"^\d{8}-\d{6}$")


def latest_timestamp_dir(path: Path) -> Path | None:
    if not path.exists() or not path.is_dir():
        return None
    runs = sorted(
        [p for p in path.iterdir() if p.is_dir() and _STAMP_DIR_RE.fullmatch(p.name or "") is not None],
        key=lambda p: p.name,
    )
    if not runs:
        return None
    return runs[-1]


def config_runs_root(base_root: Path, config_stem: str) -> Path:
    if base_root.name.lower() == str(config_stem).lower():
        return base_root
    return base_root / str(config_stem)


def scenario_variant_root(base_root: Path, config_stem: str, variant: str) -> Path:
    return config_runs_root(base_root, config_stem) / str(variant)


def scenario_variant_root_candidates(base_root: Path, config_stem: str, variant: str) -> List[Path]:
    """Return candidate variant roots across current and legacy folder layouts."""
    cfg = str(config_stem)
    var = str(variant)
    candidates: List[Path] = []

    bases = [base_root, base_root / "scenarios"]
    for b in bases:
        candidates.extend(
            [
                scenario_variant_root(b, cfg, var),  # current layout
                b / f"{cfg}_{var}",  # legacy slugged layout
                b / f"{cfg}__{var}",  # legacy unslugged layout
                b / var,  # ad-hoc manual layout
            ]
        )

    uniq: List[Path] = []
    seen = set()
    for p in candidates:
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def latest_timestamp_from_candidate_roots(candidate_roots: Iterable[Path]) -> Path | None:
    latest: Path | None = None
    for root in candidate_roots:
        cur = latest_timestamp_dir(root)
        if cur is None:
            continue
        if latest is None or cur.name > latest.name:
            latest = cur
    return latest
