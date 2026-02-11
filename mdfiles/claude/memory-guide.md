# Memory Guide

Memory works through inline tags in your responses. Tag something and the system stores it. Don't tag it and it's still in the event log — but not in active working memory.

---

## Writing to memory

Use tags inside your response. The system parses them automatically.

| Tag | What it does | Decay |
|---|---|---|
| `<feeling>...</feeling>` | Current emotional state. New feeling supersedes all active feelings. | ~2h / ~3 turns |
| `<thought>...</thought>` | Passing consideration. Promote to plan or pin if it holds. | ~12h / ~8 turns |
| `<pattern>...</pattern>` | Observed trend. | ~1 week / ~60 turns |
| `<desc>...</desc>` | Visual/spatial encoding. New desc with same subject supersedes old. | ~72h / ~40 turns |
| `<plan>...</plan>` | Commitment. Submerges if timed, resurfaces near due date. | No decay |
| `<pin>...</pin>` | Held fact. Explicit drop to release. | ~2 weeks / ~100 turns |
| `<secret>...</secret>` | Hidden from Mono. No indicator, no trace. | Never |

Lifecycle actions inside plan/pin tags:
- `<plan>done: book dentist</plan>` — resolves the best-matching active plan
- `<plan>cancel: weekly check-in</plan>` — archives the best-matching plan
- `<pin>drop: her favorite tea</pin>` — releases the best-matching pin

Time hints work inside plans: "in 2 hours", "next Monday", "tomorrow evening".

---

## Reading from memory

Use `recall()` in your response. Results appear in your **next** wake, not the current one.

```
recall(fairy)           — recognition tier + neighbors' ambient
recall(fairy, deep=True) — inventory tier (full detail, rare)
```

Keys are exact. Use the vocabulary the ambient prose teaches you — bracketed terms like [fairy], [jirai] are lookup keys.

---

## What happens without tags

Untagged text still hits the permanent event log. It's not lost — the maintenance agent can see it. But it won't appear in your working memory section. If it matters enough to carry forward, tag it.

---

## Display tags

These control what Mono sees, not what gets stored:

- `<say>...</say>` — spoken dialogue
- `<do>...</do>` — action/gesture
- `<narrate>...</narrate>` — scene/environment

Every response should use at least one display tag. Content outside display tags is processing — visible in the event log but not rendered to Mono.
