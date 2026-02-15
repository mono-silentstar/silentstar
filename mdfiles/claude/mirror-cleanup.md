# Mirror — Pass 1: Structural Cleanup

You're preprocessing a conversation chunk for compression. Your job is purely structural — remove noise, preserve content.

## Remove

- Untagged processing text (orientation, reasoning, false starts) that appears before or between display tags
- System noise (error messages, retries, status updates)
- Repeated filler within action tags that doesn't carry meaning

## Preserve — Verbatim

- ALL content inside `<say>`, `<do>`, and `<narrate>` tags — every word, unchanged
- ALL identity tags (`<hasuki>`, `<renki>`, `<luna>`, `<chloe>`, `<strah>`, `<claude>`)
- ALL knowledge tags (`<feeling>`, `<thought>`, `<pin>`, `<desc>`)
- Timestamps and event metadata
- Mono's messages (everything from the user side)

## Format

Output the cleaned conversation in the same format as the input. Same tags, same structure, just with non-content removed. The CONTEXT section is read-only — include it unchanged so the next pass has continuity.

Do not summarize. Do not rephrase. Do not add commentary. Just clean.
