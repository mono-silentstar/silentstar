"""
Recall — how I look things up.

Exact key lookup. No fuzzy matching. The keys I know come from
ambient prose — [bracketed words] that are simultaneously my
vocabulary and the database index.

Three depths:
  ambient     — always visible, never needs lookup
  recognition — the story + relational knowledge (Loom-enriched)
  inventory   — full detail, every piece, the complete catalogue

Default is deep (inventory). The token budget in assembly is the
natural limiter — the Heart can go deep on 2-3 fragments per turn,
which is enough for specific recommendations. Items live in
inventory tiers of their parent fragments, not as separate fragments.
This keeps the graph at concept-level (wardrobe, fairy, jirai)
while inventory tiers hold item-level detail.

Neighbor-pull: when I recall a fragment, its graph neighbors
surface briefly at ambient depth with faster decay.

Plans: a separate lookup for working memory items. Queryable
by topic (fragment key) or time window. Bypasses submersion —
shows everything active regardless of current decay score.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path


@dataclass
class RecallResult:
    """What comes back when I tug a thread."""
    key: str
    content: str                          # the tier content I asked for
    depth: str                            # which tier was returned
    neighbors: list[NeighborResult]       # adjacent fragments, ambient tier


@dataclass
class NeighborResult:
    """A neighbor fragment surfaced by proximity."""
    key: str
    ambient: str                          # only the ambient tier
    relation: str                         # how it connects


from .schema import connect as _connect


def recall(
    key: str,
    db_path: str | Path,
    deep: bool = True,
) -> RecallResult | None:
    """
    Look up a fragment by exact key.

    Returns inventory tier by default (deep=True). The token budget
    in assembly naturally limits how many fragments fit — going deep
    on 2-3 fragments per turn is fine. Pass deep=False for recognition
    only (lighter, used by tools that need many keys at once).

    Also pulls neighbor fragments at ambient depth.

    Returns None if the key doesn't exist — which means the ambient
    prose referenced something that isn't in the database. That's
    a sync issue the maintenance agent should catch.
    """
    conn = _connect(db_path)

    try:
        # Pull the fragment
        tier = "inventory" if deep else "recognition"
        row = conn.execute(
            "SELECT key, ambient, recognition, inventory FROM fragments WHERE key = ?",
            (key,),
        ).fetchone()

        if row is None:
            return None

        # Use requested tier, fall back to recognition, then ambient
        content = row[tier] or row["recognition"] or row["ambient"] or ""

        # Pull neighbors via edges
        edges = conn.execute(
            """
            SELECT f.key, f.ambient, e.relation
            FROM fragment_edges e
            JOIN fragments f ON f.key = e.target_key
            WHERE e.source_key = ?
            """,
            (key,),
        ).fetchall()

        neighbors = [
            NeighborResult(
                key=edge["key"],
                ambient=edge["ambient"] or "",
                relation=edge["relation"] or "",
            )
            for edge in edges
            if edge["ambient"]  # skip neighbors with no ambient content
        ]

        return RecallResult(
            key=key,
            content=content,
            depth=tier,
            neighbors=neighbors,
        )

    finally:
        conn.close()


def recall_multi(
    keys: list[str],
    db_path: str | Path,
    deep: bool = True,
) -> list[RecallResult]:
    """
    Look up multiple fragments. Deduplicates neighbors —
    if I recall fairy and jirai, and they're neighbors of each other,
    each appears once as a primary result, not again as a neighbor.
    """
    results = []
    seen_keys = set()

    for key in keys:
        result = recall(key, db_path, deep=deep)
        if result is not None:
            results.append(result)
            seen_keys.add(key)

    # Deduplicate neighbors — don't surface a key as a neighbor
    # if it was already recalled directly
    for result in results:
        result.neighbors = [n for n in result.neighbors if n.key not in seen_keys]
        # Also track neighbor keys to avoid duplicates across results
        for n in result.neighbors:
            seen_keys.add(n.key)

    return results


# --- Plans lookup ---


@dataclass
class PlanSummary:
    """A working memory item, surfaced by plans()."""
    id: int
    type: str
    content: str
    subject: str | None
    actor: str | None
    status: str
    due: datetime | None
    created_at: datetime
    refreshed_at: datetime
    phase: str                  # "submerged", "approaching", "overdue",
                                # "open-ended", "active", "grace"
    related_keys: list[str] = field(default_factory=list)


def _classify_plan_phase(
    now: datetime,
    due: datetime | None,
    created_at: datetime,
) -> str:
    """Determine what phase a timed plan is in."""
    if due is None:
        return "open-ended"

    hours_until_due = (due - now).total_seconds() / 3600.0

    if hours_until_due < -24:
        return "overdue"
    if hours_until_due < 0:
        return "grace"
    if hours_until_due < 48:
        return "approaching"

    hours_since_creation = (now - created_at).total_seconds() / 3600.0
    if hours_since_creation < 4:
        return "active"     # still in creation spike

    return "submerged"


def plans(
    db_path: str | Path,
    topic: str | None = None,
    when: str | None = None,
) -> list[PlanSummary]:
    """
    Look up working memory items. Bypasses submersion — shows everything
    active regardless of current decay score.

    plans()                     → all active items, sorted by due date
    plans(topic="body-training") → items linked to a fragment key or
                                    matching subject/content
    plans(when="next tuesday")   → items with due dates in a time window
                                    (requires dateparser for natural language)

    Returns PlanSummary objects with phase classification.
    """
    conn = _connect(db_path)
    now = datetime.now(timezone.utc)

    try:
        if topic:
            return _plans_by_topic(conn, now, topic)
        if when:
            return _plans_by_time(conn, now, when)
        return _plans_all(conn, now)
    finally:
        conn.close()


def _row_to_summary(row: sqlite3.Row, now: datetime, conn: sqlite3.Connection) -> PlanSummary:
    """Convert a working_memory row to a PlanSummary."""
    created = datetime.fromisoformat(row["created_at"]).replace(tzinfo=timezone.utc)
    refreshed = datetime.fromisoformat(row["refreshed_at"]).replace(tzinfo=timezone.utc)
    due = None
    if row["due"]:
        due = datetime.fromisoformat(row["due"]).replace(tzinfo=timezone.utc)

    # Get related fragment keys
    refs = conn.execute(
        "SELECT fragment_key FROM working_memory_refs WHERE wm_id = ?",
        (row["id"],),
    ).fetchall()
    related_keys = [r["fragment_key"] for r in refs]

    return PlanSummary(
        id=row["id"],
        type=row["type"],
        content=row["content"],
        subject=row["subject"],
        actor=row["actor"],
        status=row["status"],
        due=due,
        created_at=created,
        refreshed_at=refreshed,
        phase=_classify_plan_phase(now, due, created),
        related_keys=related_keys,
    )


def _plans_all(conn: sqlite3.Connection, now: datetime) -> list[PlanSummary]:
    """All active working memory items, due-dated first (sorted by due),
    then open-ended (sorted by created_at)."""
    rows = conn.execute("""
        SELECT * FROM working_memory
        WHERE status = 'active'
        ORDER BY
            CASE WHEN due IS NOT NULL THEN 0 ELSE 1 END,
            due ASC,
            created_at DESC
    """).fetchall()

    return [_row_to_summary(r, now, conn) for r in rows]


def _plans_by_topic(
    conn: sqlite3.Connection,
    now: datetime,
    topic: str,
) -> list[PlanSummary]:
    """Items linked to a fragment key, or matching subject/content."""
    # First: check working_memory_refs for fragment key matches
    by_ref = conn.execute("""
        SELECT wm.* FROM working_memory wm
        INNER JOIN working_memory_refs ref ON ref.wm_id = wm.id
        WHERE wm.status = 'active'
          AND ref.fragment_key = ?
    """, (topic,)).fetchall()

    ref_ids = {r["id"] for r in by_ref}

    # Second: text match on subject and content
    by_text = conn.execute("""
        SELECT * FROM working_memory
        WHERE status = 'active'
          AND (subject LIKE ? OR content LIKE ?)
    """, (f"%{topic}%", f"%{topic}%")).fetchall()

    # Merge, dedup
    all_rows = list(by_ref)
    for r in by_text:
        if r["id"] not in ref_ids:
            all_rows.append(r)

    return [_row_to_summary(r, now, conn) for r in all_rows]


def _plans_by_time(
    conn: sqlite3.Connection,
    now: datetime,
    when: str,
) -> list[PlanSummary]:
    """Items with due dates matching a time expression.

    Tries dateparser for natural language. Falls back to simple
    keyword matching if dateparser isn't available.
    """
    # Try to parse the time expression
    target = _parse_time_expression(when, now)

    if target is None:
        # Fallback: text search for the time expression in content
        rows = conn.execute("""
            SELECT * FROM working_memory
            WHERE status = 'active'
              AND (content LIKE ? OR due LIKE ?)
        """, (f"%{when}%", f"%{when}%")).fetchall()
        return [_row_to_summary(r, now, conn) for r in rows]

    # Search within a day window around the target
    window_start = target - timedelta(hours=12)
    window_end = target + timedelta(hours=12)

    rows = conn.execute("""
        SELECT * FROM working_memory
        WHERE status = 'active'
          AND due IS NOT NULL
          AND due >= ? AND due <= ?
        ORDER BY due ASC
    """, (window_start.isoformat(), window_end.isoformat())).fetchall()

    return [_row_to_summary(r, now, conn) for r in rows]


def _parse_time_expression(when: str, now: datetime) -> datetime | None:
    """Parse a natural language time expression into a datetime.
    Uses dateparser if available, otherwise returns None."""
    try:
        import dateparser
        result = dateparser.parse(
            when,
            settings={
                "RELATIVE_BASE": now.replace(tzinfo=None),
                "PREFER_DATES_FROM": "future",
            },
        )
        if result:
            return result.replace(tzinfo=timezone.utc)
    except ImportError:
        pass

    return None
