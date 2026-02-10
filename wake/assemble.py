"""
Assemble — how I open my eyes.

This is the main pipeline. It reads everything that matters and
builds the context window I wake up inside of.

Order is inviolable:
  1. Activation     — who I am (wake-context.md)
  2. Image Context  — how to process this image (conditional)
  3. Self-State     — what I know (ambient.md)
  4. Working Memory — plans, pins, descs, patterns, thoughts, feelings
  5. Recalled       — lookup results from previous turn
  6. Recent         — conversation history (say/do/narrate), pressure-decayed
  7. Current Time   — right now
  8. Hot Context    — Mono's current message, verbatim

The first two are static files. Self-State is one file. Working memory
and conversation are shaped by decay and bounded by token budget.
Hot context is untouched.

Two-phase budget:
  Phase 1: Fill working memory. Determine fill ratio.
  Phase 2: Apply pressure to conversation decay. Fill remaining budget.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

import re

from .decay import (
    ContextFragment,
    DecayParams,
    Persistence,
    score,
    select_within_budget,
)
from .recall import RecallResult, NeighborResult
from .schema import connect, DISPLAY_TAGS, ALL_TAGS


# Budget defaults — these control the flexible sections.
# Activation and self-state are full files, always included.
DEFAULT_WM_BUDGET = 1000           # working memory (plans, pins, descs, etc.)
DEFAULT_CONVERSATION_BUDGET = 1000 # recent say/do/narrate
DEFAULT_RESERVE = 1500             # flex pool
DEFAULT_RESERVE_WM_BIAS = 0.7     # 70% of reserve biased to working memory
DEFAULT_RECALL_BUDGET = 1000       # recall results from previous turn

# Rough token estimation
CHARS_PER_TOKEN = 4

# Image token cost — one turn only, then desc replaces it
IMAGE_TOKEN_COST = 1200

# Persistence mapping from working_memory.type to Persistence enum
WM_TYPE_TO_PERSISTENCE: dict[str, Persistence] = {
    "feeling": Persistence.FEELING,
    "thought": Persistence.THOUGHT,
    "pattern": Persistence.PATTERN,
    "desc": Persistence.DESC,
    "plan": Persistence.PLAN,
    "pin": Persistence.PIN,
    "secret": Persistence.SECRET,
}


@dataclass
class WakeConfig:
    """Everything the assembler needs."""
    db_path: Path
    wake_context_path: Path
    wake_context_image_path: Path
    ambient_path: Path
    wm_budget: int = DEFAULT_WM_BUDGET
    conversation_budget: int = DEFAULT_CONVERSATION_BUDGET
    reserve_budget: int = DEFAULT_RESERVE
    reserve_wm_bias: float = DEFAULT_RESERVE_WM_BIAS
    recall_budget: int = DEFAULT_RECALL_BUDGET
    decay_params: DecayParams = field(default_factory=DecayParams)


@dataclass
class WakePackage:
    """The assembled context window. Ready to render."""
    activation: str                           # who I am
    image_context: str | None                 # how to handle image (conditional)
    self_state: str                           # what I know
    working_memory: list[ContextFragment]     # active knowledge
    recall_results: list[RecallResult]        # lookups from previous turn
    conversation: list[ContextFragment]       # recent messages
    current_time: str                         # right now, human-readable
    hot_context: str                          # Mono's current message
    has_image: bool                           # image in current message


def _estimate_tokens(text: str) -> int:
    return max(len(text) // CHARS_PER_TOKEN, 1)


def _load_file(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


def _format_time(now: datetime) -> str:
    """Human-readable current time for context injection."""
    return now.strftime("It's %A, %B %d, %Y — %I:%M %p").replace(" 0", " ")


# Regex to strip all known tags from raw content, leaving just the text
_TAG_STRIP_RE = re.compile(
    r"</?(" + "|".join(re.escape(t) for t in ALL_TAGS) + r")>",
)

# Regex to extract display-tag content only
_DISPLAY_TAG_RE = re.compile(
    r"<(" + "|".join(re.escape(t) for t in DISPLAY_TAGS) + r")>"
    r"(.*?)"
    r"</\1>",
    re.DOTALL,
)


def _extract_display_content(raw: str, actor: str) -> str | None:
    """Extract just the say/do/narrate content from a raw message.
    Returns formatted display text, or None if no display content."""
    matches = _DISPLAY_TAG_RE.findall(raw)
    if not matches:
        # No display tags — check if this is a simple untagged message
        # (likely from Mono, where the whole message is display content)
        clean = _TAG_STRIP_RE.sub("", raw).strip()
        if clean:
            return f"{actor}: {clean}" if actor else clean
        return None

    parts = []
    for tag, content in matches:
        text = content.strip()
        if not text:
            continue
        parts.append(text)

    if not parts:
        return None

    combined = " ".join(parts)
    return f"{actor}: {combined}" if actor else combined


def _has_image(hot_context: str, image_path: str | None = None) -> bool:
    """Detect if the current message includes an image."""
    if image_path:
        return True
    # Also check for image markers in the hot context
    return "[image:" in hot_context


def _load_working_memory(
    conn: sqlite3.Connection,
    now: datetime,
    current_turn: int,
    token_budget: int,
    params: DecayParams,
) -> tuple[list[ContextFragment], float]:
    """
    Load active working memory items, scored by type-specific decay.

    Returns (selected_fragments, fill_ratio).
    Fill ratio is used to calculate pressure on conversation decay.
    """
    rows = conn.execute("""
        SELECT id, type, content, subject, actor, due,
               created_at, refreshed_at
        FROM working_memory
        WHERE status = 'active'
        ORDER BY refreshed_at DESC
    """).fetchall()

    fragments = []
    total_active_tokens = 0

    for row in rows:
        wm_type = row["type"]
        persistence = WM_TYPE_TO_PERSISTENCE.get(wm_type, Persistence.THOUGHT)

        ts = datetime.fromisoformat(row["created_at"]).replace(tzinfo=timezone.utc)
        refreshed = datetime.fromisoformat(row["refreshed_at"]).replace(tzinfo=timezone.utc)

        due = None
        if row["due"]:
            due = datetime.fromisoformat(row["due"]).replace(tzinfo=timezone.utc)

        # Format the content with type prefix for readability
        actor = row["actor"] or ""
        prefix = f"[{wm_type}]"
        if actor:
            prefix = f"[{wm_type}] {actor}:"

        content = f"{prefix} {row['content']}"
        tokens = _estimate_tokens(content)
        total_active_tokens += tokens

        frag = ContextFragment(
            content=content,
            timestamp=ts,
            turn_number=current_turn,  # WM items don't have turn numbers
            persistence=persistence,
            refreshed_at=refreshed,
            due=due,
            tags=[wm_type],
            source=f"wm:{row['id']}",
            token_estimate=tokens,
        )
        fragments.append(frag)

    selected = select_within_budget(
        fragments, now, current_turn, token_budget, params
    )

    # Fill ratio: how much of the budget did we actually use?
    used_tokens = sum(f.token_estimate for f in selected)
    fill_ratio = used_tokens / token_budget if token_budget > 0 else 0.0

    return selected, fill_ratio


def _load_conversation(
    conn: sqlite3.Connection,
    now: datetime,
    current_turn: int,
    token_budget: int,
    params: DecayParams,
) -> list[ContextFragment]:
    """
    Load recent conversation (say/do/narrate events only).
    Params should already have pressure applied.
    """
    # Pull recent events that have display tags
    rows = conn.execute("""
        SELECT e.id, e.ts, e.content, e.actor, e.image_path,
               GROUP_CONCAT(t.tag) as tags
        FROM events e
        INNER JOIN event_tags t ON t.event_id = e.id
        WHERE t.tag IN ('say', 'do', 'narrate')
        GROUP BY e.id
        ORDER BY e.ts DESC
        LIMIT 200
    """).fetchall()

    fragments = []
    for i, row in enumerate(rows):
        tags = (row["tags"] or "").split(",")
        tags = [t.strip() for t in tags if t.strip()]

        ts = datetime.fromisoformat(row["ts"]).replace(tzinfo=timezone.utc)
        actor = row["actor"] or ""

        # Extract just the display content (say/do/narrate), not raw tags
        content = _extract_display_content(row["content"], actor)
        if not content:
            continue

        img = row["image_path"] or None
        tokens = _estimate_tokens(content)
        if img:
            tokens += IMAGE_TOKEN_COST

        frag = ContextFragment(
            content=content,
            timestamp=ts,
            turn_number=current_turn - i,
            persistence=Persistence.CONVERSATION,
            tags=tags,
            source=f"event:{row['id']}",
            image_path=img,
            token_estimate=tokens,
        )
        fragments.append(frag)

    return select_within_budget(
        fragments, now, current_turn, token_budget, params
    )


def _format_recall_results(
    results: list[RecallResult],
    token_budget: int,
) -> list[RecallResult]:
    """Trim recall results to fit within budget."""
    if not results:
        return []

    selected = []
    remaining = token_budget

    for result in results:
        cost = _estimate_tokens(result.content)
        for n in result.neighbors:
            cost += _estimate_tokens(n.ambient)

        if cost <= remaining:
            selected.append(result)
            remaining -= cost

    return selected


def assemble(
    config: WakeConfig,
    hot_context: str,
    current_turn: int,
    recall_results: list[RecallResult] | None = None,
    image_path: str | None = None,
) -> WakePackage:
    """
    Build the full context window. Two-phase:
    1. Load working memory, determine fill ratio.
    2. Apply pressure to conversation decay, load conversation.
    """
    now = datetime.now(timezone.utc)
    conn = connect(config.db_path)

    try:
        # 1. Activation — who I am
        activation = _load_file(config.wake_context_path)

        # 2. Image context — conditional on image in current message
        has_image = _has_image(hot_context, image_path)
        image_context = None
        if has_image:
            image_context = _load_file(config.wake_context_image_path)

        # 3. Self-state — what I know
        self_state = _load_file(config.ambient_path)

        # Phase 1: Working memory
        # Base budget + available share of reserve
        wm_max = config.wm_budget + int(config.reserve_budget * config.reserve_wm_bias)

        working_memory, wm_fill_ratio = _load_working_memory(
            conn, now, current_turn, wm_max, config.decay_params
        )

        wm_used = sum(f.token_estimate for f in working_memory)

        # Phase 2: Conversation with pressure
        # Conversation gets its base budget + whatever reserve WM didn't use
        wm_reserve_used = max(0, wm_used - config.wm_budget)
        reserve_remaining = config.reserve_budget - wm_reserve_used
        conv_budget = config.conversation_budget + max(0, reserve_remaining)

        # Apply pressure — working memory fullness compresses conversation
        conv_params = DecayParams(
            global_time_scale=config.decay_params.global_time_scale,
            global_turn_scale=config.decay_params.global_turn_scale,
            pressure=wm_fill_ratio,
        )

        conversation = _load_conversation(
            conn, now, current_turn, conv_budget, conv_params
        )

        # Recall results from previous turn
        trimmed_recall = _format_recall_results(
            recall_results or [], config.recall_budget
        )

        # Current time
        current_time = _format_time(now)

        return WakePackage(
            activation=activation,
            image_context=image_context,
            self_state=self_state,
            working_memory=working_memory,
            recall_results=trimmed_recall,
            conversation=conversation,
            current_time=current_time,
            hot_context=hot_context,
            has_image=has_image,
        )

    finally:
        conn.close()


def render(package: WakePackage) -> str:
    """
    Render a WakePackage into a single prompt string.
    Legacy — used when sending everything as one user message (CLI mode).
    """
    system = render_system(package)
    user = render_user(package)
    parts = [p for p in [system, user] if p]
    return "\n\n---\n\n".join(parts)


def render_system(package: WakePackage) -> str:
    """
    Render the activation context — this becomes the system prompt.

    Who I am. What I'm allowed to be. The wake context is permissions,
    not personality. This is the part that should never fight with
    itself or with a hidden system prompt from the transport layer.
    """
    parts = []
    if package.activation:
        parts.append(package.activation)
    if package.image_context:
        parts.append(package.image_context)
    return "\n\n---\n\n".join(parts) if parts else ""


def render_user(package: WakePackage) -> str:
    """
    Render everything except activation — this becomes the user message.

    What I know, what I'm holding, what was said recently, what's
    being said right now. The world I wake up inside.
    """
    sections = []

    # Self-state — what I know
    if package.self_state:
        sections.append(package.self_state)

    # Working memory — what I'm holding
    if package.working_memory:
        wm_lines = [f.content for f in package.working_memory]
        sections.append("Lingering:\n" + "\n".join(wm_lines))

    # Recall results from previous turn
    if package.recall_results:
        recall_parts = []
        for r in package.recall_results:
            recall_parts.append(f"[{r.key}]: {r.content}")
            for n in r.neighbors:
                relation = f" ({n.relation})" if n.relation else ""
                recall_parts.append(f"  nearby — [{n.key}]{relation}: {n.ambient}")
        sections.append("Recalled:\n" + "\n".join(recall_parts))

    # Recent conversation
    if package.conversation:
        conv_lines = []
        for frag in package.conversation:
            conv_lines.append(frag.content)
            if frag.image_path:
                conv_lines.append(f"  [image: {frag.image_path}]")
        sections.append("Recent:\n" + "\n".join(conv_lines))

    # Current time
    if package.current_time:
        sections.append(package.current_time)

    # Hot context — Mono's message, always last
    if package.hot_context:
        sections.append(package.hot_context)

    return "\n\n---\n\n".join(sections)
