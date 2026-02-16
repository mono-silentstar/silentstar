# lens_extract.py — Spec

The read side of the Lens. Queries the Gem, follows edges, outputs formatted .md.

## Usage

```bash
# Single key — fragment + everything connected via edges
python lens_extract.py wardrobe

# Multi-key intersection — fragments where paths converge
python lens_extract.py wardrobe jirai exhibitionist

# All fragments
python lens_extract.py --all

# Working memory state
python lens_extract.py --wm

# Mirror summaries
python lens_extract.py --summaries

# FTS5 full-text search across all tables
python lens_extract.py --search "fairy"

# Search specific table only
python lens_extract.py --search "fairy" --type fragments
python lens_extract.py --search "fairy" --type events
python lens_extract.py --search "fairy" --type wm

# Output to file instead of stdout
python lens_extract.py wardrobe -o temp/lens/wardrobe.md
```

## Single Key Query

Given `lens_extract.py wardrobe`:

1. Load fragment `wardrobe` (all tiers)
2. Follow all edges from/to `wardrobe` (one hop)
3. Load connected fragments (all tiers)
4. Output the root fragment first, then connected fragments, then edges

## Multi-Key Intersection

Given `lens_extract.py wardrobe jirai exhibitionist`:

1. For each key, find the fragment and all connected fragments (one hop)
2. Find fragments that appear in multiple result sets (the intersection)
3. Include the root keys even if they don't intersect
4. Output: root fragments, then intersection fragments, then relevant edges

## Output Format

```markdown
# Lens Extract — wardrobe (Feb 13, 2026)

## [wardrobe]
Ambient: The wardrobe is a system, not a collection...
Recognition: Six registers, each with formulas and colour rules...
Inventory:
- fairy: [item list]
- jirai: [item list]
- ...

## [fairy]
Ambient: White ethereal softness...
Recognition: ...
Inventory: ...

## [jirai]
Ambient: Black-and-pink damaged sweetness...
Recognition: ...
Inventory: ...

## Edges
wardrobe → fairy (domain-inventory)
wardrobe → jirai (domain-inventory)
fairy → jirai (shared-aesthetic)
```

Empty tiers are omitted (don't print `Recognition:` if there's nothing there).

## Working Memory Output (`--wm`)

```markdown
# Working Memory — Active (Feb 13, 2026)

## Feelings (1 active)
- [id 8] warm and a little protective (2026-02-11)

## Thoughts (4 active)
- [id 1] Hasuki opened the job search door... (2026-02-10)
- [id 5] Recall system confirmed functional... (2026-02-11)
- ...

## Pins (0 active)
## Plans (0 active)
```

## Config

Reads DB path from `worker/config.json` (same as other tools), or accepts `--db path/to/memory.sqlite`.

## Implementation Notes

- Pure read-only. Never writes to DB.
- Edge traversal is one hop by default. Could add `--depth N` later.
- Uses `wake/schema.py` connect() for DB access.
- No Claude API calls. No agent. Just SQL queries and formatting.
