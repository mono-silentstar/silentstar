"""
Maintenance Agent — the one who tends the memory.

This agent reads raw events and compiles them into fragments.
It rewrites ambient.md. It's the one who makes sure the next
conversational Claude wakes up knowing what matters.

Runs on schedule: weekly (light), monthly (deep), manual.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .claude_client import ClaudeConfig, send as claude_send
from .runner import Agent, AgentResult


# Max tokens by run type
_MAX_TOKENS = {
    "weekly": 8192,
    "monthly": 16384,
    "bootstrap": 16384,
}

# Timeout for maintenance calls (10 minutes)
_TIMEOUT = 600


class MaintenanceAgent(Agent):
    """Compile events into fragments, rewrite ambient.md."""

    name = "maintenance"

    def __init__(
        self,
        db_path: Path,
        ambient_path: Path,
        agent_prompt_path: Path,
        run_type: str = "weekly",
        claude_config: ClaudeConfig | None = None,
    ):
        super().__init__(db_path)
        self.ambient_path = ambient_path
        self.agent_prompt_path = agent_prompt_path
        self.run_type = run_type
        self.claude_config = claude_config or ClaudeConfig()

    def run(self, conn: sqlite3.Connection) -> AgentResult:
        result = AgentResult()

        # --- 1. Find events since last completed maintenance run ---
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

        # Track valid event IDs for source_events validation
        valid_event_ids = {row["id"] for row in new_events}

        # --- 2. Gather existing context ---
        if self.run_type == "monthly":
            fragments = conn.execute("""
                SELECT key, ambient, recognition, inventory,
                       created_at, updated_at
                FROM fragments
                ORDER BY key
            """).fetchall()
        else:
            fragments = conn.execute("""
                SELECT key, ambient FROM fragments ORDER BY key
            """).fetchall()

        edges = conn.execute("""
            SELECT source_key, target_key, relation
            FROM fragment_edges
            ORDER BY source_key, target_key
        """).fetchall()

        active_wm = conn.execute("""
            SELECT id, type, content, subject, actor, status, due,
                   created_at, refreshed_at
            FROM working_memory
            WHERE status = 'active'
            ORDER BY created_at ASC
        """).fetchall()

        # --- 3. Load system prompt ---
        system_prompt = self.agent_prompt_path.read_text(encoding="utf-8")

        # --- 4. Format user message ---
        user_message = self._format_user_message(
            new_events, fragments, edges, active_wm
        )

        # --- 5. Call Claude ---
        config = ClaudeConfig(
            model=self.claude_config.model,
            timeout_seconds=_TIMEOUT,
            max_tokens=_MAX_TOKENS.get(self.run_type, 8192),
            transport=self.claude_config.transport,
            api_key=self.claude_config.api_key,
        )

        result.notes.append(
            f"Calling Claude ({config.model}, "
            f"max_tokens={config.max_tokens})..."
        )

        response = claude_send(
            user_message,
            config=config,
            system_prompt=system_prompt,
        )

        if not response.success:
            result.errors.append(f"Claude API error: {response.error}")
            return result

        result.notes.append(
            f"Got response ({len(response.text)} chars)."
        )

        # --- 6. Parse operations ---
        ops, parse_errors = _parse_operations(response.text)
        result.errors.extend(parse_errors)
        result.notes.append(f"Parsed {len(ops)} operations.")

        # --- 7. Apply operations ---
        _apply_operations(conn, ops, self.ambient_path, result, valid_event_ids)

        # --- 8. Log reasoning as system event ---
        # Extract reasoning (everything before <operations>)
        reasoning = response.text
        ops_match = re.search(r"<operations>", reasoning)
        if ops_match:
            reasoning = reasoning[:ops_match.start()].strip()

        if reasoning:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO events (ts, content, actor) VALUES (?, ?, ?)",
                (now, f"[maintenance/{self.run_type}] {reasoning}", "system"),
            )
            result.events_created += 1

        return result

    def _format_user_message(
        self,
        events: list,
        fragments: list,
        edges: list,
        active_wm: list,
    ) -> str:
        parts = []

        # Run type
        parts.append(f"## RUN TYPE\n{self.run_type}")

        # New events
        parts.append("## NEW EVENTS")
        for e in events:
            tags = f" [{e['tags']}]" if e["tags"] else ""
            actor = e["actor"] or "unknown"
            parts.append(
                f"[event {e['id']}] {e['ts']} ({actor}){tags}\n{e['content']}"
            )

        # Existing fragments
        parts.append("## EXISTING FRAGMENTS")
        if not fragments:
            parts.append("(none)")
        else:
            for f in fragments:
                lines = [f"### {f['key']}"]
                lines.append(f"ambient: {f['ambient'] or '(empty)'}")
                # Monthly gets full tiers
                if "recognition" in f.keys():
                    if f["recognition"]:
                        lines.append(f"recognition: {f['recognition']}")
                    if f["inventory"]:
                        lines.append(f"inventory: {f['inventory']}")
                parts.append("\n".join(lines))

        # Edges
        parts.append("## EDGES")
        if not edges:
            parts.append("(none)")
        else:
            for e in edges:
                rel = f" ({e['relation']})" if e["relation"] else ""
                parts.append(f"- {e['source_key']} → {e['target_key']}{rel}")

        # Active working memory
        parts.append("## ACTIVE WORKING MEMORY")
        if not active_wm:
            parts.append("(none)")
        else:
            for wm in active_wm:
                due = f", due: {wm['due']}" if wm["due"] else ""
                subj = f" [{wm['subject']}]" if wm["subject"] else ""
                parts.append(
                    f"- [wm {wm['id']}] {wm['type']}{subj}{due}: "
                    f"{wm['content']}"
                )

        return "\n\n".join(parts)


def _parse_operations(response_text: str) -> tuple[list[dict], list[str]]:
    """Extract and parse the <operations> JSON array from Claude's response."""
    errors = []

    match = re.search(
        r"<operations>\s*(.*?)\s*</operations>",
        response_text,
        re.DOTALL,
    )

    if not match:
        errors.append("No <operations> tag found in response.")
        return [], errors

    raw = match.group(1).strip()

    # Strip markdown fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    if not raw:
        return [], errors

    try:
        ops = json.loads(raw)
    except json.JSONDecodeError as e:
        errors.append(f"JSON parse error: {e}")
        # Try to detect truncation
        if raw.rstrip()[-1] not in ("]", "}"):
            errors.append(
                "Response appears truncated — JSON array is incomplete."
            )
        return [], errors

    if not isinstance(ops, list):
        errors.append(f"Expected JSON array, got {type(ops).__name__}.")
        return [], errors

    # Validate op types
    valid_types = {
        "CREATE_FRAGMENT", "UPDATE_FRAGMENT",
        "CREATE_EDGE", "DELETE_EDGE",
        "UPDATE_WORKING_MEMORY", "AMBIENT_REWRITE", "FLAG",
    }
    validated = []
    for op in ops:
        if not isinstance(op, dict):
            errors.append(f"Non-object in operations array: {op!r}")
            continue
        if op.get("type") not in valid_types:
            errors.append(f"Unknown operation type: {op.get('type')!r}")
            continue
        validated.append(op)

    return validated, errors


def _apply_operations(
    conn: sqlite3.Connection,
    ops: list[dict],
    ambient_path: Path,
    result: AgentResult,
    valid_event_ids: set[int],
) -> None:
    """Apply parsed operations to the database and filesystem."""
    now = datetime.now(timezone.utc).isoformat()

    for op in ops:
        op_type = op["type"]
        try:
            if op_type == "CREATE_FRAGMENT":
                _apply_create_fragment(conn, op, now, result, valid_event_ids)
            elif op_type == "UPDATE_FRAGMENT":
                _apply_update_fragment(conn, op, now, result, valid_event_ids)
            elif op_type == "CREATE_EDGE":
                _apply_create_edge(conn, op, result)
            elif op_type == "DELETE_EDGE":
                _apply_delete_edge(conn, op, result)
            elif op_type == "UPDATE_WORKING_MEMORY":
                _apply_update_wm(conn, op, now, result)
            elif op_type == "AMBIENT_REWRITE":
                _apply_ambient_rewrite(ambient_path, op, result)
            elif op_type == "FLAG":
                result.notes.append(f"FLAG: {op.get('message', '(no message)')}")
        except sqlite3.IntegrityError as e:
            result.errors.append(f"{op_type} integrity error: {e}")
        except Exception as e:
            result.errors.append(f"{op_type} error: {e}")


def _apply_create_fragment(
    conn: sqlite3.Connection,
    op: dict,
    now: str,
    result: AgentResult,
    valid_event_ids: set[int],
) -> None:
    key = op["key"]

    # Try INSERT; if key exists, fall back to UPDATE
    existing = conn.execute(
        "SELECT key FROM fragments WHERE key = ?", (key,)
    ).fetchone()

    if existing:
        # Fall back to update
        result.notes.append(
            f"CREATE_FRAGMENT '{key}' already exists, updating instead."
        )
        _apply_update_fragment(conn, op, now, result, valid_event_ids)
        return

    conn.execute(
        """INSERT INTO fragments (key, ambient, recognition, inventory,
           created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            key,
            op.get("ambient"),
            op.get("recognition"),
            op.get("inventory"),
            now,
            now,
        ),
    )
    result.fragments_created += 1

    _link_source_events(conn, key, op.get("source_events", []), valid_event_ids, result)


def _apply_update_fragment(
    conn: sqlite3.Connection,
    op: dict,
    now: str,
    result: AgentResult,
    valid_event_ids: set[int],
) -> None:
    key = op["key"]
    sets = ["updated_at = ?"]
    params: list = [now]

    for tier in ("ambient", "recognition", "inventory"):
        if tier in op:
            sets.append(f"{tier} = ?")
            params.append(op[tier])

    params.append(key)
    conn.execute(
        f"UPDATE fragments SET {', '.join(sets)} WHERE key = ?",
        params,
    )
    result.fragments_updated += 1

    _link_source_events(conn, key, op.get("source_events", []), valid_event_ids, result)


def _apply_create_edge(
    conn: sqlite3.Connection, op: dict, result: AgentResult
) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO fragment_edges
           (source_key, target_key, relation)
           VALUES (?, ?, ?)""",
        (op["source_key"], op["target_key"], op.get("relation")),
    )


def _apply_delete_edge(
    conn: sqlite3.Connection, op: dict, result: AgentResult
) -> None:
    conn.execute(
        """DELETE FROM fragment_edges
           WHERE source_key = ? AND target_key = ?""",
        (op["source_key"], op["target_key"]),
    )


def _apply_update_wm(
    conn: sqlite3.Connection, op: dict, now: str, result: AgentResult
) -> None:
    from wake.schema import VALID_WM_STATUSES

    status = op.get("status")
    if status not in VALID_WM_STATUSES:
        result.errors.append(
            f"UPDATE_WORKING_MEMORY invalid status: {status!r}"
        )
        return

    resolved_at = now if status in ("resolved", "dropped", "decayed", "superseded") else None

    conn.execute(
        """UPDATE working_memory
           SET status = ?, resolved_at = COALESCE(?, resolved_at)
           WHERE id = ?""",
        (status, resolved_at, op["id"]),
    )


def _apply_ambient_rewrite(
    ambient_path: Path, op: dict, result: AgentResult
) -> None:
    content = op.get("content", "")
    if not content.strip():
        result.errors.append("AMBIENT_REWRITE with empty content, skipping.")
        return
    ambient_path.write_text(content, encoding="utf-8")
    result.notes.append(
        f"Wrote ambient.md ({len(content)} chars)."
    )


def _link_source_events(
    conn: sqlite3.Connection,
    fragment_key: str,
    source_events: list,
    valid_event_ids: set[int],
    result: AgentResult | None = None,
) -> None:
    """Link fragment to source events, filtering to known valid IDs."""
    for eid in source_events:
        if not isinstance(eid, int):
            if result:
                result.errors.append(f"source_event {eid!r} is not an int, skipping")
            continue
        if eid not in valid_event_ids:
            if result:
                result.errors.append(f"source_event {eid} not in valid window, skipping")
            continue
        conn.execute(
            """INSERT OR IGNORE INTO fragment_sources
               (fragment_key, event_id) VALUES (?, ?)""",
            (fragment_key, eid),
        )


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
