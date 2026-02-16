#!/usr/bin/env python3
"""
migrate_data_split.py — split events from silentstar.sqlite into events.sqlite.

Usage:
    python migrate_data_split.py [--db data/silentstar.sqlite]

Steps:
    1. Back up silentstar.sqlite
    2. Create events.sqlite via migrate_events()
    3. Copy events + event_tags rows
    4. Rebuild events_fts index
    5. Drop events tables from silentstar.sqlite
    6. Print row counts for verification
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from wake.events_schema import migrate_events, connect_events


def main():
    parser = argparse.ArgumentParser(description="Split events into events.sqlite")
    parser.add_argument("--db", type=str, help="Path to silentstar.sqlite")
    args = parser.parse_args()

    # Resolve DB path
    if args.db:
        db_path = Path(args.db)
    else:
        config_path = Path("worker/config.json")
        if config_path.exists():
            with open(config_path) as f:
                cfg = json.load(f)
            db_path = Path(cfg.get("db_path", "data/silentstar.sqlite"))
        else:
            db_path = Path("data/silentstar.sqlite")

    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    events_path = db_path.parent / "events.sqlite"

    # 1. Back up
    backup_name = db_path.with_suffix(
        f".sqlite.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    print(f"Backing up {db_path} → {backup_name}")
    shutil.copy2(db_path, backup_name)

    # 2. Create events.sqlite schema
    print(f"Creating {events_path}...")
    migrate_events(events_path)

    # 3. Copy data via ATTACH
    print("Copying events + event_tags...")
    ev_conn = connect_events(events_path)
    try:
        ev_conn.execute("ATTACH DATABASE ? AS gem", (str(db_path),))

        # Check source has data
        src_events = ev_conn.execute(
            "SELECT COUNT(*) FROM gem.events"
        ).fetchone()[0]
        src_tags = ev_conn.execute(
            "SELECT COUNT(*) FROM gem.event_tags"
        ).fetchone()[0]

        if src_events == 0:
            print("No events to copy.")
            return

        # Copy events (preserve IDs)
        ev_conn.execute("""
            INSERT OR IGNORE INTO events (id, ts, content, actor, image_path)
            SELECT id, ts, content, actor, image_path FROM gem.events
        """)

        # Copy event_tags
        ev_conn.execute("""
            INSERT OR IGNORE INTO event_tags (event_id, tag)
            SELECT event_id, tag FROM gem.event_tags
        """)

        ev_conn.commit()

        # 4. FTS populated by triggers on INSERT — optimize the index
        print("Optimizing events_fts index...")
        ev_conn.execute("INSERT INTO events_fts(events_fts) VALUES ('optimize')")
        ev_conn.commit()

        # Verify
        ev_events = ev_conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        ev_tags = ev_conn.execute("SELECT COUNT(*) FROM event_tags").fetchone()[0]

        print(f"  source:        {src_events} events, {src_tags} event_tags")
        print(f"  events.sqlite: {ev_events} events, {ev_tags} event_tags")

        ev_conn.execute("DETACH DATABASE gem")
    finally:
        ev_conn.close()

    # 5. Drop old tables from silentstar.sqlite
    print("Dropping events tables from silentstar.sqlite...")
    gem_conn = sqlite3.connect(str(db_path))
    try:
        gem_conn.executescript("""
            DROP TRIGGER IF EXISTS events_ai;
            DROP TRIGGER IF EXISTS events_ad;
            DROP TRIGGER IF EXISTS events_au;
            DROP TABLE IF EXISTS events_fts;
            DROP TABLE IF EXISTS event_tags;
            DROP TABLE IF EXISTS events;
        """)

        # Bump schema version to 5 so migrate() knows tables are gone
        gem_conn.execute("DELETE FROM schema_version")
        gem_conn.execute("INSERT INTO schema_version (version) VALUES (5)")
        gem_conn.commit()
        print("Schema version bumped to 5.")
    finally:
        gem_conn.close()

    print(f"\nDone! Verify with:")
    print(f"  python -c \"from wake.schema import connect; from pathlib import Path; "
          f"c = connect(Path('{db_path}')); "
          f"print(c.execute('SELECT count(*) FROM ev.events').fetchone()[0])\"")


if __name__ == "__main__":
    main()
