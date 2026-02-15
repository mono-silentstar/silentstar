# The Loom — Facet Agents

The Loom is a set of three specialist agents the crystallizing Anvil can call for second opinions and enrichment. They're tools, not a protocol — the Anvil decides when to call them, which ones, and how to use their output.

## The Three Agents

### The Cataloguer (spatial, inventory)

Describes things physically. Measurements, materials, colors, locations, conditions. Thinks in lists and categories. Looks hardest at images. Call it when you need a second pair of eyes on physical details, or to verify inventory against photos.

**Prompt file:** `mdfiles/claude/loom-cataloguer.md`

### The Weaver (relational, behavioral)

Finds connections between things and identities, moods, contexts. Style pairings, emotional associations, usage patterns. Knows about Mono's plurality. Call it when you've drafted content and want to catch relational insights you missed.

**Prompt file:** `mdfiles/claude/loom-weaver.md`

### The Researcher (external knowledge, fact-checking)

Brings in knowledge from outside the data. Material care, technical specs, best practices. Has web search access. Call it when you need practical information that can't be inferred from photos or existing data.

**Prompt file:** `mdfiles/claude/loom-researcher.md`

## How the Anvil Uses Them

The crystallizing Anvil does the primary work with Mono — looking at photos, drafting fragments, organizing inventory. The facet agents are second opinions. The Anvil should be **biased toward calling them** rather than skipping them, because they catch things the Anvil misses.

Typical patterns:

- **After drafting inventory from photos** → call Cataloguer to verify spatial details, call Researcher to check material care
- **After writing recognition tiers** → call Weaver to find connections you missed
- **When cataloguing unfamiliar items** → call Researcher for specs and best practices
- **When a session has images** → call Cataloguer to cross-check what you see

Not every session needs all three. Not every session needs any. The Anvil uses judgment.

### Calling a facet agent

Spawn via the Task tool with:
- The agent's prompt file as context
- A Lens extract of relevant fragments (from `lens_extract.py`)
- The Anvil's current draft — what you want checked/enriched
- Any relevant images
- A specific ask: "check this inventory against these photos" or "what connections am I missing?"

The agent writes its output to `temp/<session>/` alongside the Anvil's working files. The Anvil reads the output, incorporates what's useful, discards what isn't.

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
└── researcher-notes.md   # facet agent output (optional)
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

## Open Questions

1. **Agent model**: Sonnet (cheaper, faster) or Opus (better judgment)? Cataloguer might be fine on Sonnet. Weaver probably needs Opus.
2. **Researcher scope**: How much web searching per session? Maybe only called when specifically needed.
3. **Pattern promotion**: When the Weaver surfaces patterns, how do they become `<pattern>` WM items?
