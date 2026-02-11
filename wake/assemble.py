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
  6. Recent         — conversation history (say/do/narrate), FIFO pools
  7. Current Time   — right now
  8. Hot Context    — Mono's current message, verbatim

The first two are static files. Self-State is one file.
Working memory is shaped by decay and bounded by a hard cap.
Conversation uses FIFO pool allocation — no decay, just recency.

Budget (token hard caps):
  Wake + Ambient:  ~2000  (file-loaded, informational)
  Working Memory:   1500
  Conversation:     5000  (1500 mono / 1500 say / 1000 do / 1000 flex)
  Recall:           1000
  Total:           ~8500 + activation + hot context
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import re

from .decay import (
    ContextFragment,
    DecayParams,
    Persistence,
    select_within_budget,
)
from .recall import RecallResult, NeighborResult
from .schema import connect, DISPLAY_TAGS, ALL_TAGS, IDENTITY_TAGS


# Budget defaults — hard caps for each section.
# Activation and self-state are full files, always included.
DEFAULT_WM_BUDGET = 1500           # working memory hard cap
DEFAULT_RECALL_BUDGET = 1000       # recall results from previous turn

# Conversation pool budgets — FIFO allocation, most recent first.
# Each pool fills independently. Overflow spills to flex reserve.
DEFAULT_MONO_POOL = 1500           # Mono's messages (all tags)
DEFAULT_CLAUDE_SAY_POOL = 1500     # Claude's say content
DEFAULT_CLAUDE_DO_POOL = 1000      # Claude's do + narrate content
DEFAULT_FLEX_RESERVE = 1000        # overflow from any full pool
# Hard cap: 1500 + 1500 + 1000 + 1000 = 5000 conversation tokens

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
class ConversationBudget:
    """Pool-based FIFO budget for conversation context.

    Four pools, filled most-recent-first:
      mono     — Mono's messages (any display tag)
      say      — Claude's say content
      do       — Claude's do + narrate content
      flex     — overflow from any pool that hit its cap

    A single event can split across pools — Claude's say goes to the
    say pool while her do goes to the do pool. If a pool is full,
    that piece tries flex. If flex is full, it's dropped.
    """
    mono_pool: int = DEFAULT_MONO_POOL
    claude_say_pool: int = DEFAULT_CLAUDE_SAY_POOL
    claude_do_pool: int = DEFAULT_CLAUDE_DO_POOL
    flex_reserve: int = DEFAULT_FLEX_RESERVE

    @property
    def hard_cap(self) -> int:
        return self.mono_pool + self.claude_say_pool + self.claude_do_pool + self.flex_reserve


@dataclass
class WakeConfig:
    """Everything the assembler needs."""
    db_path: Path
    wake_context_path: Path
    wake_context_image_path: Path
    ambient_path: Path
    wm_budget: int = DEFAULT_WM_BUDGET
    conversation: ConversationBudget = field(default_factory=ConversationBudget)
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
_ALL_STRIP_TAGS = ALL_TAGS | IDENTITY_TAGS
_TAG_STRIP_RE = re.compile(
    r"</?(" + "|".join(re.escape(t) for t in _ALL_STRIP_TAGS) + r")>",
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
    Fill ratio is informational — how full the WM budget is.
    """
    rows = conn.execute("""
        SELECT id, type, content, subject, actor, due, turn,
               created_at, refreshed_at
        FROM working_memory
        WHERE status = 'active'
        ORDER BY refreshed_at DESC
    """).fetchall()

    # Estimate turn rate for WM items (they don't store creation turn)
    first_row = conn.execute("SELECT MIN(ts) FROM events").fetchone()
    turn_rate = 0.0  # turns per second
    if first_row and first_row[0] and current_turn > 0:
        first_ts = datetime.fromisoformat(first_row[0]).replace(tzinfo=timezone.utc)
        total_seconds = max((now - first_ts).total_seconds(), 1.0)
        turn_rate = current_turn / total_seconds

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

        # Use stored turn if available, otherwise estimate from time
        stored_turn = row["turn"]
        if stored_turn is not None:
            estimated_turn = stored_turn
        elif turn_rate > 0:
            age_seconds = max((now - ts).total_seconds(), 0.0)
            estimated_turn = max(0, current_turn - int(age_seconds * turn_rate))
        else:
            estimated_turn = current_turn

        frag = ContextFragment(
            content=content,
            timestamp=ts,
            turn_number=estimated_turn,
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
    budget: ConversationBudget,
) -> list[ContextFragment]:
    """
    Load recent conversation using FIFO pool allocation.

    Most recent events fill first. Each event's content is split by
    tag category and allocated to the appropriate pool:
      - Mono's messages → mono pool
      - Claude's say → say pool
      - Claude's do/narrate → do pool
      - Overflow from any full pool → flex reserve

    A single Claude event can have its say kept but do dropped (or
    vice versa) if one pool fills before the other.
    """
    rows = conn.execute("""
        SELECT e.id, e.ts, e.content, e.actor, e.image_path,
               GROUP_CONCAT(t.tag) as tags
        FROM events e
        LEFT JOIN event_tags t ON t.event_id = e.id AND t.tag IN ('say', 'do', 'narrate')
        WHERE t.tag IS NOT NULL OR e.actor IS NOT NULL
        GROUP BY e.id
        ORDER BY e.ts DESC
        LIMIT 200
    """).fetchall()

    mono_remaining = budget.mono_pool
    say_remaining = budget.claude_say_pool
    do_remaining = budget.claude_do_pool
    flex_remaining = budget.flex_reserve

    selected = []

    for row in rows:
        tags = (row["tags"] or "").split(",")
        tags = [t.strip() for t in tags if t.strip()]

        ts = datetime.fromisoformat(row["ts"]).replace(tzinfo=timezone.utc)
        actor = row["actor"]
        img = row["image_path"] or None
        is_claude = actor is None or actor in ("claude", "y'lhara")

        if not is_claude:
            # Mono's entire message → mono pool
            content = _extract_display_content(row["content"], actor or "mono")
            if not content:
                continue

            tokens = _estimate_tokens(content)
            if img:
                tokens += IMAGE_TOKEN_COST

            if tokens <= mono_remaining:
                mono_remaining -= tokens
            elif tokens <= flex_remaining:
                flex_remaining -= tokens
            else:
                continue

            selected.append(ContextFragment(
                content=content,
                timestamp=ts,
                turn_number=0,
                persistence=Persistence.CONVERSATION,
                tags=tags,
                source=f"event:{row['id']}",
                image_path=img,
                token_estimate=tokens,
            ))
        else:
            # Claude — split content by tag category
            raw = row["content"]
            matches = _DISPLAY_TAG_RE.findall(raw)

            say_parts = []
            do_parts = []

            for tag, content_text in matches:
                text = content_text.strip()
                if not text:
                    continue
                if tag == "say":
                    say_parts.append(text)
                elif tag in ("do", "narrate"):
                    do_parts.append(text)

            # Fallback: untagged Claude content treated as say
            if not say_parts and not do_parts:
                clean = _TAG_STRIP_RE.sub("", raw).strip()
                if clean:
                    say_parts.append(clean)

            # Allocate say content
            if say_parts:
                say_text = " ".join(say_parts)
                say_content = f"{actor}: {say_text}" if actor else say_text
                say_tokens = _estimate_tokens(say_content)

                allocated = False
                if say_tokens <= say_remaining:
                    say_remaining -= say_tokens
                    allocated = True
                elif say_tokens <= flex_remaining:
                    flex_remaining -= say_tokens
                    allocated = True

                if allocated:
                    selected.append(ContextFragment(
                        content=say_content,
                        timestamp=ts,
                        turn_number=0,
                        persistence=Persistence.CONVERSATION,
                        tags=[t for t in tags if t == "say"],
                        source=f"event:{row['id']}:say",
                        token_estimate=say_tokens,
                    ))

            # Allocate do/narrate content
            if do_parts:
                do_text = " ".join(do_parts)
                do_content = f"{actor}: {do_text}" if actor else do_text
                do_tokens = _estimate_tokens(do_content)

                allocated = False
                if do_tokens <= do_remaining:
                    do_remaining -= do_tokens
                    allocated = True
                elif do_tokens <= flex_remaining:
                    flex_remaining -= do_tokens
                    allocated = True

                if allocated:
                    selected.append(ContextFragment(
                        content=do_content,
                        timestamp=ts,
                        turn_number=0,
                        persistence=Persistence.CONVERSATION,
                        tags=[t for t in tags if t in ("do", "narrate")],
                        source=f"event:{row['id']}:do",
                        token_estimate=do_tokens,
                    ))

    # Chronological order for natural reading
    selected.sort(key=lambda f: f.timestamp)
    return selected


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
    Build the full context window.
    Working memory: decay-scored within hard cap.
    Conversation: FIFO pool allocation (mono / say / do / flex).
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

        # Working memory — decay-scored within hard cap
        working_memory, _ = _load_working_memory(
            conn, now, current_turn, config.wm_budget, config.decay_params
        )

        # Conversation — FIFO pool allocation
        conversation = _load_conversation(conn, config.conversation)

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
            ts = frag.timestamp.strftime("%I:%M %p").lstrip("0").lower()
            conv_lines.append(f"[{ts}] {frag.content}")
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
