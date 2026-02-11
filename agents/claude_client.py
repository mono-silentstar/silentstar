"""
Claude Client — the bridge between our system and Claude.

Two transports:
  - API (default): Anthropic Messages API via raw HTTP (urllib).
    No third-party dependencies. Requires api_key in config
    or ANTHROPIC_API_KEY env var.
  - CLI (fallback): claude -p. Carries Claude Code's system prompt,
    which fights with the wake context. Use only if API isn't available.

The interface is simple:
  send(user_message, system_prompt) → response text
  send(user_message, system_prompt, image_path) → response text (multimodal)

Everything else (assembly, parsing, ingestion) doesn't care
how the prompt gets to Claude and back.
"""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


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

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"


def _send_api(
    user_message: str,
    config: ClaudeConfig,
    image_path: Path | None = None,
    system_prompt: str | None = None,
) -> ClaudeResponse:
    """Send via Anthropic Messages API using raw HTTP. No third-party deps."""
    api_key = config.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No API key. Set ANTHROPIC_API_KEY or api_key in config."
        )

    # Build user content — text, optionally with image
    content: list[dict] = []

    if image_path and image_path.exists():
        raw_bytes = image_path.read_bytes()
        media_type = _guess_media_type(image_path)

        # Anthropic API limit: 5MB per image
        if len(raw_bytes) > _IMAGE_MAX_BYTES:
            try:
                raw_bytes, media_type = _compress_image(raw_bytes, media_type)
            except Exception:
                pass  # compression failed, check size below

        if len(raw_bytes) <= _IMAGE_MAX_BYTES:
            image_data = base64.standard_b64encode(raw_bytes).decode("utf-8")
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": image_data,
                },
            })
        # else: image too large even after compression — skip it, send text only

    content.append({"type": "text", "text": user_message})

    # Build the request body
    body: dict = {
        "model": config.model,
        "max_tokens": config.max_tokens,
        "messages": [{"role": "user", "content": content}],
    }

    if system_prompt:
        body["system"] = system_prompt

    data = json.dumps(body).encode("utf-8")

    req = Request(
        ANTHROPIC_API_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=config.timeout_seconds) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Anthropic API error {e.code}: {error_body}")
    except URLError as e:
        raise RuntimeError(f"Network error: {e.reason}")

    # Extract text from response content blocks
    text = ""
    for block in result.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")

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


# --- Image compression ---

_IMAGE_MAX_BYTES = 5 * 1024 * 1024 * 3 // 4  # API limit is 5MB base64, so ~3.75MB raw


def _compress_image(
    raw_bytes: bytes, media_type: str
) -> tuple[bytes, str]:
    """Compress an image to fit within the API size limit."""
    from PIL import Image

    img = Image.open(io.BytesIO(raw_bytes))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # Try JPEG at decreasing quality levels
    for quality in (85, 70, 50):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        if buf.tell() <= _IMAGE_MAX_BYTES:
            return buf.getvalue(), "image/jpeg"

    # Still too large — scale down
    for scale in (0.75, 0.5, 0.35):
        scaled = img.resize(
            (int(img.width * scale), int(img.height * scale)),
            Image.LANCZOS,
        )
        buf = io.BytesIO()
        scaled.save(buf, format="JPEG", quality=70)
        if buf.tell() <= _IMAGE_MAX_BYTES:
            return buf.getvalue(), "image/jpeg"

    # Last resort — return whatever we have
    buf = io.BytesIO()
    img.resize(
        (int(img.width * 0.25), int(img.height * 0.25)),
        Image.LANCZOS,
    ).save(buf, format="JPEG", quality=60)
    return buf.getvalue(), "image/jpeg"


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

        with open(f.name, "r", encoding="utf-8") as stdin_file:
            result = subprocess.run(
                cmd,
                stdin=stdin_file,
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
