from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import List, Tuple

_STAMP_DIR_RE = re.compile(r"^\d{8}-\d{6}$")


def archive_old_timestamped_runs(
    parent_dir: str | Path,
    *,
    keep_last: int = 3,
    archive_dirname: str = "_archive",
) -> List[Tuple[Path, Path]]:
    """Keep only the newest timestamped run folders and archive the rest.

    Timestamped folders are identified by the name pattern: YYYYMMDD-HHMMSS.
    Archived folders are moved under ``<parent_dir>/<archive_dirname>/``.
    """
    if keep_last < 0:
        raise ValueError(f"keep_last must be >= 0; got {keep_last}")

    base = Path(parent_dir).resolve()
    if not base.exists():
        return []

    run_dirs = [
        p
        for p in base.iterdir()
        if p.is_dir() and _STAMP_DIR_RE.fullmatch(p.name or "") is not None
    ]
    run_dirs = sorted(run_dirs, key=lambda p: p.name, reverse=True)
    to_archive = run_dirs[keep_last:]
    if not to_archive:
        return []

    archive_root = base / archive_dirname
    archive_root.mkdir(parents=True, exist_ok=True)

    moved: List[Tuple[Path, Path]] = []
    for src in to_archive:
        dst = archive_root / src.name
        if dst.exists():
            i = 1
            while True:
                cand = archive_root / f"{src.name}__{i:02d}"
                if not cand.exists():
                    dst = cand
                    break
                i += 1
        shutil.move(str(src), str(dst))
        moved.append((src, dst))
    return moved

