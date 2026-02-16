#!/usr/bin/env python3
"""
lens_extract.py — the read side of the Lens.

Queries the Gem, follows edges, outputs formatted .md.
Pure read-only. Never writes to DB. No API calls.

Usage:
    python lens_extract.py wardrobe                     # single key + neighbors
    python lens_extract.py wardrobe jirai exhibitionist  # multi-key intersection
    python lens_extract.py --all                         # all fragments
    python lens_extract.py --wm                          # working memory state
    python lens_extract.py --summaries                   # mirror summaries
    python lens_extract.py --search "fairy"              # FTS5 search across all tables
    python lens_extract.py --search "fairy" --type fragments  # search fragments only
    python lens_extract.py wardrobe -o temp/lens/out.md  # output to file
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from wake.schema import connect


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


def _format_date() -> str:
    return datetime.now(timezone.utc).strftime("%b %d, %Y")


def _format_fragment(key: str, row: dict) -> str:
    """Format a single fragment with its tiers."""
    lines = [f"## [{key}]"]
    if row.get("ambient"):
        lines.append(f"Ambient: {row['ambient']}")
    if row.get("recognition"):
        lines.append(f"Recognition: {row['recognition']}")
    if row.get("inventory"):
        lines.append(f"Inventory: {row['inventory']}")
    return "\n".join(lines)


def _format_edges(edges: list[dict]) -> str:
    """Format edge list."""
    if not edges:
        return ""
    lines = ["## Edges"]
    for e in edges:
        rel = f" ({e['relation']})" if e.get("relation") else ""
        lines.append(f"{e['source_key']} \u2192 {e['target_key']}{rel}")
    return "\n".join(lines)


def _get_fragment(conn, key: str) -> dict | None:
    row = conn.execute(
        "SELECT key, ambient, recognition, inventory FROM fragments WHERE key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def _get_edges_for_keys(conn, keys: set[str]) -> list[dict]:
    """Get all edges where both endpoints are in the key set."""
    if not keys:
        return []
    placeholders = ",".join("?" for _ in keys)
    rows = conn.execute(
        f"""
        SELECT source_key, target_key, relation
        FROM fragment_edges
        WHERE source_key IN ({placeholders})
           OR target_key IN ({placeholders})
        ORDER BY source_key, target_key
        """,
        list(keys) + list(keys),
    ).fetchall()
    return [dict(r) for r in rows]


def _get_neighbor_keys(conn, key: str) -> set[str]:
    """Get all keys connected to this key via edges (one hop)."""
    rows = conn.execute(
        """
        SELECT target_key AS k FROM fragment_edges WHERE source_key = ?
        UNION
        SELECT source_key AS k FROM fragment_edges WHERE target_key = ?
        """,
        (key, key),
    ).fetchall()
    return {r["k"] for r in rows}


def extract_single(conn, key: str) -> str:
    """Single key query: fragment + one-hop neighbors + edges."""
    root = _get_fragment(conn, key)
    if root is None:
        return f"# Lens Extract \u2014 {key} ({_format_date()})\n\nFragment not found: {key}"

    neighbor_keys = _get_neighbor_keys(conn, key)
    all_keys = {key} | neighbor_keys

    # Load all fragments
    fragments = {key: root}
    for nk in neighbor_keys:
        frag = _get_fragment(conn, nk)
        if frag:
            fragments[nk] = frag

    # Get edges between all involved keys
    edges = _get_edges_for_keys(conn, all_keys)

    # Build output: root first, then neighbors alphabetically
    parts = [f"# Lens Extract \u2014 {key} ({_format_date()})"]
    parts.append("")
    parts.append(_format_fragment(key, root))

    for nk in sorted(neighbor_keys):
        if nk in fragments:
            parts.append("")
            parts.append(_format_fragment(nk, fragments[nk]))

    edge_str = _format_edges(edges)
    if edge_str:
        parts.append("")
        parts.append(edge_str)

    return "\n".join(parts)


def extract_multi(conn, keys: list[str]) -> str:
    """Multi-key intersection: fragments where paths converge."""
    # For each key, find its neighborhood (self + one-hop)
    neighborhoods: dict[str, set[str]] = {}
    for key in keys:
        if _get_fragment(conn, key) is None:
            continue
        neighbors = _get_neighbor_keys(conn, key)
        neighborhoods[key] = {key} | neighbors

    if not neighborhoods:
        return f"# Lens Extract \u2014 intersection ({_format_date()})\n\nNo matching fragments found."

    # Find intersection: keys that appear in 2+ neighborhoods
    from collections import Counter
    all_neighbor_keys: list[str] = []
    for ns in neighborhoods.values():
        all_neighbor_keys.extend(ns)
    counts = Counter(all_neighbor_keys)
    intersection = {k for k, c in counts.items() if c >= 2 and k not in keys}

    # All keys we'll show: roots + intersection
    root_keys = [k for k in keys if k in neighborhoods]
    show_keys = set(root_keys) | intersection
    all_involved = set()
    for ns in neighborhoods.values():
        all_involved |= ns

    # Load fragments
    fragments: dict[str, dict] = {}
    for k in show_keys:
        frag = _get_fragment(conn, k)
        if frag:
            fragments[k] = frag

    # Get edges between all involved keys
    edges = _get_edges_for_keys(conn, show_keys)

    # Build output
    label = ", ".join(root_keys)
    parts = [f"# Lens Extract \u2014 {label} ({_format_date()})"]

    # Root fragments first
    for k in root_keys:
        if k in fragments:
            parts.append("")
            parts.append(_format_fragment(k, fragments[k]))

    # Intersection fragments
    if intersection:
        parts.append("")
        parts.append(f"## Intersection ({len(intersection)})")
        for k in sorted(intersection):
            if k in fragments:
                parts.append("")
                parts.append(_format_fragment(k, fragments[k]))

    edge_str = _format_edges(edges)
    if edge_str:
        parts.append("")
        parts.append(edge_str)

    return "\n".join(parts)


def extract_all(conn) -> str:
    """All fragments + all edges."""
    rows = conn.execute(
        "SELECT key, ambient, recognition, inventory FROM fragments ORDER BY key"
    ).fetchall()

    parts = [f"# Lens Extract \u2014 all ({_format_date()})"]
    parts.append(f"\n{len(rows)} fragments\n")

    for row in rows:
        parts.append(_format_fragment(row["key"], dict(row)))
        parts.append("")

    edges = conn.execute(
        "SELECT source_key, target_key, relation FROM fragment_edges ORDER BY source_key, target_key"
    ).fetchall()
    edge_str = _format_edges([dict(e) for e in edges])
    if edge_str:
        parts.append(edge_str)

    return "\n".join(parts)


def extract_wm(conn) -> str:
    """Working memory state."""
    rows = conn.execute(
        """
        SELECT id, type, content, subject, actor, status, due,
               created_at, refreshed_at
        FROM working_memory
        WHERE status = 'active'
        ORDER BY type, id
        """
    ).fetchall()

    # Group by type
    by_type: dict[str, list] = {}
    for row in rows:
        t = row["type"]
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(dict(row))

    # Order: feeling, thought, desc, pin, plan, pattern, secret
    type_order = ["feeling", "thought", "desc", "pin", "plan", "pattern", "secret"]

    parts = [f"# Working Memory \u2014 Active ({_format_date()})"]

    for wm_type in type_order:
        items = by_type.get(wm_type, [])
        parts.append(f"\n## {wm_type.title()}s ({len(items)} active)")
        if not items:
            continue
        for item in items:
            date = item["created_at"][:10] if item.get("created_at") else ""
            actor = f" ({item['actor']})" if item.get("actor") else ""
            due = f" due: {item['due'][:10]}" if item.get("due") else ""
            parts.append(f"- [id {item['id']}]{actor} {item['content']}{due} ({date})")

    return "\n".join(parts)


def extract_summaries(db_path: Path) -> str:
    """Mirror summaries from data/summaries.sqlite."""
    summaries_path = db_path.parent / "summaries.sqlite"
    if not summaries_path.exists():
        return f"# Mirror Summaries ({_format_date()})\n\nNo summaries.sqlite found at {summaries_path}."

    try:
        from wake.summaries_schema import connect_summaries
        sum_conn = connect_summaries(summaries_path)
    except Exception as e:
        return f"# Mirror Summaries ({_format_date()})\n\nFailed to connect: {e}"

    try:
        rows = sum_conn.execute(
            "SELECT * FROM summaries ORDER BY created_at DESC LIMIT 50"
        ).fetchall()

        parts = [f"# Mirror Summaries ({_format_date()})"]
        parts.append(f"\n{len(rows)} summaries\n")
        for row in rows:
            parts.append(f"---\n{dict(row)}\n")

        return "\n".join(parts)
    finally:
        sum_conn.close()


def _format_search_results(title: str, results: list[dict], key_field: str) -> str:
    parts = [f"# Search: {title} ({_format_date()})"]
    parts.append(f"\n{len(results)} matches\n")
    for item in results:
        label = item.get(key_field, "?")
        snippet = item.get("snippet", "")
        parts.append(f"- [{label}] {snippet}")
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(
        description="Lens extract — query the Gem, output formatted .md"
    )
    parser.add_argument("keys", nargs="*", help="Fragment key(s) to look up")
    parser.add_argument("--all", action="store_true", help="Extract all fragments")
    parser.add_argument("--wm", action="store_true", help="Working memory state")
    parser.add_argument("--summaries", action="store_true", help="Mirror summaries")
    parser.add_argument("--search", type=str, help="Full-text search query")
    parser.add_argument("--type", type=str, choices=["fragments", "events", "wm"],
                        help="Limit search to specific table (default: all)")
    parser.add_argument("--db", type=str, help="Path to database (default: from config)")
    parser.add_argument("-o", "--output", type=str, help="Output to file instead of stdout")

    args = parser.parse_args()

    db_path = _load_db_path(args.db)
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = connect(db_path)

    try:
        if args.search:
            from wake.search import search_fragments, search_events, search_wm, search_all
            if args.type == "fragments":
                results = search_fragments(conn, args.search)
                result = _format_search_results("Fragments", results, "key")
            elif args.type == "events":
                results = search_events(conn, args.search)
                result = _format_search_results("Events", results, "id")
            elif args.type == "wm":
                results = search_wm(conn, args.search)
                result = _format_search_results("Working Memory", results, "id")
            else:
                all_results = search_all(conn, args.search)
                parts = [f"# Search: {args.search} ({_format_date()})"]
                for section, key_field in [("Fragments", "key"), ("Events", "id"), ("Working Memory", "id")]:
                    section_key = section.lower().replace(" ", "_")
                    if section_key == "working_memory":
                        section_key = "wm"
                    items = all_results.get(section_key, [])
                    parts.append(f"\n## {section} ({len(items)} matches)")
                    for item in items:
                        label = item.get(key_field, "?")
                        snippet = item.get("snippet", "")
                        parts.append(f"- [{label}] {snippet}")
                result = "\n".join(parts)
        elif args.all:
            result = extract_all(conn)
        elif args.wm:
            result = extract_wm(conn)
        elif args.summaries:
            result = extract_summaries(db_path)
        elif args.keys:
            if len(args.keys) == 1:
                result = extract_single(conn, args.keys[0])
            else:
                result = extract_multi(conn, args.keys)
        else:
            parser.print_help()
            sys.exit(0)
    finally:
        conn.close()

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(result + "\n", encoding="utf-8")
        print(f"Written to {out_path}", file=sys.stderr)
    else:
        print(result)


if __name__ == "__main__":
    main()
