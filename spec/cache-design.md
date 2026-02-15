# Anthropic Prompt Caching — Design

## Status: Deferred
Not yet implemented. Revisit when stable WM content (pins, plans, secrets, patterns) is substantial enough to exceed the 4096-token minimum on Opus, or if we switch to Sonnet (1024-token minimum).

## What it is
Anthropic's API supports `cache_control` breakpoints on content blocks. Everything up to and including the breakpoint is cached server-side. Cached input tokens cost ~90% less. Cache TTL is 5 minutes (refreshed on each hit), with an optional 1-hour TTL.

## The constraint
Minimum cacheable prefix on Opus 4.6: **4096 tokens**. Below that, breakpoints are silently ignored — no error, no extra cost, just no caching.

- Wake context: ~1058 tokens
- Ambient: ~785 tokens
- Combined: ~1843 tokens — below 4096

Need ~2200+ tokens of stable WM to hit the threshold. On Sonnet 4.5 the minimum is 1024 — our static content alone would cache.

## Caching strategy (2 breakpoints)

**Breakpoint 1 — System (1h TTL):**
Activation (wake-context.md) + optional image context. `cache_control: {"type": "ephemeral"}`.

**Breakpoint 2 — User prefix (5min TTL):**
Ambient + stable WM as the first text block in the user message. `cache_control: {"type": "ephemeral"}`.

**Not cached:** Volatile WM, recall, conversation, current time, image, hot context.

## WM classification

| Type | Classification | Reasoning |
|------|---------------|-----------|
| pin | STABLE | 336h half-life, changes only on explicit action |
| secret | STABLE | Never decays |
| plan | STABLE | No decay until resolved |
| pattern | STABLE | 168h half-life |
| thought | VOLATILE | 12h half-life, drops out of selection |
| feeling | VOLATILE | 2h half-life, constantly refreshed |
| desc | VOLATILE | Superseded on image turns |

Stable items sorted by database ID for deterministic byte-identical output (cache hit requirement).

## Implementation summary

### assemble.py
- Add `STABLE_WM_TYPES = frozenset({"secret", "pin", "plan", "pattern"})`
- Split `WakePackage.working_memory` → `stable_wm` + `volatile_wm`
- Add `render_prompt()` returning structured content blocks with cache_control
- Keep `render_system()` / `render_user()` for CLI fallback

### claude_client.py
- `send()` accepts `str` or `list[dict]` for both user_message and system_prompt
- `body["system"]` becomes array of content blocks (not plain string)
- Image block placed AFTER cached prefix in user content
- Parse cache usage from response: `cache_creation_input_tokens`, `cache_read_input_tokens`

### orchestrator.py
- Call `render_prompt()` instead of `render_system()` + `render_user()`
- Log cache metrics

## Image handling
Images placed after cache breakpoint in user content. System cache may miss on image↔non-image transitions (rare, acceptable).

## API details
- Endpoint: `https://api.anthropic.com/v1/messages` (same)
- Prompt caching is GA — no beta header needed
- Up to 4 breakpoints per request
- Cache write cost: 125% of base (5min TTL) or 200% (1h TTL)
- Cache read cost: 10% of base
