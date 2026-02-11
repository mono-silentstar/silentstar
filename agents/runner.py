"""
Runner — base interface for agents.

An agent is a task that reads from the database, does some work,
and writes back. Each agent has:
  - A name (for logging and audit)
  - A run_type (for maintenance_runs tracking)
  - A run() method that does the actual work

The runner handles setup, teardown, and audit logging.
"""

from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from wake.schema import connect


@dataclass
class AgentResult:
    """What an agent produced."""
    events_created: int = 0
    fragments_created: int = 0
    fragments_updated: int = 0
    working_memory_created: int = 0
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Deferred filesystem writes to apply after DB commit
    _post_commit_writes: list[tuple[Path, str]] = field(default_factory=list)


class Agent(ABC):
    """Base class for all agents."""

    name: str = "unnamed"
    run_type: str = "manual"

    def __init__(self, db_path: Path):
        self.db_path = db_path

    @abstractmethod
    def run(self, conn: sqlite3.Connection) -> AgentResult:
        """Do the actual work. Connection is provided, don't close it."""
        ...

    def execute(self) -> AgentResult:
        """Run the agent with audit logging and error handling."""
        conn = connect(self.db_path)
        now = datetime.now(timezone.utc).isoformat()

        # Log the start
        cursor = conn.execute(
            "INSERT INTO maintenance_runs (started_at, run_type) VALUES (?, ?)",
            (now, self.run_type),
        )
        run_id = cursor.lastrowid
        conn.commit()

        try:
            result = self.run(conn)
            conn.commit()

            # Apply deferred filesystem writes now that DB is committed
            for path, content in result._post_commit_writes:
                try:
                    path.write_text(content, encoding="utf-8")
                    result.notes.append(f"Wrote {path.name} ({len(content)} chars).")
                except Exception as e:
                    result.errors.append(f"Post-commit write to {path} failed: {e}")

            # Log completion
            conn.execute(
                "UPDATE maintenance_runs SET completed_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), run_id),
            )
            conn.commit()

            return result

        except Exception as e:
            conn.rollback()
            result = AgentResult(errors=[str(e)])
            return result

        finally:
            conn.close()
