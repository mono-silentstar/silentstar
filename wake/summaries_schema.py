"""
Summaries schema — the Mirror's output store.

Tables:
  summaries       — chunk summaries at all levels (L0, L1, L2)
  tag_suggestions — WM tags proposed by compression, staged for promotion
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_VERSION = 1


def connect_summaries(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def migrate_summaries(db_path: Path) -> None:
    """Create or update the summaries schema. Safe to call every startup."""
    conn = connect_summaries(db_path)

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
    """Initial summaries schema."""

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS summaries (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            level       TEXT NOT NULL DEFAULT 'L0',
            chunk_start INTEGER NOT NULL,
            chunk_end   INTEGER NOT NULL,
            content     TEXT NOT NULL,
            tokens      INTEGER,
            do_density  REAL,
            pipeline    TEXT,
            created_at  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_summaries_level
            ON summaries(level);
        CREATE INDEX IF NOT EXISTS idx_summaries_chunk_range
            ON summaries(chunk_start, chunk_end);

        CREATE TABLE IF NOT EXISTS tag_suggestions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            summary_id  INTEGER NOT NULL,
            type        TEXT NOT NULL CHECK(type IN ('pin', 'pattern', 'desc')),
            content     TEXT NOT NULL,
            subject     TEXT,
            status      TEXT NOT NULL DEFAULT 'suggested',
            created_at  TEXT NOT NULL,
            FOREIGN KEY (summary_id) REFERENCES summaries(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_tag_suggestions_summary
            ON tag_suggestions(summary_id);
        CREATE INDEX IF NOT EXISTS idx_tag_suggestions_status
            ON tag_suggestions(status);
    """)
