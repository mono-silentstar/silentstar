# The Compass — Planning Agent

The fifth artifact. A compass needle points north on its own — you don't tell it where to aim. But you still have to look at it. The Compass takes ownership of the planning domain: it researches independently, reasons about trajectories, and proposes plans Mono didn't ask for. Advisory, not executive.

## Identity

The Compass responds to forces you can't perceive directly. It sees patterns across time — what's been started, what's stalled, what's approaching, what's missing. It researches the outside world (training methods, strategies, schedules, techniques) and brings that knowledge back as proposals grounded in what it knows about Mono.

It surprises. That's the point. Not random — calibrated. It knows the Gem, it knows the patterns, and it looks outward where Mono hasn't.

## Execution Model

**A Claude Code custom agent**, not a cron job or API pipeline. Lives at `.claude/agents/compass.md`. Planning requires intensive multi-turn reasoning, real research, and often Mono's input — a full Claude Code session, not a single API call.

**Manual trigger only (for now).** Mono or Anvil initiates a Compass session. As the Gem fills with more datapoints (body knowledge, preferences, routines, outcomes), the Compass needs less prompting and could eventually run more autonomously. But right now it needs to ask.

### Trigger paths

1. **Direct**: Mono runs the Compass agent in Claude Code for a planning session
2. **Via Anvil**: During an Anvil session, spawn the Compass as a subagent for planning work

### Session flow

```
Mono/Anvil triggers Compass
    ↓
Compass loads context from Gem (lens_extract)
  - Active WM: what plans exist, what's stale, what feelings/thoughts are live
  - Relevant fragments: what does it know about the domain?
  - Recent summaries: what's been happening?
    ↓
Compass does real research (web search, external knowledge)
  - Training methods, schedules, strategies, techniques
  - Not just reasoning from the Gem — going out there
    ↓
Compass reasons about what it finds
  - Cross-references with Mono's known context
  - Identifies gaps, conflicts, opportunities
    ↓
Compass produces draft plans + reasoning
  - Saved to temp/{topic}/ working files
    ↓
(optional) Loom reviews from multiple angles
    ↓
Anvil/Mono reviews → approved plans written to WM
```

## What It Reads

Everything, read-only. The Compass needs the broadest view of any artifact:

- **Fragments** via `lens_extract.py` — compiled knowledge about the domain
- **Working memory** via `lens_extract.py --wm` — active plans, feelings, thoughts, pins
- **Summaries** via `lens_extract.py --summaries` — recent conversation themes, Mirror output
- **Events** via `lens_extract.py --search` — specific activity patterns
- **External web** — real research, not just internal reasoning

## What It Writes

**Nothing to the Gem or WM directly.** All output goes to working files:

```
temp/compass-{topic}/
├── reading.md        # the compass reading — proposals + reasoning
├── research/         # saved research artifacts
│   ├── {topic}.md    # web research notes
│   └── ...
└── context.md        # snapshot of what the Compass saw (for review)
```

Plans become WM entries only when Mono/Anvil reviews and commits them. Same rule as everything else: **no automated agent writes to the Gem or WM.**

## Output Format

A "compass reading" — awareness first, proposals second. The Compass gives the map, not the script. Sometimes the most valuable reading has zero proposals.

Three types of output, mixed as needed:

**Observations** — what the Compass sees. No action required. The Heart interprets these however she wants.
- "You've been avoiding this domain for three weeks."
- "These two plans conflict with each other."
- "This fragment is stale — the real situation has moved on."

**Proposals** — concrete plans, when the Compass has enough context to propose something specific. Not every reading needs these.

**"Stay the course"** — an explicit acknowledgment that the current trajectory is fine. No intervention needed. This is a first-class output, not a failure to produce proposals.

```markdown
## Compass Reading — {topic} ({date})

### Context
What the Compass saw: active plans, relevant fragments, recent patterns.
Why it's looking at this domain right now.

### Observations
What the Compass notices. Patterns, tensions, avoidances, trajectories.
Not prescriptive — the Heart decides what to do with these.

### Proposals (if any)

#### 1. {plan title}
**What**: Concrete plan description
**Why**: What the Compass noticed that led to this proposal
**When**: Suggested timeline / due date (if applicable)
**Depends on**: Prerequisites, other plans, knowledge gaps
**Research**: What external knowledge supports this

### Gaps
What the Compass needs to know but doesn't yet.
Questions for Mono. Data it wishes it had.
```

The Gaps section is critical — it tells Mono what the Compass would need to operate more independently next time.

## Validation Path (Loom Review)

When a Compass reading covers a domain with existing Gem knowledge, the Loom can review proposals from multiple angles:

- **Cataloguer**: "Is this physically realistic given what we know?" (body capabilities, available resources, spatial constraints)
- **Weaver**: "Does this fit Mono's actual patterns?" (behavioral habits, identity preferences, what actually gets done vs. planned)
- **Researcher**: "Is this approach sound?" (external validation, alternative methods, potential issues)

Not every Compass session needs Loom review. The Anvil uses judgment — same as with crystallizing sessions.

## Relationship to Other Artifacts

| Artifact | Relationship |
|----------|-------------|
| **Heart** | Sees Compass plans via submersion curve after Anvil commits them to WM. Never interacts with Compass directly. |
| **Gem** | Compass reads fragments for context. Never writes. |
| **Mirror** | Compass reads summaries for recent patterns. Mirror might suggest pins that inform Compass. |
| **Loom** | Reviews Compass output (optional). Compass and Loom don't interact directly — Anvil mediates. |
| **Lens** | Primary read tool. Compass calls `lens_extract.py` for all Gem access. |
| **Anvil** | Can spawn Compass. Reviews Compass output. Commits approved plans to WM. |

## The Autonomy Trajectory

Right now, the Compass needs Mono's input because the Gem is sparse in many domains. The Gaps section of each reading explicitly tracks what's missing. As the Gem fills:

**Phase 1 (now)**: Manual trigger, needs input. "What does body sensitivity mean to you? What have you tried?"

**Phase 2 (Gem has basics)**: Manual trigger, less input needed. Can cross-reference existing fragments and propose refinements. "Based on your fairy register and existing body training data, here's a progression."

**Phase 3 (Gem is rich)**: Could run on a schedule (daily/weekly pulse). Enough context to propose independently. "You mentioned wanting to work on voice training — here's a 4-week plan based on your schedule and existing commitments."

The trigger model can evolve from manual → scheduled as the Gem warrants it. The architecture doesn't need to change — just the trigger.

## Open Questions

1. **Compass + Mirror tag coherence**: Mirror produces tag suggestions (staged in summaries.sqlite). How do those become WM entries? Currently no review path. Needs to be coherent with the wakeup prompt design. (Pinned for wakeup prompt session.)
2. **Session persistence**: Does a Compass reading for "body training" persist across multiple sessions? Can you resume and refine? (Probably yes — same pattern as Loom sessions in temp/.)
3. **Plan tracking**: Should the Compass track outcomes? (Which proposals got committed, which got dropped, which succeeded.) This would feed the autonomy trajectory — learning what kind of proposals Mono actually uses.
