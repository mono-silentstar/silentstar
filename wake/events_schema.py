"""
Events schema — the event log store.

Tables:
  events      — raw message log, append-only
  event_tags  — per-event tag associations
  events_fts  — FTS5 full-text search index
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_VERSION = 1


def connect_events(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def migrate_events(db_path: Path) -> None:
    """Create or update the events schema. Safe to call every startup."""
    conn = connect_events(db_path)

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
    """Initial events schema — events, event_tags, FTS5 + sync triggers."""

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            content     TEXT NOT NULL,
            actor       TEXT,
            image_path  TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

        CREATE TABLE IF NOT EXISTS event_tags (
            event_id    INTEGER NOT NULL,
            tag         TEXT NOT NULL,
            PRIMARY KEY (event_id, tag),
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_event_tags_tag ON event_tags(tag);

        -- Standalone FTS5 (no content= directive) — stores its own copy
        -- of the data. Required because content-sync FTS5 resolves the
        -- content table in the main schema, which breaks when ATTACHed.
        CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
            content, actor
        );

        -- Sync triggers
        CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
            INSERT INTO events_fts(rowid, content, actor)
            VALUES (new.id, new.content, new.actor);
        END;
        CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
            DELETE FROM events_fts WHERE rowid = old.id;
        END;
        CREATE TRIGGER IF NOT EXISTS events_au AFTER UPDATE ON events BEGIN
            DELETE FROM events_fts WHERE rowid = old.id;
            INSERT INTO events_fts(rowid, content, actor)
            VALUES (new.id, new.content, new.actor);
        END;
    """)
