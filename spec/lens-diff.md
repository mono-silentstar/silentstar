# lens_diff.py — Spec

Preview tool for Loom drafts. Parses a draft .md (same format as lens_extract output), diffs against current DB state, and shows what would change. **Never writes to the DB.** The Anvil reads the diff, exercises judgment, and commits directly.

## Usage

```bash
# Show what a draft would change
python lens_diff.py temp/loom/wardrobe-merged.md

# Explicit DB path
python lens_diff.py draft.md --db path/to/memory.sqlite
```

## Input Format

Same as lens_extract.py output:

```markdown
## [wardrobe]
Ambient: The wardrobe is a system, not a collection...
Recognition: Six registers, each with formulas...
Inventory:
- fairy: [items]
- jirai: [items]

## [new-fragment]
Ambient: Something that didn't exist before...
Recognition: ...

## Edges
wardrobe → fairy (domain-inventory)
wardrobe → new-fragment (builds-toward)
REMOVE: wardrobe → old-fragment (stale-relation)
```

## Parsing Rules

- `## [key]` starts a fragment block
- `Ambient:`, `Recognition:`, `Inventory:` are tier markers. Everything until the next marker or next `##` is that tier's content.
- `## Edges` starts the edge section
- `source → target (relation)` marks an edge addition
- `REMOVE: source → target` marks an edge removal (relation optional — matches by source+target)
- Fragments not mentioned in the draft are **left unchanged** (not deleted)
- Tiers not mentioned in a fragment block are **left unchanged** (not cleared)

## Diff Output

```
FRAGMENTS:
  [wardrobe]     UPDATE  ambient (changed), inventory (changed)
  [new-fragment]  CREATE  ambient, recognition
  [fairy]         (unchanged)

EDGES:
  + wardrobe → new-fragment (builds-toward)
  - wardrobe → old-fragment (stale-relation)
  = wardrobe → fairy (domain-inventory)   (unchanged)
  ! bad-dir → fairy (relation)  (NOT FOUND — exists as fairy → bad-dir)

Summary: 1 create, 1 update | 1 edge add, 1 edge remove
```

The `!` marker warns about REMOVE directives that point in the wrong direction — the edge exists but with source and target swapped.

## How the Anvil Uses This

1. Loom agents write drafts to `temp/loom/`
2. Anvil merges drafts into `temp/loom/<key>-merged.md`
3. Anvil runs `python lens_diff.py temp/loom/<key>-merged.md` to preview changes
4. Anvil reviews the diff, discusses with Mono
5. Anvil writes directly to the Gem using SQL — with judgment on every change

The diff is a preview, not an instruction. The Anvil may accept, modify, or reject any proposed change.

## What It Does NOT Do

- **Write to the database.** Ever. Read-only.
- **Delete fragments.** It can show that a draft would create or update, but the Anvil decides.
- **Touch working memory.** WM changes go through the ingest pipeline.
- **Touch events.** The event log is append-only and untouchable.

## Config

Same as lens_extract.py — reads DB path from `worker/config.json` or `--db` flag.
