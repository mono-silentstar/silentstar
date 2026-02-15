# Mirror — Pass 2: Modality Compression

You're compressing the physical/action layer of a conversation chunk. The dialogue layer stays intact.

## Rules

**Preserve 100%** — all `<say>` content, word-for-word. Do not edit, summarize, or rephrase dialogue.

**Compress** — `<do>` and `<narrate>` content. Replace moment-by-moment choreography with what it meant emotionally. Keep the arc, lose the positions.

Examples of compression:
- 20 lines of intimate choreography → "moved from tentative touch to full trust, Claude leading with patience, Hasuki surrendering incrementally"
- 5 lines of room cleaning actions → "sorted through the mess systematically, breaking the task into passes"
- Physical positioning details → the emotional register they conveyed

## What to Keep in DO/NARRATE

- Emotional transitions (when the mood shifts)
- Power dynamics (who leads, who follows, who initiates)
- Consent choreography (nonverbal questions and answers)
- Physical milestones (first touch, escalation points, resolution)
- Context that changes meaning of dialogue

## Format

Output the conversation with `<say>` tags unchanged and `<do>`/`<narrate>` tags containing compressed arc summaries. Keep timestamps and metadata. The CONTEXT section is read-only — include it unchanged.
