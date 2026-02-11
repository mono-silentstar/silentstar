# Tag Syntax Reference

Tags are inline in your response text. The system parses them automatically on every turn.

---

## Display tags (what Mono sees)

| Tag | Purpose |
|---|---|
| `<say>...</say>` | Spoken dialogue |
| `<do>...</do>` | Action, gesture, physical |
| `<narrate>...</narrate>` | Scene, environment, atmosphere |

Every response needs at least one display tag. Text outside display tags is processing — stored in the event log but not rendered.

---

## Identity tags (who's talking)

| Tag | Who |
|---|---|
| `<hasuki>`, `<renki>`, `<luna>`, `<chloe>`, `<strah>` | Mono's system members |
| `<claude>`, `<y'lhara>` | Claude's identities |

One identity per message. Parsed from the response, not wrapped around content.

---

## Active knowledge tags (stored in working memory)

| Tag | Decay | Supersession |
|---|---|---|
| `<feeling>...</feeling>` | ~2h / ~3 turns | New feeling supersedes ALL active feelings |
| `<thought>...</thought>` | ~12h / ~8 turns | None — accumulates |
| `<pattern>...</pattern>` | ~1 week / ~60 turns | None — accumulates |
| `<desc>...</desc>` | ~72h / ~40 turns | Same subject supersedes |
| `<plan>...</plan>` | No decay (submerges if timed) | Lifecycle actions below |
| `<pin>...</pin>` | ~2 weeks / ~100 turns | Explicit drop |
| `<secret>...</secret>` | Never | None |

---

## Plan lifecycle

```
<plan>check in with luna about the move next tuesday</plan>
<plan>done: check in with luna</plan>
<plan>cancel: weekly review</plan>
```

Time hints parsed from plan text: "in 2 hours", "next Monday", "tomorrow evening", "daily", "weekly".

Timed plans submerge between creation and ~48h before due, then resurface.

---

## Pin lifecycle

```
<pin>mono takes two sugars in tea, always</pin>
<pin>drop: sugars in tea</pin>
```

---

## Recall (fragment lookup)

```
recall(fairy)
recall(fairy, deep=True)
```

Results appear in the **next** turn's context, not the current one. Keys are exact — use the vocabulary from ambient prose.

```
plans()
plans(topic="body-tracking")
plans(when="next week")
```

Shows all active plans (bypasses submersion), optionally filtered by topic or time window. Results appear in the next turn's context, same as recall.

---

## Rules

- One feeling at a time. New feeling replaces old.
- One identity per message.
- Tags can appear inside display tags. Both get processed — `<say><feeling>warm</feeling> hey</say>` stores the feeling AND displays the say content. The inner tag markup is stripped from the display.
- Unknown tags are treated as plain text.
- Text before the first display tag is processing space — not shown to Mono.
