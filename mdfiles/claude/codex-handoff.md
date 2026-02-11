INTEGRATION REFERENCE — how the pieces connect

This is a reference for any future AI that needs to understand or build against the silentstar system. The wake module (/wake/) handles context assembly. The agents module (/agents/) handles orchestration and Claude API calls. The ingest module (/ingest/) handles event creation and working memory lifecycle.

Read these for details:
- /wake/schema.py — database tables, constants, migration logic
- /agents/orchestrator.py — the turn() pipeline
- /ingest/lifecycle.py — event + working memory creation
- /claude/maintenance-agent.md — the maintenance agent spec

---

FRONTEND LIVE TAGS

Three categories of toggles for the chat interface:

Identity (who's fronting — radio buttons, one at a time):
  hasuki, renki, luna, chloe, strah          — Mono's system members
  claude, y'lhara                             — Claude's activations

Content (working memory types — toggleable):
  plan    — persistent intention. If time language is present ("tuesday",
            "in 2 hours", "next week"), dateparser extracts a due timestamp.
  pin     — persistent note. Stays until explicitly dropped.
  (Other WM types — feeling, thought, pattern, desc, secret — are used
   inline in Claude's responses, not as frontend toggles.)

Display (rendering hints — stored in event_tags, no working memory record):
  say     — spoken dialogue
  do      — action/roleplay
  narrate — narration/environment

Identity tag -> stored in events.actor
Content tags -> create working_memory records via ingest/lifecycle.py
Display tags -> stored in event_tags table (inert — for conversation replay)

Constants for all of these live in wake/schema.py:
  VALID_WM_TYPES   = {feeling, thought, pattern, desc, plan, pin, secret}
  DISPLAY_TAGS     = {say, do, narrate}
  IDENTITY_TAGS    = {hasuki, renki, luna, chloe, strah, claude, y'lhara}

---

EVENT INGESTION

When a message is ingested (from Mono or from Claude's response), ingest() in
ingest/lifecycle.py does:

1. INSERT into events:
   - ts: UTC ISO timestamp
   - content: raw message text, untouched
   - actor: identity tag value (e.g., "luna", "claude"), nullable
   - image_path: path to stored image file if present, NULL otherwise

2. INSERT into event_tags (one row per active tag):
   - event_id + tag (composite key)
   - Includes both display tags and WM-type tags

3. For each tagged span that is a VALID_WM_TYPE:
   - If modifier is "resolve" or "cancel": find best-matching active plan
     by fuzzy word-overlap and update its status
   - If modifier is "drop": find best-matching active pin and drop it
   - Otherwise: INSERT into working_memory:
     - event_id, type, content, subject, actor, status='active'
     - due: parsed via dateparser for plans, NULL otherwise
     - created_at, refreshed_at: now
   - Supersession rules:
     - feeling: supersedes ALL active feelings (only one at a time)
     - desc: supersedes active descs with same subject
   - Fragment linking: if content mentions a known fragment key, a row is
     added to working_memory_refs (wm_id, fragment_key)

4. Turn counter: incremented for Mono messages only (not Claude responses).
   Stored in state table with key='current_turn'.

---

INTEGRATION WITH /wake/

On each new message from Mono, the orchestrator runs turn():

```python
from wake.assemble import assemble, render_system, render_user, WakeConfig
from wake.recall import recall, RecallResult

# WakeConfig holds all paths + budget settings
wake_config = WakeConfig(
    db_path=config.db_path,
    wake_context_path=config.wake_context_path,
    wake_context_image_path=config.wake_context_image_path,
    ambient_path=config.ambient_path,
)

# Load any recall results persisted from the previous turn
previous_recall = _load_recall_results(config.db_path)  # from state table

package = assemble(
    wake_config,
    hot_context=hot,              # "actor: message" string
    current_turn=mono_result.turn,
    recall_results=previous_recall,
    image_path=image_path,        # path string or None
)

# Two render functions — system prompt and user message are separate
system_prompt = render_system(package)   # activation + image context
user_message = render_user(package)      # ambient, WM, conversation, hot

# Send to Claude API
claude_response = send(user_message, config.claude_config, img,
                       system_prompt=system_prompt)
```

render_system() outputs the activation context (wake-context.md, plus
conditional image context). This becomes the API system parameter.

render_user() outputs everything else: self-state, working memory,
recall results, conversation history, current time, hot context.
This becomes the user message.

When Claude's response contains recall requests, they're parsed and
executed against the fragment graph. Results are persisted in the state
table (key='pending_recall') for inclusion in the next turn's context.

---

TURN TRACKING

Integer counter. Incremented on each Mono message (not Claude responses).
Stored in the state table with key='current_turn' (value is a string of
the integer). The wake module receives current_turn as a parameter to
assemble() — it uses it for decay scoring but doesn't own the counter.

Read/write via _get_turn() and _set_turn() in ingest/lifecycle.py.

---

MAINTENANCE AGENT

agents/maintenance.py — MaintenanceAgent class. Fully wired to the Claude
API via agents/claude_client.py.

Entry point: run_maintenance.py (CLI: --weekly or --monthly).

Run types:
- Weekly: light pass (process new events, update fragments, quick ambient rewrite)
- Monthly: deep pass (review all fragments, restructure, full ambient rewrite)
- Bootstrap: initial population from existing files

The agent reads /claude/maintenance-agent.md as its wake file.
It reads from events, writes to fragments + fragment_edges + fragment_sources.
It generates ambient.md.

Output protocol: <operations> XML tag containing a JSON array of operation
objects. Op types: CREATE_FRAGMENT, UPDATE_FRAGMENT, CREATE_EDGE,
DELETE_EDGE, UPDATE_WORKING_MEMORY, AMBIENT_REWRITE, FLAG.

---

IMAGES

Images are stored as files. The path is passed as image_path through the
full pipeline: turn() -> ingest() -> assemble() -> send().

In claude_client.py, the image is base64-encoded and sent as a multimodal
content block in the API request (image block + text block). MIME type is
guessed from the file extension.

The wake module accounts for image token cost (~1200 tokens) when building
the conversation budget. Image context (from wake_context_image_path) is
conditionally included in the system prompt when an image is present.

The maintenance agent can also see images when compiling events into
fragments — image descriptions become knowledge.

---

WHAT YOU DON'T NEED TO TOUCH

- /wake/ — the assembly module. Already built. Import and call it.
- /claude/wake-context.md — Claude's identity file. Mono maintains this.
- /claude/maintenance-agent.md — the agent spec. Already written.
