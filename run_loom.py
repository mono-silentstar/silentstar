#!/usr/bin/env python3
"""
run_loom.py — Loom runner CLI.

Orchestrates the four Loom facet agents (Cataloguer, Weaver, Researcher,
Questioner) in parallel. Each agent reviews a draft and produces markdown notes.

Agents don't write to the DB — they produce {agent}-notes.md files
alongside the draft.

Usage:
    python run_loom.py temp/wardrobe/inventory.md
    python run_loom.py temp/wardrobe/inventory.md --agents cataloguer,weaver
    python run_loom.py temp/wardrobe/inventory.md --images temp/wardrobe/pics/
    python run_loom.py temp/wardrobe/inventory.md --context wardrobe,fairy
    python run_loom.py temp/wardrobe/inventory.md --ask "what am I missing?"
    python run_loom.py temp/wardrobe/inventory.md --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.claude_client import ClaudeConfig, ClaudeResponse, send
from lens_extract import extract_multi, extract_single
from wake.schema import connect

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

AGENTS: dict[str, dict] = {
    "cataloguer": {
        "prompt_file": "mdfiles/claude/loom-cataloguer.md",
        "model": "claude-sonnet-4-5-20250929",
        "receives_images": True,
    },
    "weaver": {
        "prompt_file": "mdfiles/claude/loom-weaver.md",
        "model": "claude-opus-4-6",
        "receives_images": False,
    },
    "researcher": {
        "prompt_file": "mdfiles/claude/loom-researcher.md",
        "model": "claude-sonnet-4-5-20250929",
        "receives_images": False,
    },
    "questioner": {
        "prompt_file": "mdfiles/claude/loom-questioner.md",
        "model": "claude-opus-4-6",
        "receives_images": False,
    },
}


def _load_config() -> dict:
    """Load worker/config.json or return empty dict."""
    config_path = REPO_ROOT / "worker" / "config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {}


def _load_db_path() -> Path:
    """Resolve DB path from worker/config.json or fallback."""
    cfg = _load_config()
    return Path(cfg.get("db_path", "data/silentstar.sqlite"))


def _load_api_key() -> str | None:
    """Resolve API key from worker/config.json or env var."""
    cfg = _load_config()
    return cfg.get("claude_api_key") or os.environ.get("ANTHROPIC_API_KEY")


def _find_bracketed_keys(text: str) -> list[str]:
    """Extract [bracketed keys] from draft text."""
    return re.findall(r"\[([a-zA-Z0-9_-]+)\]", text)


def _list_images(images_dir: Path) -> list[Path]:
    """List image files in a directory."""
    if not images_dir.is_dir():
        return []
    return sorted(
        p for p in images_dir.iterdir()
        if p.suffix.lower() in IMAGE_EXTENSIONS
    )


def _get_lens_context(keys: list[str]) -> str:
    """Query the Gem via lens_extract for the given keys."""
    db_path = _load_db_path()
    if not db_path.exists():
        return "No context available. (database not found)"

    conn = connect(db_path)
    try:
        if len(keys) == 1:
            return extract_single(conn, keys[0])
        else:
            return extract_multi(conn, keys)
    finally:
        conn.close()


def _build_prompt(
    agent_name: str,
    agent_cfg: dict,
    draft_text: str,
    lens_context: str,
    ask: str | None,
    image_files: list[Path],
) -> str:
    """Assemble the full prompt for one agent."""
    # Load prompt file
    prompt_path = REPO_ROOT / agent_cfg["prompt_file"]
    if not prompt_path.exists():
        return ""  # caller checks for this
    prompt_content = prompt_path.read_text(encoding="utf-8").strip()

    parts = [
        f"# {agent_name.title()} — Loom Facet Agent",
        "",
        prompt_content,
        "",
        "---",
        "",
        "## Context from the Gem",
        "",
        lens_context or "No context available.",
        "",
        "---",
        "",
        "## Draft Under Review",
        "",
        draft_text,
        "",
        "---",
        "",
    ]

    if ask:
        parts.extend([
            "## Ask",
            "",
            ask,
            "",
            "---",
            "",
        ])

    if image_files and agent_cfg.get("receives_images"):
        parts.extend([
            "## Available Images",
            "",
        ])
        for img in image_files:
            parts.append(f"- {img.name}")
        parts.extend(["", "---", ""])

    parts.append("Please review the draft above and provide your analysis.")

    return "\n".join(parts)


def _run_agent(
    agent_name: str,
    agent_cfg: dict,
    prompt: str,
    image_files: list[Path],
    output_dir: Path,
) -> tuple[str, bool, str]:
    """Call Claude API for one agent. Returns (agent_name, success, message)."""
    config = ClaudeConfig(
        model=agent_cfg["model"],
        max_tokens=4096,
        api_key=_load_api_key(),
    )

    # Cataloguer gets all images
    images: list[Path] = []
    if agent_cfg.get("receives_images") and image_files:
        images = image_files

    resp: ClaudeResponse = send(
        user_message=prompt,
        config=config,
        image_paths=images if images else None,
    )

    if not resp.success:
        return (agent_name, False, f"API error: {resp.error}")

    # Write output
    out_path = output_dir / f"{agent_name}-notes.md"
    out_path.write_text(resp.text + "\n", encoding="utf-8")
    return (agent_name, True, f"Written to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Loom runner — orchestrate facet agents on a draft"
    )
    parser.add_argument("draft", help="Path to draft .md file")
    parser.add_argument(
        "--agents",
        type=str,
        default=None,
        help="Comma-separated agent names (default: all four)",
    )
    parser.add_argument(
        "--images",
        type=str,
        default=None,
        help="Directory containing images for the draft",
    )
    parser.add_argument(
        "--context",
        type=str,
        default=None,
        help="Comma-separated Gem keys to pull context for (overrides auto-detect)",
    )
    parser.add_argument(
        "--ask",
        type=str,
        default=None,
        help="Question to include for agents",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print prompts and config without calling API",
    )

    args = parser.parse_args()

    # Validate draft
    draft_path = Path(args.draft)
    if not draft_path.exists():
        print(f"Error: draft file not found: {draft_path}", file=sys.stderr)
        sys.exit(1)

    draft_text = draft_path.read_text(encoding="utf-8").strip()
    output_dir = draft_path.parent

    # Select agents
    if args.agents:
        selected = [a.strip().lower() for a in args.agents.split(",")]
        invalid = [a for a in selected if a not in AGENTS]
        if invalid:
            print(f"Error: unknown agent(s): {', '.join(invalid)}", file=sys.stderr)
            print(f"Available: {', '.join(AGENTS.keys())}", file=sys.stderr)
            sys.exit(1)
    else:
        selected = list(AGENTS.keys())

    if not selected:
        parser.print_help()
        sys.exit(1)

    # Check prompt files exist
    runnable = []
    for name in selected:
        prompt_path = REPO_ROOT / AGENTS[name]["prompt_file"]
        if not prompt_path.exists():
            print(f"Warning: prompt file missing for {name}: {prompt_path}", file=sys.stderr)
        else:
            runnable.append(name)

    if not runnable:
        print("Error: no agents have prompt files", file=sys.stderr)
        sys.exit(1)

    # Resolve context keys
    if args.context:
        keys = [k.strip() for k in args.context.split(",")]
    else:
        keys = _find_bracketed_keys(draft_text)
        # Optional FTS5 fallback if no keys found
        if not keys:
            try:
                from wake.search import search_fragments
                db_path = _load_db_path()
                if db_path.exists():
                    conn = connect(db_path)
                    try:
                        stem = draft_path.stem.replace("-", " ").replace("_", " ")
                        hits = search_fragments(conn, stem, limit=5)
                        keys = [h["key"] for h in hits if h.get("key")]
                    finally:
                        conn.close()
            except ImportError:
                pass

    # Get lens context
    if keys:
        print(f"Context keys: {', '.join(keys)}", file=sys.stderr)
        lens_context = _get_lens_context(keys)
    else:
        lens_context = "No context available."

    # Collect images
    image_files: list[Path] = []
    if args.images:
        images_dir = Path(args.images)
        if images_dir.is_dir():
            image_files = _list_images(images_dir)
            print(f"Images: {len(image_files)} found", file=sys.stderr)
        else:
            print(f"Warning: images directory not found: {images_dir}", file=sys.stderr)

    # Build prompts
    prompts: dict[str, str] = {}
    for name in runnable:
        prompts[name] = _build_prompt(
            name, AGENTS[name], draft_text, lens_context, args.ask, image_files
        )

    # Dry run
    if args.dry_run:
        for name in runnable:
            prompt = prompts[name]
            print(f"\n{'=' * 60}")
            print(f"Agent: {name}")
            print(f"Model: {AGENTS[name]['model']}")
            print(f"Output: {output_dir / f'{name}-notes.md'}")
            print(f"Prompt ({len(prompt)} chars):")
            print("-" * 40)
            if len(prompt) > 500:
                print(prompt[:500] + "...")
            else:
                print(prompt)
            print()
        return

    # Run agents in parallel
    print(f"\nRunning {len(runnable)} agent(s)...", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(
                _run_agent, name, AGENTS[name], prompts[name], image_files, output_dir
            ): name
            for name in runnable
        }

        for future in as_completed(futures):
            agent_name, success, message = future.result()
            status = "ok" if success else "FAILED"
            print(f"  [{status}] {agent_name}: {message}", file=sys.stderr)

    print("\nDone.", file=sys.stderr)


if __name__ == "__main__":
    main()
