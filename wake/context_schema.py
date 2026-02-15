"""
Context snapshots — daily records of what the Heart saw.

Each day gets its own SQLite file in data/context/YYYY-MM-DD.sqlite.
Every turn appends a snapshot: the full rendered system + user text,
token counts per section, and which items were included.

For debugging "vibe" — lets you replay exactly what context
the Heart was given on any turn.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1


def connect_context(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def migrate_context(db_path: Path) -> None:
    """Create or update the context snapshot schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect_context(db_path)

    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL
            )
        """)

        row = conn.execute("SELECT version FROM schema_version").fetchone()
        current = row["version"] if row else 0

        if current < 1:
            _create_v1(conn)

        conn.execute("DELETE FROM schema_version")
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )

        conn.commit()
    finally:
        conn.close()


def _create_v1(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            turn            INTEGER NOT NULL,
            ts              TEXT NOT NULL,
            system_text     TEXT NOT NULL,
            user_text       TEXT NOT NULL,
            token_counts    TEXT NOT NULL,
            items_included  TEXT NOT NULL,
            created_at      TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_turn
            ON snapshots(turn);
    """)


def save_snapshot(
    context_path: Path,
    turn: int,
    system_text: str,
    user_text: str,
    token_counts: dict,
    items_included: dict,
) -> None:
    """Append a snapshot to the daily context DB.

    Safe to call — creates the DB and schema if needed.
    """
    migrate_context(context_path)
    conn = connect_context(context_path)
    now = datetime.now(timezone.utc).isoformat()

    try:
        conn.execute(
            """
            INSERT INTO snapshots (turn, ts, system_text, user_text,
                                   token_counts, items_included, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                turn,
                now,
                system_text,
                user_text,
                json.dumps(token_counts),
                json.dumps(items_included),
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
