#!/usr/bin/env python3
"""
lens_diff.py — draft preview tool.

Parses a draft .md (same format as lens_extract output), diffs against
current DB state, and shows what would change. Never writes to the DB.

The Anvil reads this diff, exercises judgment, and commits directly.

Usage:
    python lens_diff.py temp/loom/wardrobe-merged.md              # diff against DB
    python lens_diff.py temp/loom/wardrobe-merged.md --db mem.db   # explicit DB path
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from wake.schema import connect


# --- Parsing ---


@dataclass
class ParsedFragment:
    key: str
    ambient: str | None = None
    recognition: str | None = None
    inventory: str | None = None


@dataclass
class ParsedEdge:
    source_key: str
    target_key: str
    relation: str | None = None
    remove: bool = False


@dataclass
class ParsedDraft:
    fragments: list[ParsedFragment] = field(default_factory=list)
    edges: list[ParsedEdge] = field(default_factory=list)


# Regex for fragment header: ## [key]
_FRAGMENT_RE = re.compile(r"^##\s+\[([^\]]+)\]\s*$")

# Regex for tier marker: Ambient:, Recognition:, Inventory:
_TIER_RE = re.compile(r"^(Ambient|Recognition|Inventory):\s*(.*)", re.IGNORECASE)

# Regex for edge: source → target (relation)  or  source -> target (relation)
_EDGE_RE = re.compile(
    r"^(?:REMOVE:\s*)?(.+?)\s*(?:→|->)\s*(.+?)(?:\s+\(([^)]+)\))?\s*$"
)

# Regex for edge section header
_EDGE_SECTION_RE = re.compile(r"^##\s+Edges\s*$", re.IGNORECASE)

# Regex for title line (skip it)
_TITLE_RE = re.compile(r"^#\s+")


def parse_draft(text: str) -> ParsedDraft:
    """Parse a draft .md file into fragments and edges."""
    draft = ParsedDraft()
    lines = text.split("\n")

    current_fragment: ParsedFragment | None = None
    current_tier: str | None = None
    tier_lines: list[str] = []
    in_edges = False

    def _flush_tier():
        nonlocal current_tier, tier_lines
        if current_fragment and current_tier and tier_lines:
            content = "\n".join(tier_lines).strip()
            if content:
                setattr(current_fragment, current_tier.lower(), content)
        current_tier = None
        tier_lines = []

    def _flush_fragment():
        nonlocal current_fragment
        _flush_tier()
        if current_fragment:
            draft.fragments.append(current_fragment)
        current_fragment = None

    for line in lines:
        # Skip title lines
        if _TITLE_RE.match(line) and not _FRAGMENT_RE.match(line) and not _EDGE_SECTION_RE.match(line):
            continue

        # Edge section
        if _EDGE_SECTION_RE.match(line):
            _flush_fragment()
            in_edges = True
            continue

        # Fragment header
        frag_match = _FRAGMENT_RE.match(line)
        if frag_match:
            _flush_fragment()
            in_edges = False
            current_fragment = ParsedFragment(key=frag_match.group(1))
            continue

        # Edge line
        if in_edges:
            edge_match = _EDGE_RE.match(line.strip())
            if edge_match:
                is_remove = line.strip().startswith("REMOVE:")
                source = edge_match.group(1).strip()
                if is_remove:
                    source = re.sub(r"^REMOVE:\s*", "", source).strip()
                draft.edges.append(ParsedEdge(
                    source_key=source,
                    target_key=edge_match.group(2).strip(),
                    relation=edge_match.group(3).strip() if edge_match.group(3) else None,
                    remove=is_remove,
                ))
            continue

        # Inside a fragment block
        if current_fragment is not None:
            tier_match = _TIER_RE.match(line)
            if tier_match:
                _flush_tier()
                current_tier = tier_match.group(1).lower()
                rest = tier_match.group(2).strip()
                if rest:
                    tier_lines.append(rest)
                continue

            if current_tier is not None:
                tier_lines.append(line)

    # Flush remaining
    _flush_fragment()

    return draft


# --- Diffing ---


@dataclass
class FragmentDiff:
    key: str
    action: str  # "CREATE", "UPDATE", "(unchanged)"
    changed_tiers: list[str] = field(default_factory=list)


@dataclass
class EdgeDiff:
    source_key: str
    target_key: str
    relation: str | None
    action: str  # "+", "-", "=", "!"


@dataclass
class DiffResult:
    fragments: list[FragmentDiff] = field(default_factory=list)
    edges: list[EdgeDiff] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        for f in self.fragments:
            if f.action != "(unchanged)":
                return True
        for e in self.edges:
            if e.action not in ("=", "!"):
                return True
        return False


def compute_diff(conn, draft: ParsedDraft) -> DiffResult:
    """Compare draft against current DB state."""
    diff = DiffResult()

    for frag in draft.fragments:
        row = conn.execute(
            "SELECT key, ambient, recognition, inventory FROM fragments WHERE key = ?",
            (frag.key,),
        ).fetchone()

        if row is None:
            tiers = []
            if frag.ambient is not None:
                tiers.append("ambient")
            if frag.recognition is not None:
                tiers.append("recognition")
            if frag.inventory is not None:
                tiers.append("inventory")
            diff.fragments.append(FragmentDiff(
                key=frag.key, action="CREATE", changed_tiers=tiers
            ))
        else:
            changed = []
            for tier in ("ambient", "recognition", "inventory"):
                draft_val = getattr(frag, tier)
                if draft_val is not None and draft_val != (row[tier] or ""):
                    changed.append(tier)

            if changed:
                diff.fragments.append(FragmentDiff(
                    key=frag.key, action="UPDATE", changed_tiers=changed
                ))
            else:
                diff.fragments.append(FragmentDiff(
                    key=frag.key, action="(unchanged)"
                ))

    for edge in draft.edges:
        if edge.remove:
            existing = conn.execute(
                "SELECT 1 FROM fragment_edges WHERE source_key = ? AND target_key = ?",
                (edge.source_key, edge.target_key),
            ).fetchone()
            if existing:
                diff.edges.append(EdgeDiff(
                    source_key=edge.source_key,
                    target_key=edge.target_key,
                    relation=edge.relation,
                    action="-",
                ))
            else:
                reverse = conn.execute(
                    "SELECT 1 FROM fragment_edges WHERE source_key = ? AND target_key = ?",
                    (edge.target_key, edge.source_key),
                ).fetchone()
                if reverse:
                    diff.edges.append(EdgeDiff(
                        source_key=edge.source_key,
                        target_key=edge.target_key,
                        relation=edge.relation,
                        action="!",
                    ))
        else:
            existing = conn.execute(
                "SELECT relation FROM fragment_edges WHERE source_key = ? AND target_key = ?",
                (edge.source_key, edge.target_key),
            ).fetchone()
            if existing is None:
                diff.edges.append(EdgeDiff(
                    source_key=edge.source_key,
                    target_key=edge.target_key,
                    relation=edge.relation,
                    action="+",
                ))
            elif existing["relation"] != edge.relation:
                diff.edges.append(EdgeDiff(
                    source_key=edge.source_key,
                    target_key=edge.target_key,
                    relation=edge.relation,
                    action="+",
                ))
            else:
                diff.edges.append(EdgeDiff(
                    source_key=edge.source_key,
                    target_key=edge.target_key,
                    relation=edge.relation,
                    action="=",
                ))

    return diff


def format_diff(diff: DiffResult) -> str:
    """Format diff for display."""
    parts = []

    if diff.fragments:
        parts.append("FRAGMENTS:")
        for f in diff.fragments:
            if f.action == "CREATE":
                parts.append(f"  [{f.key}]  CREATE  {', '.join(f.changed_tiers)}")
            elif f.action == "UPDATE":
                parts.append(f"  [{f.key}]  UPDATE  {', '.join(t + ' (changed)' for t in f.changed_tiers)}")
            else:
                parts.append(f"  [{f.key}]  (unchanged)")

    if diff.edges:
        parts.append("")
        parts.append("EDGES:")
        for e in diff.edges:
            rel = f" ({e.relation})" if e.relation else ""
            if e.action == "+":
                parts.append(f"  + {e.source_key} \u2192 {e.target_key}{rel}")
            elif e.action == "-":
                parts.append(f"  - {e.source_key} \u2192 {e.target_key}{rel}")
            elif e.action == "!":
                parts.append(
                    f"  ! {e.source_key} \u2192 {e.target_key}{rel}  "
                    f"(NOT FOUND \u2014 exists as {e.target_key} \u2192 {e.source_key})"
                )
            else:
                parts.append(f"  = {e.source_key} \u2192 {e.target_key}{rel}  (unchanged)")

    creates = sum(1 for f in diff.fragments if f.action == "CREATE")
    updates = sum(1 for f in diff.fragments if f.action == "UPDATE")
    edge_adds = sum(1 for e in diff.edges if e.action == "+")
    edge_removes = sum(1 for e in diff.edges if e.action == "-")

    parts.append("")
    parts.append(
        f"Summary: {creates} create, {updates} update | "
        f"{edge_adds} edge add, {edge_removes} edge remove"
    )

    return "\n".join(parts)


# --- CLI ---


def _load_db_path(args_db: str | None) -> Path:
    """Resolve DB path from --db flag or worker/config.json."""
    if args_db:
        return Path(args_db)

    config_path = Path("worker/config.json")
    if config_path.exists():
        with open(config_path) as f:
            cfg = json.load(f)
        return Path(cfg.get("db_path", "data/silentstar.sqlite"))

    return Path("data/silentstar.sqlite")


def main():
    parser = argparse.ArgumentParser(
        description="Lens diff \u2014 parse draft .md, diff against DB, show what would change"
    )
    parser.add_argument("draft", help="Path to draft .md file")
    parser.add_argument("--db", type=str, help="Path to database (default: from config)")

    args = parser.parse_args()

    draft_path = Path(args.draft)
    if not draft_path.exists():
        print(f"Draft not found: {draft_path}", file=sys.stderr)
        sys.exit(1)

    text = draft_path.read_text(encoding="utf-8")
    draft = parse_draft(text)

    if not draft.fragments and not draft.edges:
        print("Nothing parsed from draft. Check the format.", file=sys.stderr)
        sys.exit(1)

    db_path = _load_db_path(args.db)
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = connect(db_path)

    try:
        diff = compute_diff(conn, draft)
        print(format_diff(diff))

        if not diff.has_changes:
            print("\nNo changes needed.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
