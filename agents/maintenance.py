"""
Maintenance Agent — the one who tends the memory.

This agent reads raw events and compiles them into fragments.
It rewrites ambient.md. It's the one who makes sure the next
conversational Claude wakes up knowing what matters.

Runs on schedule: weekly (light), monthly (deep), manual.

REQUIRES CLAUDE API — currently a skeleton. The compile step
needs Claude to read events and author knowledge with taste.
Once API integration is wired, this becomes the real thing.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .runner import Agent, AgentResult


class MaintenanceAgent(Agent):
    """Compile events into fragments, rewrite ambient.md."""

    name = "maintenance"

    def __init__(
        self,
        db_path: Path,
        ambient_path: Path,
        agent_prompt_path: Path,
        run_type: str = "weekly",
    ):
        super().__init__(db_path)
        self.ambient_path = ambient_path
        self.agent_prompt_path = agent_prompt_path
        self.run_type = run_type

    def run(self, conn: sqlite3.Connection) -> AgentResult:
        result = AgentResult()

        # Find events since last completed maintenance run
        last_run = conn.execute("""
            SELECT started_at FROM maintenance_runs
            WHERE completed_at IS NOT NULL
              AND run_type IN ('weekly', 'monthly', 'bootstrap')
            ORDER BY started_at DESC
            LIMIT 1
        """).fetchone()

        since = last_run["started_at"] if last_run else "1970-01-01"

        new_events = conn.execute("""
            SELECT e.id, e.ts, e.content, e.actor,
                   GROUP_CONCAT(t.tag) as tags
            FROM events e
            LEFT JOIN event_tags t ON t.event_id = e.id
            WHERE e.ts > ?
            GROUP BY e.id
            ORDER BY e.ts ASC
        """, (since,)).fetchall()

        if not new_events:
            result.notes.append("No new events since last run.")
            return result

        result.notes.append(f"Found {len(new_events)} new events since {since}.")

        # --- This is where Claude API integration goes ---
        #
        # The maintenance agent prompt (from agent_prompt_path) tells
        # Claude how to compile events into fragments. The flow:
        #
        # 1. Load the maintenance agent prompt
        # 2. Format the new events as context
        # 3. If monthly: also load all existing fragments for review
        # 4. Send to Claude API
        # 5. Parse Claude's response for fragment operations:
        #    - CREATE fragment: key, ambient, recognition, inventory
        #    - UPDATE fragment: key, updated tiers
        #    - EDGE: source_key, target_key, relation
        #    - AMBIENT_REWRITE: new ambient.md content
        # 6. Apply all operations to the database
        # 7. Write ambient.md
        #
        # For now, we just log what would happen.

        result.notes.append(
            "SKELETON: Claude API not yet wired. "
            f"Would compile {len(new_events)} events into fragments."
        )

        # Load existing fragments for context
        fragment_count = conn.execute(
            "SELECT COUNT(*) FROM fragments"
        ).fetchone()[0]

        result.notes.append(f"Current fragments: {fragment_count}")

        if self.run_type == "monthly":
            result.notes.append("Monthly deep pass: would review all fragments for staleness.")

        return result


class BootstrapAgent(Agent):
    """Initial population — compile existing markdown files into fragments.

    Unlike FileIngestAgent (which stores files as-is), this agent would
    use Claude to read the files and compile them with taste — deciding
    what's ambient vs recognition vs inventory, authoring edges, and
    writing the initial ambient.md.

    For now, populate_fragments.py handles this manually. Once Claude
    API is wired, this agent replaces it.
    """

    name = "bootstrap"
    run_type = "bootstrap"

    def __init__(
        self,
        db_path: Path,
        source_dir: Path,
        ambient_path: Path,
        agent_prompt_path: Path,
    ):
        super().__init__(db_path)
        self.source_dir = source_dir
        self.ambient_path = ambient_path
        self.agent_prompt_path = agent_prompt_path

    def run(self, conn: sqlite3.Connection) -> AgentResult:
        result = AgentResult()

        files = sorted(self.source_dir.glob("*.md"))
        result.notes.append(
            f"SKELETON: Would compile {len(files)} files from {self.source_dir} "
            "using Claude API. Use populate_fragments.py or FileIngestAgent for now."
        )

        return result
