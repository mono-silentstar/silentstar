# Silentstar

Persistent memory and context system for Claude. Seven artifacts, one folklore set.

## Anvil Types

The Anvil is Claude Code. There are two kinds of session:

### System-building Anvil (architecture, design, code)
Read order:
1. **`ARCHITECTURE.md`** — the single source of truth. Start here.
2. **`temp/12-2-26/session-feb13-todo.md`** — latest design session decisions and remaining work.
3. **`temp/12-2-26/compression-design.md`** — authoritative design doc for planned direction.
4. **`temp/12-2-26/system-prompt-draft.md`** — current system prompt draft (v2, anti-patterns pending).

### Crystallizing Anvil (cataloguing, compiling, inventorying)
Read order:
1. **`mdfiles/claude/anvil-crystallize.md`** — session guide, fragment schema, principles.
2. Run `python lens_extract.py <key>` to see current Gem state.
3. Work with Mono — look at photos, draft fragments, organize.
4. Call facet agents for second opinions (see Tools below).
5. Commit directly to the Gem when done.

Sessions persist in `temp/<topic>/` across conversations. Work is iterative.

---

## Tools

### lens_extract.py — Read the Gem

Query fragments, edges, and working memory. Pure read-only.

```bash
python lens_extract.py wardrobe                     # single key + neighbors
python lens_extract.py wardrobe jirai exhibitionist  # multi-key intersection
python lens_extract.py --all                         # all fragments
python lens_extract.py --wm                          # working memory state
python lens_extract.py --summaries                   # mirror summaries
python lens_extract.py wardrobe -o temp/out.md       # output to file
```

### lens_diff.py — Preview Changes

Parse a draft .md (same format as lens_extract output), diff against current DB state. Never writes.

```bash
python lens_diff.py temp/room-inventory/draft.md           # show what would change
python lens_diff.py temp/room-inventory/draft.md --db mem.db  # explicit DB
```

Output shows CREATE/UPDATE/unchanged for fragments, +/-/= for edges, `!` for wrong-direction edge removals.

### loom_pull.py — Pull Images from Server

Download phone-uploaded images from the server to a local session folder. Auto-clears server copies after download (server is transit only).

```bash
python loom_pull.py temp/room-inventory/pics/                  # interactive password
python loom_pull.py temp/room-inventory/pics/ --password pass   # explicit password
python loom_pull.py temp/room-inventory/pics/ --keep-server     # don't clear server
SILENTSTAR_PASSWORD=pass python loom_pull.py temp/pics/         # env var
```

### Facet Agents (the Loom)

Three specialist agents the crystallizing Anvil can call for second opinions. Spawn via the Task tool with the agent's prompt file + your draft + a specific ask.

| Agent | Prompt file | What it checks |
|-------|------------|----------------|
| **Cataloguer** | `mdfiles/claude/loom-cataloguer.md` | Spatial, physical. "Check this inventory against these photos." |
| **Weaver** | `mdfiles/claude/loom-weaver.md` | Relational, behavioral. "What connections am I missing?" |
| **Researcher** | `mdfiles/claude/loom-researcher.md` | External knowledge. "What's the care routine for merino?" Has web search. |

**Bias toward calling them.** They catch things the Anvil misses. Not every session needs all three, but if you've drafted content, at least one should review it.

Each returns structured review notes (verified/additions/corrections). The Anvil incorporates with judgment.

---

## Image Pipeline

Two paths to get images into a session:

1. **Direct drop** — Mono puts images in `temp/<session>/pics/` via file sharing. Simplest.
2. **Phone upload** — PWA camera button → server → `loom_pull.py` downloads to local → server auto-cleared.

Images are working material in `temp/`, not permanent storage. They don't go in the Gem — fragments describe what's in them.

---

## Fragment Format

```markdown
## [key]
Ambient: 1-2 sentences. What the Heart always knows. [bracketed keys] for recall.
Recognition: Story-level detail, relational knowledge, pairings, style rules.
Inventory: Full item lists, measurements, locations, care info.
```

Edges: `source → target (relation-type)`

- **Ambient** is the most important tier — it's what the Heart wakes up inside.
- **Items are data in inventory tiers**, not separate fragments. Graph stays at concept level.
- **All writes go through the Anvil** — Lens reads, Loom advises, Anvil commits directly.

---

## Key Files

### Architecture & Design
| File | What | When to read |
|------|------|-------------|
| `ARCHITECTURE.md` | Complete architecture reference | Always first |
| `spec/loom.md` | Loom spec — facet agents, sessions, image pipeline | Crystallizing sessions |
| `spec/lens-diff.md` | Diff tool spec | Understanding the preview tool |
| `temp/12-2-26/compression-design.md` | Mirror + artifact design, design principles | Working on design |
| `temp/12-2-26/mirror-experiments.md` | All 7 pipeline experiments, DO-density analysis | Working on Mirror |
| `temp/12-2-26/system-prompt-draft.md` | System prompt draft v2 | Working on wake/prompt |
| `spec/deployment.md` | cPanel deploy procedure | Deploying |

### Code
| Directory | What |
|-----------|------|
| `agents/` | orchestrator, claude_client, runner, maintenance (legacy) |
| `ingest/` | Tag parsing, working memory lifecycle |
| `wake/` | Schema, assembly, decay, recall |
| `worker/` | Cron worker, config |
| `web/` | PHP frontend (deployed to web host) |

### Context Files (loaded by code)
| File | Loaded by |
|------|-----------|
| `mdfiles/claude/wake-context.md` | `assemble.py` — Heart's system prompt |
| `mdfiles/claude/wake-context-image.md` | `assemble.py` — image context (conditional) |
| `mdfiles/claude/maintenance-agent.md` | `maintenance.py` — maintenance agent prompt |
| `mdfiles/claude/anvil-crystallize.md` | Crystallizing sessions |
| `mdfiles/claude/loom-*.md` | Facet agent prompts |
| `ambient.md` | `assemble.py` — self-state prose |

### Data
| File | What |
|------|------|
| `memory.sqlite` | Current database (all-in-one, pre-split) |
| `temp/` | Working sessions — persist across conversations |

---

## Keeping Docs in Sync

When making design changes, these may need updating:

- **`ARCHITECTURE.md`** — always update when architecture changes
- **`temp/12-2-26/compression-design.md`** — artifact roles, pipeline, design principles
- **`MEMORY.md`** (at `~/.claude/projects/.../memory/MEMORY.md`) — key facts (loaded into every Anvil session)

ARCHITECTURE.md is the canonical reference. When in doubt, trust it over other files.
