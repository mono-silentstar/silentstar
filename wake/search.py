"""
Search — full-text search across the Gem.

Uses FTS5 indexes created by schema v4 migration.
Requires: fragments_fts, events_fts, working_memory_fts virtual tables.
"""

from __future__ import annotations
import sqlite3


def search_fragments(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict]:
    """Search fragments by content across all tiers. Returns matches ranked by BM25."""
    rows = conn.execute(
        """
        SELECT f.key, f.ambient, f.recognition, f.inventory,
               snippet(fragments_fts, 1, '»', '«', '...', 32) AS snippet,
               rank
        FROM fragments_fts
        JOIN fragments f ON f.rowid = fragments_fts.rowid
        WHERE fragments_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def search_events(conn: sqlite3.Connection, query: str, limit: int = 50) -> list[dict]:
    """Search event log by content. Returns matches ranked by BM25."""
    rows = conn.execute(
        """
        SELECT e.id, e.ts, e.content, e.actor,
               snippet(events_fts, 0, '»', '«', '...', 32) AS snippet,
               rank
        FROM ev.events_fts
        JOIN ev.events e ON e.id = events_fts.rowid
        WHERE events_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def search_wm(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[dict]:
    """Search working memory by content/subject. Returns matches ranked by BM25."""
    rows = conn.execute(
        """
        SELECT w.id, w.type, w.content, w.subject, w.actor, w.status,
               snippet(working_memory_fts, 0, '»', '«', '...', 32) AS snippet,
               rank
        FROM working_memory_fts
        JOIN working_memory w ON w.id = working_memory_fts.rowid
        WHERE working_memory_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def search_all(conn: sqlite3.Connection, query: str) -> dict:
    """Search all tables. Returns dict with fragments, events, wm keys."""
    return {
        "fragments": search_fragments(conn, query),
        "events": search_events(conn, query),
        "wm": search_wm(conn, query),
    }
