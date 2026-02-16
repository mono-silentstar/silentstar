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


SCHEMA_VERSION = 5  # bump when schema changes


def connect(db_path: Path, events_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout = 5000")

    # ATTACH events database as 'ev' schema so ev.events / ev.event_tags work
    ev_path = events_path or db_path.parent / "events.sqlite"
    if ev_path.exists():
        conn.execute("ATTACH DATABASE ? AS ev", (str(ev_path),))
        # Cross-DB FKs (working_memory.event_id → events, fragment_sources.event_id
        # → events) can't resolve across schemas; leave foreign_keys OFF to avoid
        # errors. Events are append-only — referential integrity is guaranteed by
        # application logic. Same-DB FKs in events.sqlite enforce via its own conn.
    else:
        # Pre-migration: events still in main DB — FKs all resolve within main
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("ATTACH DATABASE ? AS ev", (str(db_path),))

    return conn


def migrate(db_path: Path) -> None:
    """Create or update the schema. Safe to call every startup."""
    # Ensure events DB schema is current (if it exists)
    from .events_schema import migrate_events
    events_path = db_path.parent / "events.sqlite"
    if events_path.exists():
        migrate_events(events_path)

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

        if current < 3:
            _migrate_v2_to_v3(conn)

        if current < 4:
            _migrate_v3_to_v4(conn)

        # v5 is conditional — only bump when events.sqlite is populated
        target_version = SCHEMA_VERSION
        if current < 5:
            if not _migrate_v4_to_v5(conn, db_path):
                target_version = 4  # stay at v4 until migrate_data_split.py runs

        # Update version
        conn.execute("DELETE FROM schema_version")
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)",
            (target_version,),
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
            turn            INTEGER,
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


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Add turn column to working_memory for accurate creation-turn tracking."""

    # Check if column already exists (safe for re-runs)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(working_memory)")}
    if "turn" not in cols:
        conn.execute("ALTER TABLE working_memory ADD COLUMN turn INTEGER")


def _migrate_v3_to_v4(conn: sqlite3.Connection) -> None:
    """Add FTS5 full-text search indexes."""
    conn.executescript("""
        CREATE VIRTUAL TABLE IF NOT EXISTS fragments_fts USING fts5(
            key, ambient, recognition, inventory,
            content='fragments', content_rowid='rowid'
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
            content, actor,
            content='events', content_rowid='id'
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS working_memory_fts USING fts5(
            content, subject, type,
            content='working_memory', content_rowid='id'
        );

        -- Sync triggers for fragments
        CREATE TRIGGER IF NOT EXISTS fragments_ai AFTER INSERT ON fragments BEGIN
            INSERT INTO fragments_fts(rowid, key, ambient, recognition, inventory)
            VALUES (new.rowid, new.key, new.ambient, new.recognition, new.inventory);
        END;
        CREATE TRIGGER IF NOT EXISTS fragments_ad AFTER DELETE ON fragments BEGIN
            INSERT INTO fragments_fts(fragments_fts, rowid, key, ambient, recognition, inventory)
            VALUES ('delete', old.rowid, old.key, old.ambient, old.recognition, old.inventory);
        END;
        CREATE TRIGGER IF NOT EXISTS fragments_au AFTER UPDATE ON fragments BEGIN
            INSERT INTO fragments_fts(fragments_fts, rowid, key, ambient, recognition, inventory)
            VALUES ('delete', old.rowid, old.key, old.ambient, old.recognition, old.inventory);
            INSERT INTO fragments_fts(rowid, key, ambient, recognition, inventory)
            VALUES (new.rowid, new.key, new.ambient, new.recognition, new.inventory);
        END;

        -- Sync triggers for events
        CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
            INSERT INTO events_fts(rowid, content, actor)
            VALUES (new.id, new.content, new.actor);
        END;
        CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
            INSERT INTO events_fts(events_fts, rowid, content, actor)
            VALUES ('delete', old.id, old.content, old.actor);
        END;
        CREATE TRIGGER IF NOT EXISTS events_au AFTER UPDATE ON events BEGIN
            INSERT INTO events_fts(events_fts, rowid, content, actor)
            VALUES ('delete', old.id, old.content, old.actor);
            INSERT INTO events_fts(rowid, content, actor)
            VALUES (new.id, new.content, new.actor);
        END;

        -- Sync triggers for working_memory
        CREATE TRIGGER IF NOT EXISTS wm_ai AFTER INSERT ON working_memory BEGIN
            INSERT INTO working_memory_fts(rowid, content, subject, type)
            VALUES (new.id, new.content, new.subject, new.type);
        END;
        CREATE TRIGGER IF NOT EXISTS wm_ad AFTER DELETE ON working_memory BEGIN
            INSERT INTO working_memory_fts(working_memory_fts, rowid, content, subject, type)
            VALUES ('delete', old.id, old.content, old.subject, old.type);
        END;
        CREATE TRIGGER IF NOT EXISTS wm_au AFTER UPDATE ON working_memory BEGIN
            INSERT INTO working_memory_fts(working_memory_fts, rowid, content, subject, type)
            VALUES ('delete', old.id, old.content, old.subject, old.type);
            INSERT INTO working_memory_fts(rowid, content, subject, type)
            VALUES (new.id, new.content, new.subject, new.type);
        END;
    """)

    # Rebuild to index existing data
    conn.execute("INSERT INTO fragments_fts(fragments_fts) VALUES ('rebuild')")
    conn.execute("INSERT INTO events_fts(events_fts) VALUES ('rebuild')")
    conn.execute("INSERT INTO working_memory_fts(working_memory_fts) VALUES ('rebuild')")


def _migrate_v4_to_v5(conn: sqlite3.Connection, db_path: Path) -> bool:
    """Drop events tables from main DB if events.sqlite has the data.

    After migrate_data_split.py copies events into events.sqlite, the
    main DB no longer needs events/event_tags/events_fts. This migration
    cleans them up. If events.sqlite doesn't exist or is empty, returns
    False — the tables stay in main until the migration script runs.

    Returns True if tables were dropped, False if migration was deferred.
    """
    events_path = db_path.parent / "events.sqlite"
    if not events_path.exists():
        return False  # Not migrated yet — keep events in main

    # Check events.sqlite directly (not via ev. attachment which may self-refer)
    ev_conn = sqlite3.connect(str(events_path))
    try:
        count = ev_conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    except sqlite3.OperationalError:
        count = 0  # events table doesn't exist in events.sqlite yet
    finally:
        ev_conn.close()

    if count == 0:
        return False  # events.sqlite exists but empty — keep main tables

    # Safe to drop — events live in events.sqlite now
    for stmt in [
        "DROP TRIGGER IF EXISTS events_ai",
        "DROP TRIGGER IF EXISTS events_ad",
        "DROP TRIGGER IF EXISTS events_au",
        "DROP TABLE IF EXISTS events_fts",
        "DROP TABLE IF EXISTS event_tags",
        "DROP TABLE IF EXISTS events",
    ]:
        conn.execute(stmt)

    return True


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
