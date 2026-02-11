"""
One-time script: backfill 'say' tags for Mono messages missing display tags.

Run against the live database AFTER deploying phases 1-2.
Recommend: test on a backup first.

Usage:
    python fix_missing_say_tags.py              # dry run (default)
    python fix_missing_say_tags.py --apply      # actually insert
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DB_PATH = Path("memory.sqlite")


def main():
    parser = argparse.ArgumentParser(description="Backfill say tags for untagged Mono messages")
    parser.add_argument("--apply", action="store_true", help="Actually insert (default is dry run)")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="Path to database")
    args = parser.parse_args()

    conn = sqlite3.connect(str(args.db))
    conn.row_factory = sqlite3.Row

    # Find Mono events with no display tags
    rows = conn.execute("""
        SELECT e.id, e.ts, substr(e.content, 1, 60) as preview
        FROM events e
        WHERE e.actor IS NOT NULL
          AND e.id NOT IN (
            SELECT event_id FROM event_tags
            WHERE tag IN ('say', 'do', 'narrate')
          )
        ORDER BY e.ts
    """).fetchall()

    print(f"Found {len(rows)} Mono messages without display tags.")

    if not rows:
        conn.close()
        return

    for row in rows[:10]:
        print(f"  [{row['id']}] {row['ts']} — {row['preview']}...")
    if len(rows) > 10:
        print(f"  ... and {len(rows) - 10} more")

    if not args.apply:
        print("\nDry run. Use --apply to insert say tags.")
        conn.close()
        return

    conn.executemany(
        "INSERT INTO event_tags (event_id, tag) VALUES (?, 'say')",
        [(row["id"],) for row in rows],
    )
    conn.commit()
    print(f"\nInserted {len(rows)} 'say' tags.")
    conn.close()


if __name__ == "__main__":
    main()
