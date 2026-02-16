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
  send(user_message, image_path=...) → response text (single image)
  send(user_message, image_paths=[...]) → response text (multiple images)

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
from typing import Callable
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
    image_paths: list[Path] | None = None,
) -> ClaudeResponse:
    """
    Send a message to Claude and get a response.

    system_prompt: the wake context (activation). Becomes the API system
    parameter — no hidden instructions, no fighting with a CLI prompt.

    user_message: everything else — ambient, working memory, conversation,
    the current message. What I wake up inside.

    image_path: single image (backward compat).
    image_paths: multiple images. If both provided, image_paths wins.

    This is the one function the rest of the system calls.
    """
    c = config or ClaudeConfig()

    # Normalize to list
    images = image_paths or ([image_path] if image_path else [])

    try:
        if c.transport == "api":
            return _send_api(user_message, c, images, system_prompt)
        else:
            # CLI fallback — system prompt gets folded into the user message
            full = user_message
            if system_prompt:
                full = system_prompt + "\n\n---\n\n" + user_message
            return _send_cli(full, c, images[0] if images else None)
    except Exception as e:
        return ClaudeResponse(
            text="",
            success=False,
            error=str(e),
        )


def send_streaming(
    user_message: str,
    config: ClaudeConfig | None = None,
    image_path: Path | None = None,
    system_prompt: str | None = None,
    on_chunk: Callable[[str], None] | None = None,
    image_paths: list[Path] | None = None,
) -> ClaudeResponse:
    """
    Send a message to Claude with streaming response.

    Like send(), but streams the response via SSE. Calls on_chunk(text)
    for each text delta as it arrives. Returns the complete ClaudeResponse
    at the end.

    Falls back to non-streaming send() if streaming fails.
    """
    c = config or ClaudeConfig()

    # Normalize to list
    images = image_paths or ([image_path] if image_path else [])

    try:
        if c.transport != "api":
            return send(user_message, c, system_prompt=system_prompt, image_paths=images)
        return _send_api_streaming(user_message, c, images, system_prompt, on_chunk)
    except Exception:
        # Fallback to non-streaming on any error
        return send(user_message, c, system_prompt=system_prompt, image_paths=images)


# --- API transport (default) ---

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"


def _encode_image(image_path: Path) -> dict | None:
    """Encode a single image for the API, compressing if needed. Returns content block or None."""
    if not image_path.exists():
        return None

    raw_bytes = image_path.read_bytes()
    media_type = _guess_media_type(image_path)

    if len(raw_bytes) > _IMAGE_MAX_BYTES:
        try:
            raw_bytes, media_type = _compress_image(raw_bytes, media_type)
        except Exception:
            pass  # compression failed, check size below

    if len(raw_bytes) > _IMAGE_MAX_BYTES:
        return None  # too large even after compression

    image_data = base64.standard_b64encode(raw_bytes).decode("utf-8")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": image_data,
        },
    }


def _send_api(
    user_message: str,
    config: ClaudeConfig,
    image_paths: list[Path] | None = None,
    system_prompt: str | None = None,
) -> ClaudeResponse:
    """Send via Anthropic Messages API using raw HTTP. No third-party deps."""
    api_key = config.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No API key. Set ANTHROPIC_API_KEY or api_key in config."
        )

    # Build user content — text, optionally with images
    content: list[dict] = []

    for img_path in (image_paths or []):
        block = _encode_image(img_path)
        if block:
            content.append(block)

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


def _send_api_streaming(
    user_message: str,
    config: ClaudeConfig,
    image_paths: list[Path] | None = None,
    system_prompt: str | None = None,
    on_chunk: Callable[[str], None] | None = None,
) -> ClaudeResponse:
    """Stream via Anthropic Messages API with SSE."""
    api_key = config.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("No API key.")

    # Build content (same as _send_api)
    content: list[dict] = []

    for img_path in (image_paths or []):
        block = _encode_image(img_path)
        if block:
            content.append(block)

    content.append({"type": "text", "text": user_message})

    body: dict = {
        "model": config.model,
        "max_tokens": config.max_tokens,
        "messages": [{"role": "user", "content": content}],
        "stream": True,
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

    full_text = ""

    try:
        with urlopen(req, timeout=config.timeout_seconds) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n\r")

                if not line.startswith("data: "):
                    continue

                payload = line[6:]  # strip "data: "
                if payload.strip() == "[DONE]":
                    break

                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type", "")

                if etype == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            full_text += text
                            if on_chunk:
                                on_chunk(text)

                elif etype == "message_stop":
                    break

                elif etype == "error":
                    err = event.get("error", {})
                    raise RuntimeError(
                        f"Stream error: {err.get('type', 'unknown')}: {err.get('message', '')}"
                    )

    except HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Anthropic API error {e.code}: {error_body}")
    except URLError as e:
        raise RuntimeError(f"Network error: {e.reason}")

    return ClaudeResponse(text=full_text, success=True)


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
