"""
Orchestrator — the conversation loop.

This is the main pipeline:
  1. Mono sends a message
  2. Ingest it
  3. Assemble context
  4. Send to Claude
  5. Parse and ingest Claude's response
  6. Handle any recall requests
  7. Return the response

One function: turn(). Everything else is internal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from wake.assemble import assemble, render_system, render_user, WakeConfig
from wake.recall import recall, RecallResult, NeighborResult
from wake.schema import connect, migrate
from ingest.parse import (
    parse_mono_message,
    parse_response,
    parse_recall_requests,
)
from ingest.lifecycle import ingest
from .claude_client import send, ClaudeConfig, ClaudeResponse


@dataclass
class TurnConfig:
    """Everything needed to run a conversation turn."""
    db_path: Path
    wake_context_path: Path
    wake_context_image_path: Path
    ambient_path: Path
    claude_config: ClaudeConfig = field(default_factory=ClaudeConfig)


@dataclass
class TurnResult:
    """What happened in a single conversation turn."""
    response_text: str              # Claude's full response
    display_text: str               # just the say/do/narrate content
    display_spans: list[dict]       # [{"tag": "say", "content": "..."}]
    actor: str | None               # Claude's identity tag
    turn: int                       # current turn number
    recall_results: list[RecallResult] = field(default_factory=list)
    success: bool = True
    error: str | None = None


def _load_recall_results(db_path: Path) -> list[RecallResult]:
    """Load pending recall results from the state table."""
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT value FROM state WHERE key = 'pending_recall'"
        ).fetchone()
        if not row:
            return []
        data = json.loads(row["value"])
        results = []
        for item in data:
            neighbors = [
                NeighborResult(key=n["key"], ambient=n["ambient"], relation=n["relation"])
                for n in item.get("neighbors", [])
            ]
            results.append(RecallResult(
                key=item["key"], content=item["content"],
                depth=item["depth"], neighbors=neighbors,
            ))
        return results
    finally:
        conn.close()


def _save_recall_results(db_path: Path, results: list[RecallResult]) -> None:
    """Persist recall results in state table for next turn, or clear if empty."""
    conn = connect(db_path)
    try:
        if not results:
            conn.execute("DELETE FROM state WHERE key = 'pending_recall'")
        else:
            data = [
                {
                    "key": r.key, "content": r.content, "depth": r.depth,
                    "neighbors": [
                        {"key": n.key, "ambient": n.ambient, "relation": n.relation}
                        for n in r.neighbors
                    ],
                }
                for r in results
            ]
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO state (key, value, updated_at) VALUES ('pending_recall', ?, ?)",
                (json.dumps(data), now),
            )
        conn.commit()
    finally:
        conn.close()


def turn(
    config: TurnConfig,
    message: str,
    actor: str | None = None,
    tags: list[str] | None = None,
    image_path: str | None = None,
) -> TurnResult:
    """
    Run a single conversation turn.

    Mono sends a message → Claude responds → everything gets stored.
    This is the main entry point for the conversation loop.
    """
    # Ensure schema is current
    migrate(config.db_path)

    # 1. Parse and ingest Mono's message
    mono_parsed = parse_mono_message(message, actor=actor, tags=tags)
    mono_result = ingest(
        config.db_path, mono_parsed,
        image_path=image_path,
    )

    # 2. Assemble context
    wake_config = WakeConfig(
        db_path=config.db_path,
        wake_context_path=config.wake_context_path,
        wake_context_image_path=config.wake_context_image_path,
        ambient_path=config.ambient_path,
    )

    # Format hot context with identity — same convention as Recent section
    hot = f"{actor or 'mono'}: {message}"

    previous_recall = _load_recall_results(config.db_path)
    package = assemble(
        wake_config,
        hot_context=hot,
        current_turn=mono_result.turn,
        recall_results=previous_recall,
        image_path=image_path,
    )

    system_prompt = render_system(package)
    user_message = render_user(package)

    # 3. Send to Claude
    img = Path(image_path) if image_path else None
    claude_response = send(
        user_message, config.claude_config, img,
        system_prompt=system_prompt,
    )

    if not claude_response.success:
        return TurnResult(
            response_text="",
            display_text="",
            display_spans=[],
            actor=None,
            turn=mono_result.turn,
            success=False,
            error=claude_response.error,
        )

    # 4. Parse Claude's response
    response_parsed = parse_response(claude_response.text)

    # 5. Ingest Claude's response
    ingest(
        config.db_path, response_parsed,
        is_claude=True,
    )

    # 6. Handle recall requests
    recall_requests = parse_recall_requests(claude_response.text)
    recall_results = []
    for key, deep in recall_requests:
        result = recall(key, config.db_path, deep=deep)
        if result:
            recall_results.append(result)

    # Save recall results for next turn's context
    _save_recall_results(config.db_path, recall_results)

    # 7. Extract display content for the frontend
    display_spans = []
    display_parts = []
    for span in response_parsed.spans:
        if span.tag in ("say", "do", "narrate"):
            display_parts.append(span.content)
            display_spans.append({"tag": span.tag, "content": span.content})
    display_text = "\n".join(display_parts)

    return TurnResult(
        response_text=claude_response.text,
        display_text=display_text,
        display_spans=display_spans,
        actor=response_parsed.actor,
        turn=mono_result.turn,
        recall_results=recall_results,
        success=True,
    )
