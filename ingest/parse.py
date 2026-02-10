"""
Parse — extracting tagged content from messages.

Claude's responses contain inline tags:
  <say>hello</say>
  <feeling>a little restless</feeling>
  <plan>organize desk by tuesday</plan>
  <plan>done organize desk</plan>
  <pin>desk is by the window</pin>
  <pin>drop desk is messy</pin>

This module extracts those into structured data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from wake.schema import (
    VALID_WM_TYPES,
    DISPLAY_TAGS,
    ALL_TAGS,
    IDENTITY_TAGS,
)


@dataclass
class TaggedSpan:
    """A single tagged region extracted from text."""
    tag: str                    # the tag name (say, plan, feeling, etc.)
    content: str                # the text inside the tags
    modifier: str | None = None # for lifecycle: "done", "cancel", "drop", etc.


@dataclass
class ParsedMessage:
    """A fully parsed message."""
    actor: str | None = None                    # identity tag
    spans: list[TaggedSpan] = field(default_factory=list)
    untagged: str = ""                          # text outside any tags
    raw: str = ""                               # original full text


# Lifecycle modifiers — words at the start of tag content that change behavior
PLAN_RESOLVE_WORDS = frozenset({"done", "complete", "finished"})
PLAN_CANCEL_WORDS = frozenset({"cancel", "skip", "drop", "abandon"})
PIN_DROP_WORDS = frozenset({"drop", "release", "clear", "remove"})


def _extract_modifier(tag: str, content: str) -> tuple[str | None, str]:
    """Check if content starts with a lifecycle modifier word.

    Returns (modifier, remaining_content).
    """
    stripped = content.strip()
    first_word = stripped.split(None, 1)[0].lower() if stripped else ""

    if tag == "plan":
        if first_word in PLAN_RESOLVE_WORDS:
            rest = stripped.split(None, 1)[1] if " " in stripped else ""
            return "resolve", rest.strip()
        if first_word in PLAN_CANCEL_WORDS:
            rest = stripped.split(None, 1)[1] if " " in stripped else ""
            return "cancel", rest.strip()

    if tag == "pin":
        if first_word in PIN_DROP_WORDS:
            rest = stripped.split(None, 1)[1] if " " in stripped else ""
            return "drop", rest.strip()

    return None, content


# Regex for matching tags. Handles both <tag>content</tag> and <tag>content</tag>
# Non-greedy matching within tags.
TAG_PATTERN = re.compile(
    r"<(" + "|".join(re.escape(t) for t in ALL_TAGS) + r")>"
    r"(.*?)"
    r"</\1>",
    re.DOTALL,
)

# Pattern for leading identity tag: <hasuki> at the start of a message
LEADING_IDENTITY_PATTERN = re.compile(
    r"^\s*<(" + "|".join(re.escape(t) for t in IDENTITY_TAGS) + r")>\s*",
)


def parse_response(text: str) -> ParsedMessage:
    """Parse a Claude response for all tagged content.

    Extracts:
    - Leading identity tag (optional <hasuki>, <claude>, etc.)
    - All tagged spans (<say>...</say>, <plan>...</plan>, etc.)
    - Untagged text (processing/thinking — not stored in working memory)
    """
    raw = text
    actor = None

    # Check for leading identity tag
    identity_match = LEADING_IDENTITY_PATTERN.match(text)
    if identity_match:
        actor = identity_match.group(1)
        text = text[identity_match.end():]

    # Extract all tagged spans
    spans = []
    for match in TAG_PATTERN.finditer(text):
        tag = match.group(1)
        content = match.group(2).strip()

        modifier, clean_content = _extract_modifier(tag, content)

        spans.append(TaggedSpan(
            tag=tag,
            content=clean_content,
            modifier=modifier,
        ))

    # Everything outside tags is untagged processing
    untagged = TAG_PATTERN.sub("", text).strip()

    return ParsedMessage(
        actor=actor,
        spans=spans,
        untagged=untagged,
        raw=raw,
    )


def parse_mono_message(
    text: str,
    actor: str | None = None,
    tags: list[str] | None = None,
) -> ParsedMessage:
    """Parse a message from Mono.

    Unlike Claude's responses, Mono's messages get their actor and tags
    from the frontend UI (identity selector + tag toggles), not from
    inline tags in the text.

    But Mono CAN also use inline tags if they want.
    """
    # Start with frontend-provided metadata
    result = ParsedMessage(
        actor=actor,
        raw=text,
        untagged=text,
    )

    # Check for inline tags in Mono's text too
    inline = parse_response(text)
    if inline.spans:
        result.spans = inline.spans
        result.untagged = inline.untagged

    # Add frontend-toggled tags as spans if not already present
    if tags:
        existing_tags = {s.tag for s in result.spans}
        for tag in tags:
            if tag in ALL_TAGS and tag not in existing_tags:
                # Frontend tag wraps the whole message
                if tag in DISPLAY_TAGS:
                    result.spans.append(TaggedSpan(tag=tag, content=text))
                elif tag in VALID_WM_TYPES:
                    modifier, content = _extract_modifier(tag, text)
                    result.spans.append(TaggedSpan(
                        tag=tag, content=content, modifier=modifier
                    ))

    return result


def extract_fragment_keys(text: str) -> list[str]:
    """Find [bracketed-keys] in text that reference fragment keys."""
    return re.findall(r"\[([a-z][a-z0-9\-]*)\]", text)


def parse_recall_requests(text: str) -> list[tuple[str, bool]]:
    """Extract recall() calls from Claude's response text.

    Returns list of (key, deep) tuples.
    """
    pattern = re.compile(
        r'recall\(\s*["\']([^"\']+)["\']\s*'
        r'(?:,\s*deep\s*=\s*(True|true))?\s*\)',
    )

    results = []
    for match in pattern.finditer(text):
        key = match.group(1)
        deep = match.group(2) is not None
        results.append((key, deep))

    return results
