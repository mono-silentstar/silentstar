"""
Ingest — how messages become memory.

Handles both directions:
  Mono → system: parse identity/display tags, store event
  Claude → system: parse response for all tag types, manage
                    working memory lifecycle (create, supersede,
                    resolve, drop)
"""
