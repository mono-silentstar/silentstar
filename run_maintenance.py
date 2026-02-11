#!/usr/bin/env python3
"""
CLI entry point for the maintenance agent.

Usage:
  python run_maintenance.py --weekly
  python run_maintenance.py --monthly
  python run_maintenance.py --monthly --model claude-sonnet-4-5-20250929
"""

import argparse
import sys
from pathlib import Path

# Project root — where this script lives
ROOT = Path(__file__).resolve().parent

# Add project root to path so imports work
sys.path.insert(0, str(ROOT))

from agents.claude_client import ClaudeConfig
from agents.maintenance import MaintenanceAgent
from wake.schema import migrate


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the maintenance agent to compile events into fragments."
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--weekly", action="store_const", const="weekly", dest="run_type",
        help="Light pass: process new events, update fragments.",
    )
    mode.add_argument(
        "--monthly", action="store_const", const="monthly", dest="run_type",
        help="Deep pass: full review of all fragments + edges.",
    )

    parser.add_argument(
        "--model", default="claude-opus-4-6",
        help="Model to use (default: claude-opus-4-6).",
    )
    parser.add_argument(
        "--db", default=None,
        help="Path to memory.sqlite (default: <project>/memory.sqlite).",
    )

    args = parser.parse_args()

    # Resolve paths
    db_path = Path(args.db) if args.db else ROOT / "memory.sqlite"
    ambient_path = ROOT / "ambient.md"
    agent_prompt_path = ROOT / "mdfiles" / "claude" / "maintenance-agent.md"

    if not db_path.exists():
        print(f"Error: database not found at {db_path}", file=sys.stderr)
        return 1

    if not agent_prompt_path.exists():
        print(
            f"Error: agent prompt not found at {agent_prompt_path}",
            file=sys.stderr,
        )
        return 1

    # Ensure schema is current
    migrate(db_path)

    # Build config
    config = ClaudeConfig(model=args.model)

    # Create and run
    agent = MaintenanceAgent(
        db_path=db_path,
        ambient_path=ambient_path,
        agent_prompt_path=agent_prompt_path,
        run_type=args.run_type,
        claude_config=config,
    )

    print(f"Running {args.run_type} maintenance pass (model: {args.model})...")
    result = agent.execute()

    # Print results
    for note in result.notes:
        print(f"  {note}")

    if result.fragments_created:
        print(f"  Fragments created: {result.fragments_created}")
    if result.fragments_updated:
        print(f"  Fragments updated: {result.fragments_updated}")
    if result.events_created:
        print(f"  Events logged: {result.events_created}")

    if result.errors:
        print("\nErrors:", file=sys.stderr)
        for err in result.errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
