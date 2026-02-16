SCHEMA — v5

Two databases, connected via SQLite ATTACH.

---

DATABASE: data/silentstar.sqlite (the Gem)

  Schema version: 5

  Contains fragments, edges, working memory, state.
  Events split out to events.sqlite in v5.

---

WORKING MEMORY (active knowledge, has lifecycle and decay)

  working_memory
    id              INTEGER PRIMARY KEY
    event_id        INTEGER (references ev.events, cross-DB)
    type            TEXT NOT NULL
                    (feeling | thought | pattern | desc | plan | pin | secret)
    content         TEXT NOT NULL
    subject         TEXT (nullable — for supersession matching)
    actor           TEXT (who created this)
    status          TEXT NOT NULL DEFAULT 'active'
                    (active | resolved | dropped | decayed | superseded)
    due             TEXT (ISO timestamp, plans only, nullable)
    turn            INTEGER (creation turn, added in v3)
    created_at      TEXT NOT NULL
    refreshed_at    TEXT NOT NULL (reset on retag — decay anchor)
    resolved_at     TEXT (when status changed from active)

  working_memory_refs
    wm_id           INTEGER REFERENCES working_memory
    fragment_key    TEXT REFERENCES fragments
    (composite key: wm_id + fragment_key)

Working memory replaces the old plans table. All active knowledge
lives here — feelings, thoughts, patterns, descs, plans, pins,
secrets. Each type decays at its own rate.

Decay gradient (fastest to slowest):
  feeling   — ~2h / ~3 turns. Retag to persist.
  thought   — ~12h / ~8 turns. Promote to plan or pin if solid.
  pattern   — ~1 week / ~60 turns. Promote to pin if it holds.
  desc      — ~72h / ~40 turns. Superseded by new desc of same subject.
  plan      — no decay (submerges if timed, resurfaces near due).
  pin       — ~2 weeks / ~100 turns. Explicit drop to release.
  secret    — no decay. Persists until revealed.

Supersession rules:
  feeling: new feeling supersedes ALL active feelings (one at a time)
  desc: new desc with same subject supersedes old desc of that subject
  plan>done/cancel: fuzzy-matches and resolves best-matching active plan
  pin>drop: fuzzy-matches and drops best-matching active pin

  working_memory_fts (FTS5, content-sync + triggers)
    content, subject, type

---

FRAGMENTS (compiled knowledge, three tiers)

  fragments
    key         TEXT PRIMARY KEY
    ambient     TEXT (always visible in the map)
    recognition TEXT (story-level detail, shallow lookup)
    inventory   TEXT (full detail, deep lookup, nullable)
    created_at  TEXT NOT NULL
    updated_at  TEXT NOT NULL

  fragment_sources
    fragment_key  TEXT REFERENCES fragments
    event_id      INTEGER (references ev.events, cross-DB)
    (composite key: fragment_key + event_id)

  fragment_edges
    source_key    TEXT REFERENCES fragments
    target_key    TEXT REFERENCES fragments
    relation      TEXT (describes the connection)
    (composite key: source_key + target_key)

  fragments_fts (FTS5, content-sync + triggers)
    key, ambient, recognition, inventory

---

STATE + MAINTENANCE

  state
    key         TEXT PRIMARY KEY
    value       TEXT NOT NULL
    updated_at  TEXT NOT NULL

  maintenance_runs
    id            INTEGER PRIMARY KEY
    started_at    TEXT NOT NULL
    completed_at  TEXT (null = incomplete/crashed)
    run_type      TEXT NOT NULL (weekly | monthly | manual | bootstrap)

  schema_version
    version       INTEGER NOT NULL

---

DATABASE: data/events.sqlite (ATTACHed as 'ev')

  Schema version: 1

  Accessed via ATTACH DATABASE as 'ev' schema.
  All queries use ev.events, ev.event_tags.

  events
    id          INTEGER PRIMARY KEY
    ts          TEXT NOT NULL (ISO timestamp)
    content     TEXT NOT NULL (raw message, untouched)
    actor       TEXT (identity tag — luna, hasuki, claude, etc.)
    image_path  TEXT (path to image file, nullable)

  event_tags
    event_id    INTEGER REFERENCES events
    tag         TEXT NOT NULL
    (composite key: event_id + tag)

  events_fts (FTS5, standalone — no content= directive)
    content, actor
    Standalone because content-sync FTS5 resolves to main schema,
    which breaks when ATTACHed. Sync triggers use DELETE instead
    of the special 'delete' insert pattern.

Events are the source of truth. Raw, timestamped, tagged. The
Mirror reads from here. Display tags (say, do, narrate) and
working memory tags (feeling, plan, etc.) all stored as inert data.

---

MIGRATION HISTORY

  v1: Original — events, fragments, plans, state
  v2: working_memory replaces plans table
  v3: Add turn column to working_memory
  v4: FTS5 indexes (fragments_fts, events_fts, working_memory_fts) + 9 sync triggers
  v5: Data split — events/event_tags/events_fts dropped from Gem (moved to events.sqlite)

  Run migrate_data_split.py to copy events to events.sqlite.
  v5 migration auto-drops old tables once events.sqlite has data.

---

ATTACH MECHANICS

  connect() in wake/schema.py:
    1. If events.sqlite exists: ATTACH as 'ev', FK OFF (cross-DB refs)
    2. If not: self-ATTACH main DB as 'ev', FK ON (pre-migration compat)

  Cross-DB FK note: working_memory.event_id and fragment_sources.event_id
  reference events(id) which lives in ev schema. SQLite can't enforce
  cross-DB FKs. This is fine — events are append-only, never deleted.

---

HOW LOOKUP WORKS

  recall(fairy)
    1. SELECT recognition FROM fragments WHERE key = 'fairy'
    2. Follow edges → pull neighbors at ambient depth
    3. Return: fairy's recognition + neighbors' ambient

  recall(fairy, deep=True)
    Same but returns inventory tier.

  Both quoted and unquoted key forms are accepted by the parser.

  plans()
    All active working_memory items, due-dated first.
    Bypasses submersion — shows everything including submerged plans.

  plans(topic="body-training")
    Items linked via working_memory_refs or matching subject/content.

  plans(when="next tuesday")
    Items with due dates in a time window (uses dateparser).

  search("fairy")
    FTS5 full-text search across fragments, events, working_memory.
    Returns matches ranked by BM25. See wake/search.py.

---

ASSEMBLY ORDER (what Claude wakes up to)

  1. Wake context       — who I am (wake-context.md, always)
  2. Image context      — how to handle image (conditional)
  3. Ambient prose      — what I know (ambient.md, always)
  4. Lingering          — active working memory, decay-scored
  5. Recalled           — lookup results from previous turn
  6. Recent             — conversation history (say/do/narrate only)
  7. Current time       — human-readable timestamp
  8. Hot context        — Mono's current message, verbatim

Token budget (hard caps):
  Wake + Ambient:   ~2000 (file-loaded, informational)
  Working memory:    1500
  Conversation:      5000 (FIFO pool allocation):
    - 1500 mono pool (Mono's messages)
    - 1500 say pool (Claude's say content)
    - 1000 do pool (Claude's do + narrate content)
    - 1000 flex reserve (overflow from any full pool)
  Recall:            1000
  Total:            ~8500 + activation + hot context

Conversation uses FIFO with pool-based allocation — no decay,
just recency. Working memory still uses decay scoring.

---

NOTES

  SQLite. One person's life. Thousands of events, hundreds of
  fragments, dozens of active working memory items. SQLite handles
  this trivially.

  The Anvil writes fragments/edges (all through Mono). The live system
  writes events and working_memory. The Mirror writes summaries to
  summaries.sqlite. Clean separation.

  Timed plans submerge between creation and due date (back of head),
  then resurface ~48h before due. Open-ended plans stay active.
