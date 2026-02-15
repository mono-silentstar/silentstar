#!/usr/bin/env python3
"""
One-time migration: memory.sqlite → data/silentstar.sqlite

This script:
  1. Creates data/ and data/context/ directories
  2. Copies memory.sqlite → data/silentstar.sqlite (copy, not move — safe)
  3. Moves summaries.sqlite → data/summaries.sqlite (if exists)
  4. Verifies table counts match
  5. Prints server migration instructions

The old memory.sqlite stays in place until you manually delete it.
Run from repo root: python migrate_data_split.py
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent

OLD_DB = REPO_ROOT / "memory.sqlite"
NEW_DB = REPO_ROOT / "data" / "silentstar.sqlite"
OLD_SUMMARIES = REPO_ROOT / "summaries.sqlite"
NEW_SUMMARIES = REPO_ROOT / "data" / "summaries.sqlite"
CONTEXT_DIR = REPO_ROOT / "data" / "context"


def count_tables(db_path: Path) -> dict[str, int]:
    """Count rows in all tables."""
    conn = sqlite3.connect(str(db_path))
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'"
        ).fetchall()
        counts = {}
        for (name,) in tables:
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()
                counts[name] = row[0]
            except sqlite3.OperationalError:
                counts[name] = -1
        return counts
    finally:
        conn.close()


def main() -> int:
    print("silentstar data split migration")
    print("=" * 40)

    # Check source exists
    if not OLD_DB.exists():
        print(f"\nERROR: Source database not found: {OLD_DB}")
        print("Nothing to migrate.")
        return 1

    # Check destination doesn't already exist
    if NEW_DB.exists():
        print(f"\nWARNING: {NEW_DB} already exists.")
        print("If you want to re-run, delete it first.")
        return 1

    # 1. Create directories
    print(f"\n1. Creating directories...")
    NEW_DB.parent.mkdir(parents=True, exist_ok=True)
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"   Created: data/")
    print(f"   Created: data/context/")

    # 2. Copy memory.sqlite → data/silentstar.sqlite
    print(f"\n2. Copying {OLD_DB.name} → data/silentstar.sqlite ...")
    shutil.copy2(str(OLD_DB), str(NEW_DB))
    print(f"   Copied ({NEW_DB.stat().st_size:,} bytes)")

    # 3. Move summaries.sqlite if it exists
    if OLD_SUMMARIES.exists():
        if NEW_SUMMARIES.exists():
            print(f"\n3. WARNING: {NEW_SUMMARIES} already exists, skipping summaries move.")
        else:
            print(f"\n3. Moving summaries.sqlite → data/summaries.sqlite ...")
            shutil.move(str(OLD_SUMMARIES), str(NEW_SUMMARIES))
            print(f"   Moved.")
    else:
        print(f"\n3. No summaries.sqlite found (that's fine — Mirror hasn't run yet).")

    # 4. Verify
    print(f"\n4. Verifying table counts...")
    old_counts = count_tables(OLD_DB)
    new_counts = count_tables(NEW_DB)

    all_match = True
    for table in sorted(set(old_counts) | set(new_counts)):
        old_n = old_counts.get(table, "MISSING")
        new_n = new_counts.get(table, "MISSING")
        match = "OK" if old_n == new_n else "MISMATCH"
        if old_n != new_n:
            all_match = False
        print(f"   {table}: {old_n} → {new_n}  [{match}]")

    if all_match:
        print("\n   All tables match.")
    else:
        print("\n   WARNING: Some tables don't match! Check before deleting old DB.")

    # 5. Server instructions
    print(f"""
5. Server migration (manual step after deploy):
   ─────────────────────────────────────────────
   On the cPanel host, run:

     mkdir -p /home/monomeuk/silentstar/data/context
     cp /home/monomeuk/silentstar/memory.sqlite /home/monomeuk/silentstar/data/silentstar.sqlite

   Then update config.server.json (already updated in this commit):
     "db_path": "/home/monomeuk/silentstar/data/silentstar.sqlite"

   After verifying the new path works, you can remove:
     rm /home/monomeuk/silentstar/memory.sqlite

   The old memory.sqlite in the repo root is still here — safe to delete
   once you've confirmed everything works:
     rm {OLD_DB}
""")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
