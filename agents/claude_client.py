"""
Claude Client — the bridge between our system and Claude.

Currently uses Claude CLI (`claude -p`). Designed so the transport
can be swapped to API later without changing anything upstream.

The interface is simple:
  send(prompt) → response text
  send(prompt, image_path) → response text (multimodal)

Everything else (assembly, parsing, ingestion) doesn't care
how the prompt gets to Claude and back.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ClaudeConfig:
    """Configuration for the Claude client."""
    cli_path: str = "claude"          # path to claude binary
    model: str | None = None          # override model (None = default)
    timeout_seconds: int = 300        # max wait for response
    max_tokens: int | None = None     # max response tokens (None = default)


@dataclass
class ClaudeResponse:
    """What came back from Claude."""
    text: str                         # the response text
    success: bool                     # did it work
    error: str | None = None          # error message if not


def send(
    prompt: str,
    config: ClaudeConfig | None = None,
    image_path: Path | None = None,
) -> ClaudeResponse:
    """
    Send a prompt to Claude and get a response.

    This is the one function the rest of the system calls.
    Everything else is implementation detail.
    """
    c = config or ClaudeConfig()

    try:
        return _send_cli(prompt, c, image_path)
    except Exception as e:
        return ClaudeResponse(
            text="",
            success=False,
            error=str(e),
        )


def _send_cli(
    prompt: str,
    config: ClaudeConfig,
    image_path: Path | None = None,
) -> ClaudeResponse:
    """Send via Claude CLI (claude -p)."""

    cmd = [config.cli_path, "-p"]

    # Add model override if specified
    if config.model:
        cmd.extend(["--model", config.model])

    # Add max tokens if specified
    if config.max_tokens:
        cmd.extend(["--max-tokens", str(config.max_tokens)])

    # Output as JSON for cleaner parsing
    cmd.extend(["--output-format", "json"])

    # For long prompts, write to a temp file and pass via stdin
    # to avoid argument length limits
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        delete=True,
        encoding="utf-8",
    ) as f:
        f.write(prompt)
        f.flush()

        # If image is present, we need to handle it differently
        # For now, the prompt already contains the desc instruction
        # and the image path. Claude CLI doesn't natively support
        # passing images, so we note this as a TODO for API migration.
        if image_path and image_path.exists():
            # Append image reference to prompt
            # TODO: When switching to API, send as multimodal content block
            prompt += f"\n\n[Attached image: {image_path}]"
            f.seek(0)
            f.write(prompt)
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

    # Parse JSON output
    response_text = result.stdout.strip()
    try:
        parsed = json.loads(response_text)
        # Claude CLI JSON output has a "result" field
        if isinstance(parsed, dict) and "result" in parsed:
            return ClaudeResponse(text=parsed["result"], success=True)
        # Fallback: use raw output
        return ClaudeResponse(text=response_text, success=True)
    except json.JSONDecodeError:
        # Not JSON — use raw output
        return ClaudeResponse(text=response_text, success=True)


# --- Future API implementation ---
#
# def _send_api(
#     prompt: str,
#     config: ClaudeConfig,
#     image_path: Path | None = None,
# ) -> ClaudeResponse:
#     """Send via Anthropic API. Swap in when ready."""
#     import anthropic
#
#     client = anthropic.Anthropic()
#
#     content = [{"type": "text", "text": prompt}]
#
#     if image_path and image_path.exists():
#         import base64
#         image_data = base64.standard_b64encode(
#             image_path.read_bytes()
#         ).decode("utf-8")
#         media_type = _guess_media_type(image_path)
#         content.insert(0, {
#             "type": "image",
#             "source": {
#                 "type": "base64",
#                 "media_type": media_type,
#                 "data": image_data,
#             },
#         })
#
#     response = client.messages.create(
#         model=config.model or "claude-sonnet-4-5-20250929",
#         max_tokens=config.max_tokens or 4096,
#         messages=[{"role": "user", "content": content}],
#     )
#
#     text = response.content[0].text
#     return ClaudeResponse(text=text, success=True)
