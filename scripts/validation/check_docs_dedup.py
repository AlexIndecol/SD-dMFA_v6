#!/usr/bin/env python3
"""Lightweight deduplication lint for markdown prose paragraphs."""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def iter_markdown_docs(root: Path) -> list[Path]:
    docs = [root / "README.md"]
    docs.extend(sorted((root / "docs").rglob("*.md")))
    return docs


def strip_fenced_code(text: str) -> str:
    out: list[str] = []
    in_fence = False
    fence_marker = ""
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = ""
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


def normalize_paragraph(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def should_skip_paragraph(text: str) -> bool:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return True
    if all(
        ln.startswith("#")
        or ln.startswith("-")
        or ln.startswith("*")
        or re.match(r"^\d+\.\s", ln)
        or ln.startswith("|")
        for ln in lines
    ):
        return True
    return False


def split_paragraphs_with_line_numbers(text: str) -> list[tuple[int, str]]:
    paragraphs: list[tuple[int, str]] = []
    buffer: list[str] = []
    start_line = 1

    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        if line.strip() == "":
            if buffer:
                paragraphs.append((start_line, "\n".join(buffer)))
                buffer = []
            start_line = idx + 1
            continue
        if not buffer:
            start_line = idx
        buffer.append(line)

    if buffer:
        paragraphs.append((start_line, "\n".join(buffer)))

    return paragraphs


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect duplicate long prose paragraphs across markdown docs.")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root.")
    parser.add_argument(
        "--min-length",
        type=int,
        default=220,
        help="Minimum normalized paragraph length to include in duplicate checks.",
    )
    parser.add_argument(
        "--max-occurrences",
        type=int,
        default=1,
        help="Maximum allowed occurrences of a normalized paragraph across files.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    docs = iter_markdown_docs(root)

    occurrences: dict[str, list[tuple[str, int, str]]] = defaultdict(list)

    for doc in docs:
        rel = doc.relative_to(root).as_posix()
        text = strip_fenced_code(doc.read_text(encoding="utf-8"))
        for line_no, paragraph in split_paragraphs_with_line_numbers(text):
            if should_skip_paragraph(paragraph):
                continue
            normalized = normalize_paragraph(paragraph)
            if len(normalized) < args.min_length:
                continue
            occurrences[normalized].append((rel, line_no, paragraph.strip()))

    findings: list[tuple[str, list[tuple[str, int, str]]]] = []
    for normalized, refs in occurrences.items():
        distinct_files = {ref[0] for ref in refs}
        if len(refs) > args.max_occurrences and len(distinct_files) > 1:
            findings.append((normalized, refs))

    if findings:
        print("Documentation dedup check failed:\n")
        for _, refs in findings:
            print(f"- duplicate paragraph ({len(refs)} occurrences)")
            for rel, line_no, para in refs:
                preview = para.replace("\n", " ")
                if len(preview) > 160:
                    preview = preview[:157] + "..."
                print(f"  - {rel}:{line_no} -> {preview}")
            print()
        return 1

    print(f"Documentation dedup check passed: {len(docs)} markdown files scanned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
