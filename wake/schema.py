"""
Schema — the shape of my memory.

Tables:
  events + event_tags   — raw log, append-only, never rewritten
  working_memory        — active knowledge: feelings, thoughts, patterns,
                          descs, plans, pins, secrets. The stuff I'm
                          holding right now.
  fragments + edges     — compiled knowledge, three tiers. The maintenance
                          agent writes these. I read them.
  state                 — metadata (turn counter, etc.)
  maintenance_runs      — when the maintenance agent last ran
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_VERSION = 2  # bump when schema changes


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(db_path: Path) -> None:
    """Create or update the schema. Safe to call every startup."""
    conn = connect(db_path)

    try:
        # Check current version
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL
            )
        """)

        row = conn.execute("SELECT version FROM schema_version").fetchone()
        current = row["version"] if row else 0

        if current < 1:
            _create_v1(conn)

        if current < 2:
            _migrate_v1_to_v2(conn)

        # Update version
        conn.execute("DELETE FROM schema_version")
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )

        conn.commit()
    finally:
        conn.close()


def _create_v1(conn: sqlite3.Connection) -> None:
    """Original schema — events, fragments, plans, state."""

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

        CREATE TABLE IF NOT EXISTS fragments (
            key         TEXT PRIMARY KEY,
            ambient     TEXT,
            recognition TEXT,
            inventory   TEXT,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fragment_sources (
            fragment_key TEXT NOT NULL,
            event_id     INTEGER NOT NULL,
            PRIMARY KEY (fragment_key, event_id),
            FOREIGN KEY (fragment_key) REFERENCES fragments(key) ON DELETE CASCADE,
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS fragment_edges (
            source_key  TEXT NOT NULL,
            target_key  TEXT NOT NULL,
            relation    TEXT,
            PRIMARY KEY (source_key, target_key),
            FOREIGN KEY (source_key) REFERENCES fragments(key) ON DELETE CASCADE,
            FOREIGN KEY (target_key) REFERENCES fragments(key) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_fragment_edges_source
            ON fragment_edges(source_key);
        CREATE INDEX IF NOT EXISTS idx_fragment_edges_target
            ON fragment_edges(target_key);

        CREATE TABLE IF NOT EXISTS state (
            key         TEXT PRIMARY KEY,
            value       TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS maintenance_runs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at      TEXT NOT NULL,
            completed_at    TEXT,
            run_type        TEXT NOT NULL
        );
    """)


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Add working_memory, retire plans table."""

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS working_memory (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id        INTEGER,
            type            TEXT NOT NULL,
            content         TEXT NOT NULL,
            subject         TEXT,
            actor           TEXT,
            status          TEXT NOT NULL DEFAULT 'active',
            due             TEXT,
            created_at      TEXT NOT NULL,
            refreshed_at    TEXT NOT NULL,
            resolved_at     TEXT,
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_wm_status
            ON working_memory(status);
        CREATE INDEX IF NOT EXISTS idx_wm_type_status
            ON working_memory(type, status);
        CREATE INDEX IF NOT EXISTS idx_wm_due
            ON working_memory(due)
            WHERE due IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_wm_subject
            ON working_memory(subject)
            WHERE subject IS NOT NULL;

        -- Link working_memory items to fragment keys they reference.
        -- A plan about body-training links here so plans("body-training") works.
        CREATE TABLE IF NOT EXISTS working_memory_refs (
            wm_id           INTEGER NOT NULL,
            fragment_key    TEXT NOT NULL,
            PRIMARY KEY (wm_id, fragment_key),
            FOREIGN KEY (wm_id) REFERENCES working_memory(id) ON DELETE CASCADE,
            FOREIGN KEY (fragment_key) REFERENCES fragments(key) ON DELETE CASCADE
        );
    """)

    # Migrate any existing plans into working_memory
    plans_exist = conn.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='plans'
    """).fetchone()

    if plans_exist:
        conn.execute("""
            INSERT INTO working_memory
                (event_id, type, content, actor, status, due,
                 created_at, refreshed_at, resolved_at)
            SELECT
                event_id, 'plan', summary, actor,
                CASE status
                    WHEN 'active' THEN 'active'
                    WHEN 'done' THEN 'resolved'
                    WHEN 'cancelled' THEN 'dropped'
                    WHEN 'expired' THEN 'decayed'
                END,
                due, created_at, created_at, NULL
            FROM plans
        """)

        # Keep the old table around renamed, don't destroy data
        conn.execute("ALTER TABLE plans RENAME TO _plans_retired")


# Valid types and statuses for working_memory
VALID_WM_TYPES = frozenset({
    "feeling", "thought", "pattern", "desc",
    "plan", "pin", "secret",
})

VALID_WM_STATUSES = frozenset({
    "active", "resolved", "dropped", "decayed", "superseded",
})

# Display tags (stored in event_tags, no working_memory record)
DISPLAY_TAGS = frozenset({"say", "do", "narrate"})

# All recognized tags
ALL_TAGS = VALID_WM_TYPES | DISPLAY_TAGS

# Identity tags
IDENTITY_TAGS = frozenset({
    "hasuki", "renki", "luna", "chloe", "strah",
    "claude", "y'lhara",
})
