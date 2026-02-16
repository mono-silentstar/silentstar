"""
File Ingest — reading files into the system.

Two modes, auto-detected or manually chosen:

  FRAGMENT mode (structured markdown):
    Files with clear headers, sections, key-value structure.
    Each section becomes a fragment tier. Detects ambient vs
    recognition vs inventory from header depth and content density.

  EVENT mode (loose text):
    Brain dumps, notes, conversation logs. Stored as events
    tagged with source info. The maintenance agent compiles later.

Detection heuristic: if the file has markdown headers (##) and
structured sections, it's probably fragment material. Otherwise
it's event material.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .runner import Agent, AgentResult


@dataclass
class FileSpec:
    """A file to ingest with optional overrides."""
    path: Path
    mode: str | None = None       # "fragment", "event", or None for auto
    actor: str | None = None      # who provided this file
    tags: list[str] = field(default_factory=list)
    fragment_key: str | None = None  # override key for fragment mode


class FileIngestAgent(Agent):
    """Ingest one or more files into the database."""

    name = "file-ingest"
    run_type = "manual"

    def __init__(self, db_path: Path, files: list[FileSpec]):
        super().__init__(db_path)
        self.files = files

    def run(self, conn: sqlite3.Connection) -> AgentResult:
        result = AgentResult()

        for spec in self.files:
            if not spec.path.exists():
                result.errors.append(f"File not found: {spec.path}")
                continue

            try:
                text = spec.path.read_text(encoding="utf-8")
            except Exception as e:
                result.errors.append(f"Failed to read {spec.path}: {e}")
                continue

            mode = spec.mode or _detect_mode(text, spec.path)

            if mode == "fragment":
                r = _ingest_as_fragments(conn, text, spec)
                result.fragments_created += r.fragments_created
                result.fragments_updated += r.fragments_updated
                result.notes.extend(r.notes)
            else:
                r = _ingest_as_events(conn, text, spec)
                result.events_created += r.events_created
                result.notes.extend(r.notes)

        return result


class BulkFileIngestAgent(Agent):
    """Ingest all files in a directory."""

    name = "bulk-file-ingest"
    run_type = "bootstrap"

    def __init__(
        self,
        db_path: Path,
        directory: Path,
        pattern: str = "*.md",
        mode: str | None = None,
        actor: str | None = None,
    ):
        super().__init__(db_path)
        self.directory = directory
        self.pattern = pattern
        self.default_mode = mode
        self.actor = actor

    def run(self, conn: sqlite3.Connection) -> AgentResult:
        result = AgentResult()

        files = sorted(self.directory.glob(self.pattern))
        if not files:
            result.notes.append(f"No files matching {self.pattern} in {self.directory}")
            return result

        for path in files:
            try:
                text = path.read_text(encoding="utf-8")
            except Exception as e:
                result.errors.append(f"Failed to read {path}: {e}")
                continue

            spec = FileSpec(
                path=path,
                mode=self.default_mode,
                actor=self.actor,
            )

            mode = spec.mode or _detect_mode(text, path)

            if mode == "fragment":
                r = _ingest_as_fragments(conn, text, spec)
                result.fragments_created += r.fragments_created
                result.fragments_updated += r.fragments_updated
                result.notes.extend(r.notes)
            else:
                r = _ingest_as_events(conn, text, spec)
                result.events_created += r.events_created
                result.notes.extend(r.notes)

        return result


# --- Detection ---

# Headers, bullet lists, and structured content suggest fragment mode
_HEADER_RE = re.compile(r"^#{1,3}\s+.+$", re.MULTILINE)
_SECTION_RE = re.compile(r"^---+\s*$", re.MULTILINE)


def _detect_mode(text: str, path: Path) -> str:
    """Guess whether a file should be ingested as fragments or events."""
    suffix = path.suffix.lower()

    # Plain text files → events
    if suffix == ".txt":
        return "event"

    # Markdown: check structure
    headers = _HEADER_RE.findall(text)
    sections = _SECTION_RE.findall(text)

    # Lots of headers or section breaks → fragment material
    if len(headers) >= 3 or len(sections) >= 2:
        return "fragment"

    # Short file with no structure → event
    if len(text) < 500:
        return "event"

    # Default: if it's markdown with some structure, try fragments
    if headers:
        return "fragment"

    return "event"


# --- Fragment ingestion ---

@dataclass
class _Section:
    """A parsed section from a structured markdown file."""
    title: str
    content: str
    depth: int       # header level (1, 2, 3)


def _parse_markdown_sections(text: str) -> list[_Section]:
    """Split markdown into sections by headers."""
    lines = text.split("\n")
    sections = []
    current_title = ""
    current_depth = 0
    current_lines: list[str] = []

    for line in lines:
        header_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if header_match:
            # Save previous section
            if current_lines or current_title:
                content = "\n".join(current_lines).strip()
                if content:
                    sections.append(_Section(
                        title=current_title,
                        content=content,
                        depth=current_depth,
                    ))

            current_depth = len(header_match.group(1))
            current_title = header_match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Don't forget the last section
    content = "\n".join(current_lines).strip()
    if content:
        sections.append(_Section(
            title=current_title,
            content=content,
            depth=current_depth,
        ))

    return sections


def _title_to_key(title: str) -> str:
    """Convert a section title to a fragment key."""
    key = title.lower().strip()
    key = re.sub(r"[^a-z0-9\s-]", "", key)
    key = re.sub(r"\s+", "-", key)
    key = key.strip("-")
    return key


def _ingest_as_fragments(
    conn: sqlite3.Connection,
    text: str,
    spec: FileSpec,
) -> AgentResult:
    """Parse structured markdown into fragments."""
    result = AgentResult()
    now = datetime.now(timezone.utc).isoformat()

    sections = _parse_markdown_sections(text)

    if not sections:
        # No sections — treat as a single fragment if key is provided
        if spec.fragment_key:
            _upsert_fragment(conn, spec.fragment_key, text, None, now)
            result.fragments_created += 1
            result.notes.append(f"Single fragment: {spec.fragment_key}")
        else:
            # Fall back to event mode
            return _ingest_as_events(conn, text, spec)
        return result

    # If only one key is specified, use the whole file for that key
    if spec.fragment_key and len(sections) <= 3:
        ambient = ""
        recognition = ""
        inventory = ""

        for section in sections:
            if section.depth <= 1 or len(sections) == 1:
                # Top-level or only section → recognition
                recognition = section.content
            elif section.depth == 2:
                recognition += "\n\n" + section.content
            else:
                inventory += "\n\n" + section.content

        # First paragraph of recognition as ambient
        paragraphs = recognition.strip().split("\n\n")
        if paragraphs:
            ambient = paragraphs[0][:300]  # cap ambient at ~300 chars

        _upsert_fragment(conn, spec.fragment_key, ambient.strip(),
                         recognition.strip(), now, inventory.strip() or None)
        result.fragments_created += 1
        result.notes.append(f"Fragment: {spec.fragment_key} from {spec.path.name}")
        return result

    # Multiple sections → each becomes a fragment
    for section in sections:
        if not section.title:
            continue

        key = _title_to_key(section.title)
        if not key:
            continue

        # Depth heuristic:
        # - Short content (< 200 chars) → ambient only
        # - Medium content → ambient + recognition
        # - Long content → all three tiers
        content = section.content
        paragraphs = content.split("\n\n")

        ambient = paragraphs[0][:300] if paragraphs else content[:300]
        recognition = content if len(content) > 200 else None
        inventory = None

        if len(content) > 1000:
            # Long section: first paragraph ambient, full as recognition,
            # and we'd want inventory from sub-sections but that's for
            # the maintenance agent to compile
            recognition = content

        _upsert_fragment(conn, key, ambient, recognition, now, inventory)
        result.fragments_created += 1
        result.notes.append(f"Fragment: {key}")

    # Also log an event for traceability
    _log_source_event(conn, spec, f"Fragment ingestion from {spec.path.name}", now)
    result.events_created += 1

    return result


def _upsert_fragment(
    conn: sqlite3.Connection,
    key: str,
    ambient: str,
    recognition: str | None,
    now: str,
    inventory: str | None = None,
) -> None:
    """Insert or update a fragment."""
    existing = conn.execute(
        "SELECT key FROM fragments WHERE key = ?", (key,)
    ).fetchone()

    if existing:
        conn.execute("""
            UPDATE fragments
            SET ambient = ?, recognition = ?, inventory = ?, updated_at = ?
            WHERE key = ?
        """, (ambient, recognition, inventory, now, key))
    else:
        conn.execute("""
            INSERT INTO fragments (key, ambient, recognition, inventory, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (key, ambient, recognition, inventory, now, now))


# --- Event ingestion ---

# For long files, chunk into sections to avoid single massive events
MAX_EVENT_CHARS = 2000


def _ingest_as_events(
    conn: sqlite3.Connection,
    text: str,
    spec: FileSpec,
) -> AgentResult:
    """Store file content as events, chunked if needed."""
    result = AgentResult()
    now = datetime.now(timezone.utc).isoformat()

    source_tag = f"file:{spec.path.name}"
    actor = spec.actor

    # Try to split on natural boundaries
    chunks = _chunk_text(text)

    for i, chunk in enumerate(chunks):
        cursor = conn.execute(
            "INSERT INTO ev.events (ts, content, actor) VALUES (?, ?, ?)",
            (now, chunk, actor),
        )
        event_id = cursor.lastrowid

        # Tag with source info
        conn.execute(
            "INSERT OR IGNORE INTO ev.event_tags (event_id, tag) VALUES (?, ?)",
            (event_id, source_tag),
        )

        # Add any user-specified tags
        for tag in spec.tags:
            conn.execute(
                "INSERT OR IGNORE INTO ev.event_tags (event_id, tag) VALUES (?, ?)",
                (event_id, tag),
            )

        result.events_created += 1

    result.notes.append(
        f"Events from {spec.path.name}: {len(chunks)} chunk(s)"
    )
    return result


def _chunk_text(text: str) -> list[str]:
    """Split text into chunks on natural boundaries."""
    if len(text) <= MAX_EVENT_CHARS:
        return [text.strip()] if text.strip() else []

    chunks = []

    # Try splitting on double newlines (paragraphs)
    paragraphs = text.split("\n\n")
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 > MAX_EVENT_CHARS:
            if current.strip():
                chunks.append(current.strip())
            current = para
        else:
            current = current + "\n\n" + para if current else para

    if current.strip():
        chunks.append(current.strip())

    # If any chunk is still too long, hard-split on newlines
    final = []
    for chunk in chunks:
        if len(chunk) <= MAX_EVENT_CHARS:
            final.append(chunk)
        else:
            lines = chunk.split("\n")
            current = ""
            for line in lines:
                if len(current) + len(line) + 1 > MAX_EVENT_CHARS:
                    if current.strip():
                        final.append(current.strip())
                    current = line
                else:
                    current = current + "\n" + line if current else line
            if current.strip():
                final.append(current.strip())

    return final


def _log_source_event(
    conn: sqlite3.Connection,
    spec: FileSpec,
    note: str,
    now: str,
) -> None:
    """Log a source event for traceability."""
    cursor = conn.execute(
        "INSERT INTO ev.events (ts, content, actor) VALUES (?, ?, ?)",
        (now, note, spec.actor or "system"),
    )
    event_id = cursor.lastrowid
    conn.execute(
        "INSERT OR IGNORE INTO ev.event_tags (event_id, tag) VALUES (?, ?)",
        (event_id, f"file:{spec.path.name}"),
    )
