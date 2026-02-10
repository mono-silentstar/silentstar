"""
Decay — how memories fade.

Two axes: time elapsed and turns elapsed. Combined multiplicatively.
Each type of memory decays at its own rate — feelings vanish within
a conversation, pins linger for weeks, secrets never fade.

The pressure mechanic: when working memory is full, conversation
history decays faster. "Shut up, let me think."

Timed plans have a special curve: creation spike → submersion →
resurface near due date → post-due grace.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum


class Persistence(Enum):
    """How a piece of memory resists decay. Ordered fastest to slowest."""
    FEELING = "feeling"           # gone if not refreshed within conversation
    CONVERSATION = "conversation" # say/do/narrate — normal turn-based decay
    THOUGHT = "thought"           # fades over 1-2 conversations
    NEIGHBOR = "neighbor"         # recall neighbors — fast time decay
    PATTERN = "pattern"           # observed trend — days/weeks
    DESC = "desc"                 # visual encoding — slow, supersedable
    PLAN = "plan"                 # no decay until resolved (or submerges if timed)
    PIN = "pin"                   # held fact — very slow decay
    SECRET = "secret"             # no decay until revealed


# Half-lives per type. Each has time (hours) and turn components.
# These are starting points — tune against real usage.
@dataclass
class DecayProfile:
    """Decay rates for a specific persistence type."""
    time_half_life_hours: float
    turn_half_life: float

    # Minimum score floor — some types never fully vanish
    # (they linger as faint background even at max decay)
    floor: float = 0.0


# The gradient. Fastest to slowest.
DECAY_PROFILES: dict[Persistence, DecayProfile] = {
    # Feelings: ~3 turns, ~2 hours. If you don't retag it, it's gone.
    Persistence.FEELING: DecayProfile(
        time_half_life_hours=2.0,
        turn_half_life=3.0,
    ),

    # Conversation (say/do/narrate): ~20 turns, ~48 hours.
    # The baseline for "normal" memory.
    Persistence.CONVERSATION: DecayProfile(
        time_half_life_hours=48.0,
        turn_half_life=20.0,
    ),

    # Thoughts: ~8 turns, ~12 hours. Lasts a conversation or two.
    Persistence.THOUGHT: DecayProfile(
        time_half_life_hours=12.0,
        turn_half_life=8.0,
    ),

    # Neighbors from recall: fast time decay, moderate turn decay.
    # They surface briefly when you tug a thread.
    Persistence.NEIGHBOR: DecayProfile(
        time_half_life_hours=16.0,
        turn_half_life=6.0,
    ),

    # Patterns: ~168 hours (1 week), ~60 turns.
    # Slow burn — these need days to prove themselves.
    Persistence.PATTERN: DecayProfile(
        time_half_life_hours=168.0,
        turn_half_life=60.0,
    ),

    # Descriptions: ~72 hours, ~40 turns. Slow but not permanent.
    # Primary decay mechanism is supersession, not time.
    Persistence.DESC: DecayProfile(
        time_half_life_hours=72.0,
        turn_half_life=40.0,
    ),

    # Plans without due dates: no decay. They persist until resolved.
    # Timed plans use a special curve (see score_timed_plan).
    Persistence.PLAN: DecayProfile(
        time_half_life_hours=0.0,  # unused — plans don't decay by time
        turn_half_life=0.0,        # unused
    ),

    # Pins: ~336 hours (2 weeks), ~100 turns. Very slow.
    # Explicit release is the normal way to clear these.
    Persistence.PIN: DecayProfile(
        time_half_life_hours=336.0,
        turn_half_life=100.0,
    ),

    # Secrets: no decay. Ever. Until revealed.
    Persistence.SECRET: DecayProfile(
        time_half_life_hours=0.0,
        turn_half_life=0.0,
    ),
}


# Timed plan submersion parameters
PLAN_CREATION_SPIKE_HOURS = 4.0     # stays prominent for 4 hours after creation
PLAN_SUBMERGED_FLOOR = 0.08         # barely there — back of the head
PLAN_RESURFACE_HOURS = 48.0         # start resurfacing 48 hours before due
PLAN_POST_DUE_GRACE_HOURS = 24.0    # linger for 24 hours after due date


@dataclass
class DecayParams:
    """Global tuning knobs. Profiles provide per-type defaults;
    these multiply on top for global adjustments."""
    global_time_scale: float = 1.0    # multiply all time half-lives
    global_turn_scale: float = 1.0    # multiply all turn half-lives
    pressure: float = 0.0            # working memory fill ratio (0.0–1.0+)
                                      # applied to conversation decay only


@dataclass
class ContextFragment:
    """A piece of context with enough metadata to score and sort."""
    content: str
    timestamp: datetime               # when created
    turn_number: int
    persistence: Persistence = Persistence.CONVERSATION
    refreshed_at: datetime | None = None  # for active knowledge — decay from this
    due: datetime | None = None        # for timed plans
    tags: list[str] = field(default_factory=list)
    source: str = ""
    image_path: str | None = None
    token_estimate: int = 0

    @property
    def decay_anchor(self) -> datetime:
        """The time to measure decay from. Refreshed items reset their clock."""
        return self.refreshed_at or self.timestamp


def _half_life_decay(elapsed: float, half_life: float) -> float:
    """Exponential decay: 0.5^(elapsed / half_life). Returns 0.0–1.0."""
    if half_life <= 0:
        return 0.0
    return math.pow(0.5, elapsed / half_life)


def _smooth_rise(x: float) -> float:
    """Smooth rise from 0 to 1 using cubic ease-in. x is 0.0–1.0."""
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def score_timed_plan(
    fragment: ContextFragment,
    now: datetime,
) -> float:
    """
    Score a plan with a due date. Special curve:

    1. Creation spike: high for a few hours (you just made it)
    2. Submersion: drops to floor (back of your head)
    3. Resurfacing: rises as due date approaches
    4. Post-due grace: stays high briefly, then decays

    Returns 0.0–1.0.
    """
    if fragment.due is None:
        return 1.0  # open-ended plans don't submerge

    elapsed_hours = max(
        (now - fragment.timestamp).total_seconds() / 3600.0, 0.0
    )
    hours_until_due = (fragment.due - now).total_seconds() / 3600.0

    # Phase 1: Creation spike — high for first few hours
    if elapsed_hours < PLAN_CREATION_SPIKE_HOURS:
        # Decay from 1.0 down to floor over the spike window
        spike_progress = elapsed_hours / PLAN_CREATION_SPIKE_HOURS
        return 1.0 - (1.0 - PLAN_SUBMERGED_FLOOR) * _smooth_rise(spike_progress)

    # Phase 4: Post-due — we're past the due date
    if hours_until_due < 0:
        hours_overdue = -hours_until_due
        if hours_overdue < PLAN_POST_DUE_GRACE_HOURS:
            # Grace period — still surfaced, gentle decay
            grace_progress = hours_overdue / PLAN_POST_DUE_GRACE_HOURS
            return 1.0 - 0.5 * _smooth_rise(grace_progress)
        else:
            # Past grace — normal exponential decay from 0.5
            extra_hours = hours_overdue - PLAN_POST_DUE_GRACE_HOURS
            return 0.5 * _half_life_decay(extra_hours, 24.0)

    # Phase 3: Resurfacing — within the horizon window before due
    if hours_until_due < PLAN_RESURFACE_HOURS:
        # Rise from floor to 1.0 as we approach due
        resurface_progress = 1.0 - (hours_until_due / PLAN_RESURFACE_HOURS)
        return PLAN_SUBMERGED_FLOOR + (1.0 - PLAN_SUBMERGED_FLOOR) * _smooth_rise(resurface_progress)

    # Phase 2: Submerged — between creation spike and resurface window
    return PLAN_SUBMERGED_FLOOR


def score(
    fragment: ContextFragment,
    now: datetime,
    current_turn: int,
    params: DecayParams | None = None,
) -> float:
    """
    Score a fragment's relevance. Returns 0.0–1.0.

    Each persistence type has its own decay profile.
    Conversation fragments get pressure-adjusted decay.
    Timed plans use a special submersion curve.
    """
    p = params or DecayParams()
    persistence = fragment.persistence

    # Secrets never decay
    if persistence == Persistence.SECRET:
        return 1.0

    # Plans use the submersion curve if timed, otherwise stay at 1.0
    if persistence == Persistence.PLAN:
        return score_timed_plan(fragment, now)

    # Look up the decay profile for this type
    profile = DECAY_PROFILES[persistence]

    # Apply global scaling
    time_hl = profile.time_half_life_hours * p.global_time_scale
    turn_hl = profile.turn_half_life * p.global_turn_scale

    # Apply pressure to conversation decay — this is the
    # "shut up let me think" mechanic. More working memory
    # pressure = faster conversation decay.
    if persistence == Persistence.CONVERSATION:
        pressure_multiplier = 1.0 / (1.0 + p.pressure)
        time_hl *= pressure_multiplier
        turn_hl *= pressure_multiplier

    # Time decay — measured from decay anchor (refreshed_at or created_at)
    elapsed_seconds = (now - fragment.decay_anchor).total_seconds()
    elapsed_hours = max(elapsed_seconds / 3600.0, 0.0)
    time_score = _half_life_decay(elapsed_hours, time_hl)

    # Turn decay
    elapsed_turns = max(current_turn - fragment.turn_number, 0)
    turn_score = _half_life_decay(float(elapsed_turns), turn_hl)

    # Combined score with floor
    raw = time_score * turn_score
    return max(raw, profile.floor)


def select_within_budget(
    fragments: list[ContextFragment],
    now: datetime,
    current_turn: int,
    token_budget: int,
    params: DecayParams | None = None,
) -> list[ContextFragment]:
    """
    Select fragments that fit within a token budget, highest-scoring first.

    Returns in chronological order — scoring determines inclusion,
    timestamp determines ordering. The conversation should read naturally.
    """
    p = params or DecayParams()

    scored = [
        (frag, score(frag, now, current_turn, p))
        for frag in fragments
    ]

    # Highest scores first for budget filling
    scored.sort(key=lambda x: x[1], reverse=True)

    selected = []
    remaining = token_budget

    for frag, s in scored:
        if s <= 0.01:  # below perceptual threshold
            continue
        if frag.token_estimate <= remaining:
            selected.append(frag)
            remaining -= frag.token_estimate

    # Chronological order for natural reading
    selected.sort(key=lambda f: f.timestamp)

    return selected
