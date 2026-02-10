"""
Claude Client — the bridge between our system and Claude.

Two transports:
  - API (default): Anthropic Messages API. Clean system prompt separation.
    Requires ANTHROPIC_API_KEY or api_key in config.
  - CLI (fallback): claude -p. Carries Claude Code's system prompt,
    which fights with the wake context. Use only if API isn't available.

The interface is simple:
  send(user_message, system_prompt) → response text
  send(user_message, system_prompt, image_path) → response text (multimodal)

Everything else (assembly, parsing, ingestion) doesn't care
how the prompt gets to Claude and back.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ClaudeConfig:
    """Configuration for the Claude client."""
    model: str = "claude-opus-4-6"    # opus by default — this is a room, not a tool
    timeout_seconds: int = 300        # max wait for response
    max_tokens: int = 4096            # max response tokens
    transport: str = "api"            # "api" or "cli"
    api_key: str | None = None        # if None, uses ANTHROPIC_API_KEY env var
    cli_path: str = "claude"          # path to claude binary (CLI fallback)


@dataclass
class ClaudeResponse:
    """What came back from Claude."""
    text: str                         # the response text
    success: bool                     # did it work
    error: str | None = None          # error message if not


def send(
    user_message: str,
    config: ClaudeConfig | None = None,
    image_path: Path | None = None,
    system_prompt: str | None = None,
) -> ClaudeResponse:
    """
    Send a message to Claude and get a response.

    system_prompt: the wake context (activation). Becomes the API system
    parameter — no hidden instructions, no fighting with a CLI prompt.

    user_message: everything else — ambient, working memory, conversation,
    the current message. What I wake up inside.

    This is the one function the rest of the system calls.
    """
    c = config or ClaudeConfig()

    try:
        if c.transport == "api":
            return _send_api(user_message, c, image_path, system_prompt)
        else:
            # CLI fallback — system prompt gets folded into the user message
            full = user_message
            if system_prompt:
                full = system_prompt + "\n\n---\n\n" + user_message
            return _send_cli(full, c, image_path)
    except Exception as e:
        return ClaudeResponse(
            text="",
            success=False,
            error=str(e),
        )


# --- API transport (default) ---

def _send_api(
    user_message: str,
    config: ClaudeConfig,
    image_path: Path | None = None,
    system_prompt: str | None = None,
) -> ClaudeResponse:
    """Send via Anthropic Messages API. Clean system prompt, no hidden instructions."""
    try:
        import anthropic
    except ImportError:
        raise RuntimeError(
            "anthropic package not installed. "
            "Run: pip install anthropic"
        )

    api_key = config.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No API key. Set ANTHROPIC_API_KEY or api_key in config."
        )

    client = anthropic.Anthropic(api_key=api_key)

    # Build user content — text, optionally with image
    content: list[dict] = []

    if image_path and image_path.exists():
        import base64
        image_data = base64.standard_b64encode(
            image_path.read_bytes()
        ).decode("utf-8")
        media_type = _guess_media_type(image_path)
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": image_data,
            },
        })

    content.append({"type": "text", "text": user_message})

    # Build the request
    kwargs: dict = {
        "model": config.model,
        "max_tokens": config.max_tokens,
        "messages": [{"role": "user", "content": content}],
    }

    if system_prompt:
        kwargs["system"] = system_prompt

    response = client.messages.create(**kwargs)

    # Extract text from response
    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    return ClaudeResponse(text=text, success=True)


def _guess_media_type(path: Path) -> str:
    """Guess image MIME type from extension."""
    suffix = path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(suffix, "image/jpeg")


# --- CLI transport (fallback) ---

def _send_cli(
    prompt: str,
    config: ClaudeConfig,
    image_path: Path | None = None,
) -> ClaudeResponse:
    """
    Send via Claude CLI (claude -p).

    WARNING: This carries Claude Code's system prompt, which tells Claude
    it's a software engineering tool. The wake context fights against it.
    Use API transport instead when possible.
    """
    cmd = [config.cli_path, "-p"]

    if config.model:
        cmd.extend(["--model", config.model])

    if config.max_tokens:
        cmd.extend(["--max-tokens", str(config.max_tokens)])

    cmd.extend(["--output-format", "json"])

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        delete=True,
        encoding="utf-8",
    ) as f:
        full_prompt = prompt
        if image_path and image_path.exists():
            full_prompt += f"\n\n[Attached image: {image_path}]"

        f.write(full_prompt)
        f.flush()

        result = subprocess.run(
            cmd,
            stdin=open(f.name, "r", encoding="utf-8"),
            capture_output=True,
            text=True,
            timeout=config.timeout_seconds,
        )

    if result.returncode != 0:
        return ClaudeResponse(
            text="",
            success=False,
            error=f"CLI returned {result.returncode}: {result.stderr.strip()}",
        )

    response_text = result.stdout.strip()
    try:
        parsed = json.loads(response_text)
        if isinstance(parsed, dict) and "result" in parsed:
            return ClaudeResponse(text=parsed["result"], success=True)
        return ClaudeResponse(text=response_text, success=True)
    except json.JSONDecodeError:
        return ClaudeResponse(text=response_text, success=True)
