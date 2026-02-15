#!/usr/bin/env python3
"""
Run the Mirror — manual testing entry point.

Usage:
  python run_mirror.py                          # uses defaults
  python run_mirror.py --db path/to/memory.sqlite
  python run_mirror.py --dry-run                # show chunk detection + DO-density, no API calls
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.mirror import MirrorAgent


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Mirror compression agent")
    parser.add_argument(
        "--db",
        default=str(REPO_ROOT / "data" / "silentstar.sqlite"),
        help="Path to silentstar.sqlite (default: data/silentstar.sqlite)",
    )
    parser.add_argument(
        "--summaries",
        default=str(REPO_ROOT / "data" / "summaries.sqlite"),
        help="Path to summaries.sqlite (default: data/summaries.sqlite)",
    )
    parser.add_argument(
        "--prompts",
        default=str(REPO_ROOT / "mdfiles" / "claude"),
        help="Path to prompt files directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show chunk detection and DO-density without making API calls",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Anthropic API key (default: ANTHROPIC_API_KEY env var)",
    )
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
        return 1

    summaries_path = None
    if args.summaries:
        summaries_path = Path(args.summaries).expanduser().resolve()

    prompt_dir = Path(args.prompts).expanduser().resolve()
    if not prompt_dir.is_dir():
        print(f"ERROR: Prompt directory not found: {prompt_dir}", file=sys.stderr)
        return 1

    agent = MirrorAgent(
        db_path=db_path,
        summaries_path=summaries_path,
        prompt_dir=prompt_dir,
        api_key=args.api_key,
        dry_run=args.dry_run,
    )

    print(f"Mirror agent starting...")
    print(f"  db: {db_path}")
    print(f"  summaries: {agent.summaries_path}")
    print(f"  prompts: {prompt_dir}")
    print(f"  dry_run: {args.dry_run}")
    print()

    result = agent.execute()

    if result.notes:
        for note in result.notes:
            print(f"  {note}")

    if result.errors:
        print()
        for error in result.errors:
            print(f"  ERROR: {error}", file=sys.stderr)
        return 1

    print()
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
