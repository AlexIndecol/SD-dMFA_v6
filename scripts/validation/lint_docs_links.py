#!/usr/bin/env python3
"""Lint markdown documentation links, anchors, and canonical-source claims."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]

DEPRECATED_TOKENS = (
    "docs/model/BACI_OD_ASSUMPTIONS.md",
    "docs/model/OUTPUTS_GUIDE.md",
    "docs/workflows/CONFIG_PRECEDENCE.md",
    "docs/governance/ASSUMPTIONS.md",
    "docs/governance/DECISION_LOG.md",
)

TOPIC_CANONICAL_RULES = {
    "config interfaces": {
        "topic_regex": re.compile(r"\bconfig\b.*\b(interface|contract|precedence|merge)\b", re.IGNORECASE),
        "expected": "docs/workflows/CONFIGS.md",
    },
    "governance assumptions": {
        "topic_regex": re.compile(r"\b(governance|assumption|persistent model decision)\b", re.IGNORECASE),
        "expected": "docs/governance/MODEL_GOVERNANCE.md",
    },
    "risk register": {
        "topic_regex": re.compile(r"\brisk(s| register)?\b", re.IGNORECASE),
        "expected": "docs/governance/RISKS.md",
    },
    "terminology": {
        "topic_regex": re.compile(r"\b(glossary|terminology|term definitions?)\b", re.IGNORECASE),
        "expected": "docs/model/GLOSSARY.md",
    },
    "indicator formulas": {
        "topic_regex": re.compile(r"\bindicator(s)?\b.*\b(formula|semantics|interpretation)\b", re.IGNORECASE),
        "expected": "docs/model/INDICATORS.md",
    },
    "scenario execution": {
        "topic_regex": re.compile(r"\bscenario(s)?\b.*\b(execution|variants?|workflow)\b", re.IGNORECASE),
        "expected": "docs/workflows/SCENARIOS.md",
    },
}


LINK_RE = re.compile(r"(?<!\!)\[[^\]]+\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
PATH_TOKEN_RE = re.compile(r"(docs/[A-Za-z0-9_./-]+\.md|README\.md|\./[A-Za-z0-9_./-]+\.md|\.\./[A-Za-z0-9_./-]+\.md)")
BACKTICK_PATH_RE = re.compile(r"`([^`]+\.md(?:#[^`]+)?)`")
CANONICAL_CLAIM_RE = re.compile(
    r"\bcanonical\b.*\b(source|reference|contract|authority)\b", re.IGNORECASE
)


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


def slugify_heading(heading: str) -> str:
    heading = re.sub(r"`([^`]+)`", r"\1", heading)
    heading = re.sub(r"\[[^\]]+\]\(([^)]+)\)", "", heading)
    heading = re.sub(r"<[^>]+>", "", heading)
    heading = heading.strip().lower()
    heading = re.sub(r"[^a-z0-9_\-\s]", "", heading)
    heading = re.sub(r"\s+", "-", heading)
    heading = re.sub(r"-+", "-", heading)
    return heading.strip("-")


def extract_heading_anchors(path: Path) -> set[str]:
    text = strip_fenced_code(path.read_text(encoding="utf-8"))
    anchors: set[str] = set()
    seen: dict[str, int] = {}
    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if not m:
            continue
        base = slugify_heading(m.group(1))
        if not base:
            continue
        idx = seen.get(base, 0)
        anchor = base if idx == 0 else f"{base}-{idx}"
        seen[base] = idx + 1
        anchors.add(anchor)
    return anchors


def iter_markdown_docs(root: Path) -> list[Path]:
    docs = [root / "README.md"]
    docs.extend(sorted((root / "docs").rglob("*.md")))
    return docs


def normalize_target_path(src: Path, raw_link: str) -> tuple[Path | None, str | None]:
    link = raw_link.strip().strip("<>")
    if not link:
        return None, None
    if link.startswith(("http://", "https://", "mailto:", "tel:")):
        return None, None

    link = unquote(link)
    link = link.split(" ", 1)[0]
    link = link.split("?", 1)[0]

    if "#" in link:
        path_part, anchor = link.split("#", 1)
    else:
        path_part, anchor = link, None

    if path_part == "":
        target = src
    elif path_part.startswith("/"):
        target = (ROOT / path_part.lstrip("/")).resolve()
    else:
        target = (src.parent / path_part).resolve()

    return target, anchor


def normalize_doc_ref_token(src: Path, token: str) -> str | None:
    token = token.strip().strip("`<>")
    token = token.split("#", 1)[0].split("?", 1)[0]
    if not token.endswith(".md"):
        return None
    if token.startswith("/"):
        target = (ROOT / token.lstrip("/")).resolve()
    elif token.startswith("docs/") or token == "README.md":
        target = (ROOT / token).resolve()
    else:
        target = (src.parent / token).resolve()
    try:
        rel = target.relative_to(ROOT)
    except ValueError:
        return None
    return rel.as_posix()


def collect_claim_paths(src: Path, line: str) -> set[str]:
    paths: set[str] = set()

    for match in BACKTICK_PATH_RE.finditer(line):
        normalized = normalize_doc_ref_token(src, match.group(1))
        if normalized:
            paths.add(normalized)

    for match in LINK_RE.finditer(line):
        target, _ = normalize_target_path(src, match.group(1))
        if target and target.suffix == ".md":
            try:
                paths.add(target.relative_to(ROOT).as_posix())
            except ValueError:
                pass

    for match in PATH_TOKEN_RE.finditer(line):
        normalized = normalize_doc_ref_token(src, match.group(1))
        if normalized:
            paths.add(normalized)

    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint markdown links, anchors, and canonical claims.")
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Repository root (defaults to current script root).",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    docs = iter_markdown_docs(root)

    errors: list[str] = []
    anchor_cache: dict[Path, set[str]] = {}
    claim_map: dict[str, set[str]] = {topic: set() for topic in TOPIC_CANONICAL_RULES}

    for doc in docs:
        rel_doc = doc.relative_to(root).as_posix()
        text = doc.read_text(encoding="utf-8")

        for token in DEPRECATED_TOKENS:
            if token in text and rel_doc != "docs/governance/CHANGELOG.md":
                errors.append(f"{rel_doc}: deprecated reference found -> {token}")

        stripped = strip_fenced_code(text)

        for match in LINK_RE.finditer(stripped):
            raw_link = match.group(1)
            target, anchor = normalize_target_path(doc, raw_link)
            if target is None:
                continue

            if not target.exists():
                errors.append(
                    f"{rel_doc}: broken link target -> {raw_link} (resolved: {target})"
                )
                continue

            if anchor and target.suffix.lower() == ".md":
                if target not in anchor_cache:
                    anchor_cache[target] = extract_heading_anchors(target)
                if anchor not in anchor_cache[target]:
                    rel_target = target.relative_to(root).as_posix()
                    errors.append(
                        f"{rel_doc}: missing anchor -> {raw_link} (anchor '{anchor}' not found in {rel_target})"
                    )

        for line in stripped.splitlines():
            if not CANONICAL_CLAIM_RE.search(line):
                continue
            candidate_paths = collect_claim_paths(doc, line)
            if not candidate_paths:
                continue
            for topic, rule in TOPIC_CANONICAL_RULES.items():
                if rule["topic_regex"].search(line):
                    claim_map[topic].update(candidate_paths)

    for topic, rule in TOPIC_CANONICAL_RULES.items():
        claims = claim_map[topic]
        if len(claims) > 1:
            errors.append(
                f"conflicting canonical claims for topic '{topic}': {sorted(claims)}"
            )
        elif len(claims) == 1:
            claim = next(iter(claims))
            if claim != rule["expected"]:
                errors.append(
                    f"canonical claim mismatch for topic '{topic}': got {claim}, expected {rule['expected']}"
                )

    if errors:
        print("Documentation lint failed:\n")
        for item in errors:
            print(f"- {item}")
        return 1

    print(f"Documentation lint passed: {len(docs)} markdown files checked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
