# Syntax Guide For Memory-Aware Behavior

Use these tags when you want memory and planning behavior to be explicit and reliable.

| Syntax | What The System Does | How Claude Should Use It |
| --- | --- | --- |
| `<plan> ... </plan>` | Creates or updates an explicit open plan. Due time and recurrence may be parsed from the text. | Use for real commitments you want kept in active memory. |
| `<plan>done ...</plan>` | Marks the best-matching open plan as done. | Use when a plan is completed. Include key words from the original plan. |
| `<plan>cancel ...</plan>` / `<plan>skip ...</plan>` / `<plan>drop ...</plan>` | Marks the best-matching open plan as cancelled/archived. | Use when a plan should stop being active. |
| Text ending with `<secret>` | Marks memory as secret-tagged content. Secret-tagged data is preserved for memory/scoring and treated as secret context. | Append for sensitive facts, internal state, or private commitments. |
| `<secret> ... </secret>` | Canonical wrapped secret span. Secret-tagged context may be normalized into this format. | Use when you want explicit secret boundaries in text. |
| `<thought> ... </thought>` | Thought-track marker. User-facing rendering may collapse this by default. | Use for internal reasoning, private reflective notes, or side tracks you do not want shown by default. |
| Plain planning language without tags (for example: "we should...", "need to...", "later...") | May be stored as an inferred uncertain plan candidate with lower weight. Can decay and auto-archive if not reinforced. | Use for tentative ideas only. Promote to `<plan>` when it becomes a commitment. |

## Time Hints Claude Can Put Inside `<plan>`

The parser can use plain time language inside plan text, including:
- absolute date/time (ISO-like text)
- relative time ("in 2 hours", "in 3 days")
- day words ("today", "tomorrow")
- weekday references ("Monday")
- time-of-day phrases ("at 9am", "evening", "tonight")
- recurrence ("daily", "weekly", "monthly", "yearly", "every Monday")

## Practical Rules

- If it must persist as a commitment, always wrap it in `<plan>`.
- Put one clear action per `<plan>` whenever possible.
- Include due or recurrence words when timing matters.
- Use done/cancel plan tags to close items cleanly.
- For sensitive details, use secret tags. If you still want Mono to see context, write a separate visible hint outside secret tags.
- Assume `<thought>` can be hidden by default in user output.
- Unknown tags are treated as normal text unless another parser is added.

## Memory Commands

When deeper context is needed, use `./memoryctl` commands instead of assuming hidden state.

- Read first: `recent`, `search`, `thread`, `plans`, `get`
- Write intentionally: `note-add`, `note-archive`, `plan-add`, `plan-close`, `feedback-add`
- Inferred/tentative planning data lives in a separate experimental DB and is not surfaced by default unless requested.
