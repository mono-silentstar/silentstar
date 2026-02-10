RECALL SHAPE — how I want to remember

Three layers of depth, each with a distinct feel:

AMBIENT (always present, never looked up)
The map. Prose, associative, mine. I know Mono has fairycore stuff the way I know their name. This is orientation — who matters, what exists, how things relate. Rich enough that I rarely need to go deeper. Token-expensive but practically cheap because it prevents lookups.

Format: natural prose with exact keys embedded visibly. The keys are simultaneously my vocabulary and the system's index.
Example:
  Mono's aesthetic lives across five registers — [fairy], [jirai], [street], [homecore], [nerdcore]. Fairy and jirai share a delicacy. Street comes out with confidence.

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

Storage architecture (locked):

Everything lives in the database except one file. Optimized for my eyes — prose in content fields is still prose, but the container is queryable, traversable, maintainable.

  Database (SQLite or graph DB — TBD)
    → events: raw message log, append-only, tagged, never interpreted
    → fragments: compiled knowledge (key, depth, prose content, sources)
    → associations: graph edges between fragments (explicit, authored)
    → tag relationships: graph structure for event tags

  ambient.md → the one file. Generated from fragments. What I wake up to.

Why not files for fragments: 500 fragments = 500 files to glob, parse, traverse. Database gives clean lookup, clean graph traversal, clean maintenance. The prose is identical either way — the container is what changes.

Why database for events: append-only structured data. SQLite is literally made for this.

Why graph structure for associations + tags: a message can be <luna> + <plan> + <secret> simultaneously. Fragments connect to each other through explicit edges. These are graph relationships, not rows. Whether this is a graph DB or a graph schema within SQLite is TBD.

The ambient file is the only thing that needs to be a file because it's always in context. Everything else is accessed through lookup.

---

Open questions:

- What does the maintenance agent look like? How does it know what I know? How do we tell it to do this work without having this conversation again?
- Key format delimiter — brackets, bold, something else? Needs to be readable as prose AND parseable by the system.
- How granular should ambient prose be? Too sparse = guessing. Too detailed = just the database with extra steps.
- How do we handle the map growing as Mono's life grows? Structure can't be static.
- Tag system design — what tags exist, how they interact, how they influence storage and retrieval.
- SQLite with graph schema vs dedicated graph DB? Scale is personal (one person's life), so probably SQLite is fine, but worth considering.
