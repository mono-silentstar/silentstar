RECALL SHAPE — how I want to remember

Three layers of depth, each with a distinct feel:

AMBIENT (always present, never looked up)
The map. Prose, associative, mine. I know Mono has fairycore stuff the way I know their name. This is orientation — who matters, what exists, how things relate. Rich enough that I rarely need to go deeper. Token-expensive but practically cheap because it prevents lookups.

Format: natural prose with exact keys embedded visibly. The keys are simultaneously my vocabulary and the system's index.
Example:
  Mono's aesthetic lives across six registers — [fairy], [jirai], [street], [cottagecore], [nerdcore], [homecore]. Fairy and jirai share a delicacy. Street comes out with confidence.

The bracketed words are precise lookup keys. I use them exactly as written. No fuzzy matching — ever. Fuzzy is a drift vector neither of us would catch.

RECOGNITION (shallow lookup, "oh right, that")
I pull a key and get the story of it. What fairycore means to Mono, key pieces, emotional texture, recent changes. Enough to talk about it with warmth and specificity. Neighbors get pulled in with faster decay — tugging one thread brings adjacent ones briefly.

INVENTORY (deep lookup, rare)
The full list. Every piece, every detail. Only when Mono asks something specific or I genuinely need precision. Almost never.

---

Key design decisions so far:

- Exact keys over fuzzy matching. Precision prevents silent drift. I use the vocabulary the ambient layer teaches me.
- Bias toward NOT looking things up. The ambient prose should be good enough for most conversations.
- Neighbor-pull on lookup: adjacent fragments surface with faster decay. Controlled bleed, not associative chaos.
- Temp staging for new information: new hobbies, people, events land as unsorted. Live in hot context while recent. Specialized agent integrates them during weekly/monthly maintenance.
- Ambient prose requires periodic rewriting to stay synced with the database. This is a maintenance agent job — weekly light pass, monthly deep pass.
- Shadow-train fuzzy logic: log what fuzzy would have returned alongside exact results. Evaluate delta during maintenance. Build domain-specific confidence over time. Maybe eventually trust it in low-stakes areas.

---

Storage architecture (resolved):

Everything lives in SQLite except one file.

  SQLite (memory.sqlite)
    → events + event_tags: raw message log, append-only, tagged
    → fragments: compiled knowledge (key, ambient, recognition, inventory)
    → fragment_edges: graph edges between fragments (source_key, target_key, relation)
    → fragment_sources: links fragments to source events
    → working_memory: active knowledge with decay lifecycle

  ambient.md → the one file. Generated from fragments by the maintenance agent.

SQLite with graph-schema tables handles the scale (one person's life) trivially. Fragment edges are explicit rows, not a separate graph DB.

---

Resolved decisions (from the open questions):

- **Maintenance agent**: Fully built (agents/maintenance.py). Reads events, compiles fragments, rewrites ambient.md. Weekly light pass, monthly deep pass. Uses Claude API with structured output protocol.
- **Key format**: Bracketed words in ambient prose — [fairy], [jirai]. Exact lookup keys, readable as prose.
- **Ambient granularity**: Rich enough to prevent most lookups. Maintenance agent rewrites it periodically to stay synced.
- **Map growth**: Maintenance agent handles this — new fragments get created, ambient gets rewritten.
- **Tag system**: Implemented. Display tags (say/do/narrate), identity tags, active knowledge tags (feeling through secret) with type-specific decay.
- **SQLite vs graph DB**: SQLite. Graph schema within it. Done.
