# The Loom — Facet Agents

The Loom is a set of four facet agents that provide multiple perspectives on any given work. They're tools, not a protocol — the Anvil decides when to call them, which ones, and how to use their output. Each facet sees the same material from a different angle.

## The Four Agents

### The Cataloguer (spatial, inventory)

Describes things physically. Measurements, materials, colors, locations, conditions. Thinks in lists and categories. Looks hardest at images. Call it when you need a second pair of eyes on physical details, or to verify inventory against photos.

**Prompt file:** `mdfiles/claude/loom-cataloguer.md`

### The Weaver (relational, behavioral)

Finds connections between things and identities, moods, contexts. Style pairings, emotional associations, usage patterns. Knows about Mono's plurality. Call it when you've drafted content and want to catch relational insights you missed.

**Prompt file:** `mdfiles/claude/loom-weaver.md`

### The Researcher (external knowledge, fact-checking)

Brings in knowledge from outside the data. Material care, technical specs, best practices. Has web search access. Call it when you need practical information that can't be inferred from photos or existing data.

**Prompt file:** `mdfiles/claude/loom-researcher.md`

### The Questioner (uncertainty, assumptions, unexplored angles)

Resists convergence. Where the other three agents add information, the Questioner expands the question space. It enumerates uncertainties, surfaces assumptions that were made without examination, and maps alternative directions that weren't explored. Call it on anything before committing — drafts, plans, designs, code.

Not adversarial. Not a devil's advocate arguing the opposite. It maps the terrain of what hasn't been considered yet, so Mono and the Anvil can decide which doors to open rather than having them closed by default.

**Prompt file:** `mdfiles/claude/loom-questioner.md`

## How the Anvil Uses Them

The crystallizing Anvil does the primary work with Mono — looking at photos, drafting fragments, organizing inventory. The facet agents are second opinions. The Anvil should be **biased toward calling them** rather than skipping them, because they catch things the Anvil misses.

Typical patterns:

- **After drafting inventory from photos** → call Cataloguer to verify spatial details, call Researcher to check material care
- **After writing recognition tiers** → call Weaver to find connections you missed
- **When cataloguing unfamiliar items** → call Researcher for specs and best practices
- **When a session has images** → call Cataloguer to cross-check what you see
- **Before committing anything significant** → call Questioner to surface what you haven't considered
- **On Compass readings** → call Questioner + Weaver to check proposals against patterns and blind spots
- **On code/design reviews** → call Questioner to enumerate assumptions and unexplored alternatives

Not every session needs all four. Not every session needs any. The Anvil uses judgment.

### Running the Loom

**Primary path: Claude Code orchestrator** (recommended)

Run the Loom agent directly:
```bash
claude --agent loom
```

Or spawn it from an Anvil session via Task tool. The Loom orchestrator (`.claude/agents/loom.md`) handles everything: reads the draft, gathers Gem context, spawns facets in parallel as Claude Code subagents, collects results. Each facet has full tool access — the Researcher can do real web searches, the Questioner can look things up.

**Legacy path: API runner** (still available)

`run_loom.py` calls the Claude API directly — simpler but no tool access:
```bash
python3 run_loom.py temp/wardrobe/inventory.md
python3 run_loom.py temp/wardrobe/inventory.md --agents questioner,weaver
```

### Facet output

Each facet writes `{facet}-notes.md` to `temp/<session>/` alongside the Anvil's working files. The Anvil reads the output, incorporates what's useful, discards what isn't.

## Sessions

Crystallizing sessions live in `temp/<topic>/` and can span multiple Anvil conversations. Working files accumulate:

```
temp/room-inventory/
├── inventory.md          # evolving draft
├── plan.md               # phased approach
├── pics/
│   ├── first-pass/       # initial photos
│   ├── survey/           # organized by zone
│   │   ├── bed/
│   │   ├── kitchen/
│   │   └── storage/
│   └── cleanup/          # progress photos
├── cataloguer-notes.md   # facet agent output (optional)
├── researcher-notes.md   # facet agent output (optional)
└── questioner-notes.md   # facet agent output (optional)
```

Sessions are iterative. The Anvil might:
1. First pass: look at photos with Mono, draft rough inventory
2. Call Cataloguer to verify spatial details
3. Mono takes more photos, reorganizes
4. Second pass: refine, call Weaver for relational insights
5. Call Researcher for care instructions on specific items
6. Commit to the Gem when Mono is satisfied

Or it might be a single-pass session. The Anvil follows the work, not a script.

## Image Pipeline

Images are **working material**, not permanent storage. Two paths to get them local:

### Path 1: Direct drop (simplest)
Mono drops images directly into `temp/<session>/pics/` from phone (file sharing, network, etc). No server involved.

### Path 2: Phone upload → pull → auto-clear
For accumulating photos throughout the day when away from the computer:

1. **Upload**: Phone → PWA camera button → `api/upload_loom.php` → server `data/uploads_loom/`
2. **Pull**: `python loom_pull.py temp/<session>/pics/` → downloads all images from server to local folder
3. **Auto-clear**: Pull script deletes server copies immediately after successful download

Server is transit only. Images never accumulate there.

### Upload API (built)
- `api/upload_loom.php` — POST with `images[]`, saves to `data/uploads_loom/`
- `api/loom_images.php` — GET lists uploads, GET `?file=name` serves file, POST `action=clear` deletes all

## Committing to the Gem

When the Anvil is ready to commit (Mono has reviewed, work is done):
1. Run `python lens_diff.py temp/<session>/draft.md` to preview changes (optional)
2. Write fragments and edges directly to the Gem with judgment
3. Working files in `temp/<session>/` can be kept for reference or cleaned up

## Dependencies

- `lens_extract.py` — read current Gem state (DONE)
- `lens_diff.py` — preview changes (DONE)
- `api/upload_loom.php` + `api/loom_images.php` — phone upload path (DONE)
- `loom_pull.py` — download + auto-clear from server (DONE)
- `mdfiles/claude/loom-cataloguer.md` — Cataloguer prompt (DONE)
- `mdfiles/claude/loom-weaver.md` — Weaver prompt (DONE)
- `mdfiles/claude/loom-researcher.md` — Researcher prompt (DONE)
- `mdfiles/claude/loom-questioner.md` — Questioner prompt (DONE)
- `.claude/agents/loom.md` — Loom orchestrator agent (DONE)
- `run_loom.py` — Legacy API runner (DONE, kept as fallback)

## Open Questions

1. **Agent model**: Sonnet (cheaper, faster) or Opus (better judgment)? Cataloguer might be fine on Sonnet. Weaver probably needs Opus.
2. **Researcher scope**: How much web searching per session? Maybe only called when specifically needed.
3. **Pattern promotion**: When the Weaver surfaces patterns, how do they become `<pattern>` WM items?
