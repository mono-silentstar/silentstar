"""
Lifecycle — managing working memory state.

When tagged content comes in, this module decides what to do:
  - Create new working memory items
  - Supersede old ones (new feeling replaces old, new desc replaces old)
  - Resolve plans (done/cancel)
  - Drop pins
  - Link items to fragment keys
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path

from wake.schema import connect, VALID_WM_TYPES, DISPLAY_TAGS
from .parse import (
    ParsedMessage,
    TaggedSpan,
    extract_fragment_keys,
)


@dataclass
class IngestResult:
    """What happened when we ingested a message."""
    event_id: int
    wm_created: list[int]       # working_memory IDs created
    wm_resolved: list[int]      # working_memory IDs resolved/dropped
    wm_superseded: list[int]    # working_memory IDs superseded
    turn: int                   # current turn number


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_due_date(text: str) -> str | None:
    """Try to extract a due date from plan text.
    Uses dateparser if available, otherwise returns None."""
    try:
        import dateparser
        now = datetime.now(timezone.utc)
        result = dateparser.parse(
            text,
            settings={
                "RELATIVE_BASE": now.replace(tzinfo=None),
                "PREFER_DATES_FROM": "future",
            },
        )
        if result and result > now.replace(tzinfo=None):
            return result.replace(tzinfo=timezone.utc).isoformat()
    except ImportError:
        pass

    return None


def _fuzzy_match_content(query: str, candidate: str) -> float:
    """Simple word-overlap similarity for matching plan/pin content.
    Returns 0.0–1.0."""
    q_words = set(query.lower().split())
    c_words = set(candidate.lower().split())

    if not q_words or not c_words:
        return 0.0

    overlap = q_words & c_words
    return len(overlap) / max(len(q_words), len(c_words))


def ingest(
    db_path: Path,
    parsed: ParsedMessage,
    is_claude: bool = False,
    image_path: str | None = None,
) -> IngestResult:
    """
    Ingest a parsed message into the database.

    1. Create event + event_tags
    2. For each tagged span, handle the lifecycle:
       - Display tags: just store in event_tags
       - WM tags: create/supersede/resolve working_memory records
    3. Increment turn counter (for Mono messages only)
    """
    conn = connect(db_path)
    now = _now_iso()

    wm_created = []
    wm_resolved = []
    wm_superseded = []

    try:
        # 1. Create event
        cursor = conn.execute(
            """INSERT INTO events (ts, content, actor, image_path)
               VALUES (?, ?, ?, ?)""",
            (now, parsed.raw, parsed.actor, image_path),
        )
        event_id = cursor.lastrowid

        # 2. Store event tags
        all_tags = {span.tag for span in parsed.spans}
        for tag in all_tags:
            conn.execute(
                "INSERT OR IGNORE INTO event_tags (event_id, tag) VALUES (?, ?)",
                (event_id, tag),
            )

        # 3. Process each span
        for span in parsed.spans:
            if span.tag in DISPLAY_TAGS:
                continue  # already stored as event_tag, no WM action

            if span.tag not in VALID_WM_TYPES:
                continue

            if span.modifier == "resolve":
                resolved = _resolve_plan(conn, span, now)
                wm_resolved.extend(resolved)
            elif span.modifier == "cancel":
                resolved = _cancel_plan(conn, span, now)
                wm_resolved.extend(resolved)
            elif span.modifier == "drop":
                dropped = _drop_pin(conn, span, now)
                wm_resolved.extend(dropped)
            else:
                created, superseded = _create_wm_item(
                    conn, event_id, span, parsed.actor, now
                )
                wm_created.extend(created)
                wm_superseded.extend(superseded)

        # 4. Increment turn counter (Mono messages only)
        turn = _get_turn(conn)
        if not is_claude:
            turn += 1
            _set_turn(conn, turn)

        conn.commit()

        return IngestResult(
            event_id=event_id,
            wm_created=wm_created,
            wm_resolved=wm_resolved,
            wm_superseded=wm_superseded,
            turn=turn,
        )

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _create_wm_item(
    conn: sqlite3.Connection,
    event_id: int,
    span: TaggedSpan,
    actor: str | None,
    now: str,
) -> tuple[list[int], list[int]]:
    """Create a new working memory item. Handle supersession for types
    that auto-supersede (feeling, desc)."""

    created = []
    superseded = []

    # Determine subject for supersession matching
    subject = _infer_subject(span)

    # Handle supersession by type
    if span.tag == "feeling":
        # Feelings: supersede ALL active feelings (only one at a time)
        old = conn.execute(
            "SELECT id FROM working_memory WHERE type = 'feeling' AND status = 'active'"
        ).fetchall()
        for row in old:
            conn.execute(
                "UPDATE working_memory SET status = 'superseded', resolved_at = ? WHERE id = ?",
                (now, row["id"]),
            )
            superseded.append(row["id"])

    elif span.tag == "desc" and subject:
        # Descs: supersede active descs with same subject
        old = conn.execute(
            "SELECT id FROM working_memory WHERE type = 'desc' AND status = 'active' AND subject = ?",
            (subject,),
        ).fetchall()
        for row in old:
            conn.execute(
                "UPDATE working_memory SET status = 'superseded', resolved_at = ? WHERE id = ?",
                (now, row["id"]),
            )
            superseded.append(row["id"])

    # Parse due date for plans
    due = None
    if span.tag == "plan":
        due = _parse_due_date(span.content)

    # Create the item
    cursor = conn.execute("""
        INSERT INTO working_memory
            (event_id, type, content, subject, actor, status, due,
             created_at, refreshed_at)
        VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
    """, (event_id, span.tag, span.content, subject, actor, due, now, now))

    wm_id = cursor.lastrowid
    created.append(wm_id)

    # Link to fragment keys mentioned in the content
    keys = extract_fragment_keys(span.content)
    for key in keys:
        # Only link if the fragment actually exists
        exists = conn.execute(
            "SELECT 1 FROM fragments WHERE key = ?", (key,)
        ).fetchone()
        if exists:
            conn.execute(
                "INSERT OR IGNORE INTO working_memory_refs (wm_id, fragment_key) VALUES (?, ?)",
                (wm_id, key),
            )

    return created, superseded


def _resolve_plan(
    conn: sqlite3.Connection,
    span: TaggedSpan,
    now: str,
) -> list[int]:
    """Find and resolve the best-matching active plan."""
    return _match_and_update(conn, "plan", span.content, "resolved", now)


def _cancel_plan(
    conn: sqlite3.Connection,
    span: TaggedSpan,
    now: str,
) -> list[int]:
    """Find and cancel the best-matching active plan."""
    return _match_and_update(conn, "plan", span.content, "dropped", now)


def _drop_pin(
    conn: sqlite3.Connection,
    span: TaggedSpan,
    now: str,
) -> list[int]:
    """Find and drop the best-matching active pin."""
    return _match_and_update(conn, "pin", span.content, "dropped", now)


def _match_and_update(
    conn: sqlite3.Connection,
    wm_type: str,
    query: str,
    new_status: str,
    now: str,
) -> list[int]:
    """Find the best-matching active WM item by content similarity,
    then update its status."""
    rows = conn.execute(
        "SELECT id, content FROM working_memory WHERE type = ? AND status = 'active'",
        (wm_type,),
    ).fetchall()

    if not rows:
        return []

    # Score each by word overlap
    scored = [
        (row["id"], _fuzzy_match_content(query, row["content"]))
        for row in rows
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Take the best match if it's at least somewhat relevant
    best_id, best_score = scored[0]
    if best_score < 0.15:
        return []

    conn.execute(
        "UPDATE working_memory SET status = ?, resolved_at = ? WHERE id = ?",
        (new_status, now, best_id),
    )

    return [best_id]


def _infer_subject(span: TaggedSpan) -> str | None:
    """Try to infer a subject/topic for a tagged span.
    Used for supersession matching (e.g., desc of same area)."""

    # For descs, the subject might be explicitly stated
    # e.g., <desc>room corner: messy desk...</desc> → "room corner"
    if span.tag == "desc":
        # Look for "subject: content" pattern
        colon_match = re.match(r"^([^:]{3,30}):\s", span.content)
        if colon_match:
            return colon_match.group(1).strip().lower()

    return None


def _get_turn(conn: sqlite3.Connection) -> int:
    """Get current turn number from state table."""
    row = conn.execute(
        "SELECT value FROM state WHERE key = 'current_turn'"
    ).fetchone()
    return int(row["value"]) if row else 0


def _set_turn(conn: sqlite3.Connection, turn: int) -> None:
    """Set current turn number."""
    now = _now_iso()
    conn.execute("""
        INSERT INTO state (key, value, updated_at)
        VALUES ('current_turn', ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?
    """, (str(turn), now, str(turn), now))
