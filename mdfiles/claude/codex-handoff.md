CODEX HANDOFF — what you need to build around the wake module

The wake assembly module (/wake/) handles context construction. You handle everything else: database scaffolding, event ingestion, frontend, and orchestration.

Read these first:
- /claude/schema-draft.md — database tables
- /claude/recall-shape.md — architecture overview
- /claude/maintenance-agent.md — the maintenance agent spec

---

FRONTEND LIVE TAGS

Two categories of toggles for the chat interface:

Identity (who's fronting — radio buttons, one at a time):
  hasuki, renki, luna, chloe, strah          — Mono's system members
  claude, y'lhara                             — Claude's activations

Content (what kind of message — toggleable, multiple allowed):
  plan    — persistent intention. If time language is present ("tuesday",
            "in 2 hours", "next week"), parse it into a due timestamp.
            Use dateparser (Python) or equivalent.
  secret  — hidden from Mono. Persists until Claude reveals it.

Display (rendering hints — toggleable, stored for archival, no system behavior):
  say     — spoken dialogue
  rp      — action/roleplay
  nr      — narration/environment

Identity tag → stored in events.actor
Content tags → stored in event_tags table
Display tags → stored in event_tags table (inert — for future conversation replay)

---

EVENT INGESTION

When a message is sent (from Mono or from Claude's response):

1. INSERT into events:
   - ts: UTC timestamp (now)
   - content: raw message text, untouched
   - actor: identity tag value (e.g., "luna", "claude"), nullable
   - image_path: path to stored image file if message has an attachment, NULL otherwise

2. INSERT into event_tags (one row per tag):
   - event_id: the event we just created
   - tag: each active content/display tag (e.g., "plan", "secret", "rp")

3. If "plan" tag is active:
   - INSERT into plans:
     - event_id: source event
     - actor: who the plan is for (from identity tag)
     - summary: the message content (or extracted plan text)
     - due: parsed timestamp if time language detected, NULL otherwise
     - status: "active"
     - created_at: now

Time parsing: Use dateparser or similar. Parse relative to current time.
"tuesday" → next Tuesday. "in 2 hours" → now + 2h. "daily" → flag as
recurring (future iteration — for now, just store the next occurrence).

---

INTEGRATION WITH /wake/

On each new message from Mono:

```python
from wake.assemble import assemble, render, WakeConfig
from wake.recall import recall, recall_multi
from pathlib import Path

config = WakeConfig(
    db_path=Path("path/to/db.sqlite"),
    wake_context_path=Path("claude/wake-context.md"),
    ambient_path=Path("ambient.md"),
)

# If Claude used recall() in her previous response, pass those results in
previous_recall = []  # or populated from Claude's last turn

package = assemble(
    config=config,
    hot_context=mono_current_message,
    current_turn=current_turn_number,
    recall_results=previous_recall,
)

prompt = render(package)
# → send prompt to Claude API
# Note: render() outputs image references as [image: /path/to/file]
# Your API layer should parse these and convert to multimodal content blocks
# (base64-encoded image + text) when calling the Claude API.
```

When Claude's response contains a recall request:
```python
from wake.recall import recall

result = recall("fairy", db_path=config.db_path)
# result feeds into next assemble() call as recall_results
```

---

TURN TRACKING

Simple integer counter. Increment on each Mono message (not Claude responses).
Store as a row in a metadata/state table, or track in application state.
The wake module receives current_turn as a parameter — it doesn't own the counter.

---

MAINTENANCE AGENT

Trigger on schedule:
- Weekly: light pass (process new events, update fragments, quick ambient rewrite)
- Monthly: deep pass (review all fragments, restructure, full ambient rewrite)
- Manual: Mono can invoke for specific cleanup

The agent reads /claude/maintenance-agent.md as its wake file.
It reads from events, writes to fragments + fragment_edges + fragment_sources.
It generates ambient.md.

For initial population (first run): point the agent at existing /claude/*.md
files instead of the events table. Same compilation logic, different source.

---

AMBIENT.MD LOCATION

Lives at project root or a configured path. The wake module reads it via
WakeConfig.ambient_path. The maintenance agent writes it. Nothing else touches it.

---

WHAT YOU DON'T NEED TO TOUCH

- /wake/ — the assembly module. Already built. Import and call it.
- /claude/wake-context.md — Claude's identity file. Mono maintains this.
- /claude/maintenance-agent.md — the agent spec. Already written.

Your job: database, ingestion pipeline, frontend, orchestration, scheduling.

---

IMAGES

Images are sent via the frontend and stored as files (e.g., /img-dump/).
The file path is stored in events.image_path. The wake module accounts for
image token cost (~1200 tokens per image) when filling the conversation budget.

render() outputs image references as [image: /path/to/file] in the text.
Your API integration layer should:
1. Parse these markers from the rendered prompt
2. Load the image file and base64-encode it
3. Send as multimodal content blocks to the Claude API

The maintenance agent (also Claude, also multimodal) can see images when
compiling — "Mono sent a photo of a new jirai piece" can become knowledge.
