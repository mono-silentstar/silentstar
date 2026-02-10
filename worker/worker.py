"""
silentstar worker — the bridge between web and brain.

Runs locally. Polls the remote PHP frontend for jobs. When a job arrives,
runs it through the orchestrator and posts the result back. That's it.

The intelligence lives in the backend. This is just the courier.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# Add project root to path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.orchestrator import turn, TurnConfig, TurnResult
from agents.claude_client import ClaudeConfig


@dataclass
class WorkerConfig:
    web_base_url: str
    bridge_secret: str
    worker_name: str
    db_path: Path
    wake_context_path: Path
    wake_context_image_path: Path
    ambient_path: Path
    image_archive_dir: Path
    heartbeat_interval: float = 2.0
    claim_interval: float = 1.2
    request_timeout: float = 20.0
    claude_timeout: int = 300
    claude_model: str | None = None
    claude_transport: str = "api"     # "api" (default) or "cli"
    claude_api_key: str | None = None # if None, uses ANTHROPIC_API_KEY env var
    verbose: bool = True


def load_config(path: Path) -> WorkerConfig:
    if not path.is_file():
        raise RuntimeError(f"Config not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    def resolve(val: str, default: Path) -> Path:
        if not val:
            return default
        p = Path(val).expanduser()
        if not p.is_absolute():
            p = (REPO_ROOT / p).resolve()
        return p

    return WorkerConfig(
        web_base_url=raw.get("web_base_url", "").rstrip("/"),
        bridge_secret=raw.get("bridge_secret", ""),
        worker_name=raw.get("worker_name", "silentstar-worker"),
        db_path=resolve(raw.get("db_path", ""), REPO_ROOT / "memory.sqlite"),
        wake_context_path=resolve(
            raw.get("wake_context_path", ""),
            REPO_ROOT / "mdfiles" / "claude" / "wake-context.md",
        ),
        wake_context_image_path=resolve(
            raw.get("wake_context_image_path", ""),
            REPO_ROOT / "mdfiles" / "claude" / "wake-context-image.md",
        ),
        ambient_path=resolve(raw.get("ambient_path", ""), REPO_ROOT / "ambient.md"),
        image_archive_dir=resolve(
            raw.get("image_archive_dir", ""), REPO_ROOT / "data" / "img-dump"
        ),
        heartbeat_interval=float(raw.get("heartbeat_interval", 2.0)),
        claim_interval=float(raw.get("claim_interval", 1.2)),
        request_timeout=float(raw.get("request_timeout", 20.0)),
        claude_timeout=int(raw.get("claude_timeout", 300)),
        claude_model=raw.get("claude_model"),
        claude_transport=raw.get("claude_transport", "api"),
        claude_api_key=raw.get("claude_api_key"),
        verbose=bool(raw.get("verbose", True)),
    )


class Bridge:
    """HTTP client for the PHP bridge endpoints."""

    def __init__(self, cfg: WorkerConfig):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({
            "X-Bridge-Secret": cfg.bridge_secret,
            "Content-Type": "application/json",
            "User-Agent": "silentstar-worker/2.0",
        })

    def _url(self, endpoint: str) -> str:
        return f"{self.cfg.web_base_url}/api/{endpoint}"

    def heartbeat(self, busy: bool = False) -> None:
        self.session.post(
            self._url("bridge_heartbeat.php"),
            data=json.dumps({"busy": busy, "worker": self.cfg.worker_name}),
            timeout=self.cfg.request_timeout,
        ).raise_for_status()

    def claim(self) -> dict[str, Any] | None:
        r = self.session.post(
            self._url("bridge_claim.php"),
            data=json.dumps({"worker": self.cfg.worker_name}),
            timeout=self.cfg.request_timeout,
        )
        r.raise_for_status()
        body = r.json()
        if not body.get("ok"):
            raise RuntimeError(f"Claim failed: {body}")
        return body.get("job")

    def download_upload(self, job_id: str, dest_dir: Path) -> Path | None:
        r = self.session.get(
            self._url("bridge_download.php"),
            params={"id": job_id},
            timeout=self.cfg.request_timeout,
            stream=True,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()

        dest_dir.mkdir(parents=True, exist_ok=True)
        # Extract filename from Content-Disposition or generate one
        cd = r.headers.get("Content-Disposition", "")
        name = "image.bin"
        if 'filename="' in cd:
            name = cd.split('filename="')[1].rstrip('"')

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        local_path = dest_dir / f"{ts}__{job_id}__{name}"

        with local_path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)

        return local_path

    def complete(
        self,
        job_id: str,
        status: str = "done",
        display: list[dict] | None = None,
        actor: str | None = None,
        reply_text: str | None = None,
        error_message: str | None = None,
        turn_id: str | None = None,
    ) -> None:
        payload = {
            "id": job_id,
            "status": status,
            "display": display or [],
            "actor": actor or "claude",
            "reply_text": reply_text,
            "error_message": error_message,
            "turn_id": turn_id,
        }
        self.session.post(
            self._url("bridge_complete.php"),
            data=json.dumps(payload),
            timeout=self.cfg.request_timeout,
        ).raise_for_status()


def extract_display_spans(response_text: str) -> list[dict]:
    """Extract say/do/narrate spans from Claude's raw response.
    Returns structured display data for the frontend."""
    import re

    spans = []
    pattern = re.compile(
        r"<(say|do|narrate)>(.*?)</\1>",
        re.DOTALL,
    )
    for match in pattern.finditer(response_text):
        tag = match.group(1)
        content = match.group(2).strip()
        if content:
            spans.append({"tag": tag, "content": content})

    return spans


class Worker:
    def __init__(self, cfg: WorkerConfig):
        self.cfg = cfg
        self.bridge = Bridge(cfg)

    def log(self, msg: str) -> None:
        if self.cfg.verbose:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] {msg}", flush=True)

    def _heartbeat_safe(self, busy: bool = False) -> None:
        try:
            self.bridge.heartbeat(busy)
        except Exception as e:
            self.log(f"heartbeat failed: {e}")

    def process_job(self, job: dict[str, Any]) -> None:
        job_id = str(job.get("id", ""))
        if not job_id:
            raise RuntimeError("Job missing ID")

        message = str(job.get("message", ""))
        actor = str(job.get("actor", "mono")) or "mono"
        tags = job.get("tags", [])
        has_upload = bool(job.get("has_upload"))

        self.log(f"processing {job_id}")

        # Download image if present
        image_path: str | None = None
        if has_upload:
            local = self.bridge.download_upload(job_id, self.cfg.image_archive_dir)
            if local:
                image_path = str(local)
                self.log(f"downloaded image: {local.name}")

        # Build config for the orchestrator
        cc = ClaudeConfig(
            timeout_seconds=self.cfg.claude_timeout,
            transport=self.cfg.claude_transport,
        )
        if self.cfg.claude_model:
            cc.model = self.cfg.claude_model
        if self.cfg.claude_api_key:
            cc.api_key = self.cfg.claude_api_key

        turn_config = TurnConfig(
            db_path=self.cfg.db_path,
            wake_context_path=self.cfg.wake_context_path,
            wake_context_image_path=self.cfg.wake_context_image_path,
            ambient_path=self.cfg.ambient_path,
            claude_config=cc,
        )

        # Run the turn
        result: TurnResult = turn(
            config=turn_config,
            message=message,
            actor=actor,
            tags=tags if tags else None,
            image_path=image_path,
        )

        if not result.success:
            self.bridge.complete(
                job_id=job_id,
                status="error",
                error_message=result.error or "turn failed",
            )
            self.log(f"job {job_id} failed: {result.error}")
            return

        # Debug: show what Claude actually said
        raw = result.response_text
        self.log(f"raw response ({len(raw)} chars): {raw[:300]}{'...' if len(raw) > 300 else ''}")

        # Extract display spans from raw response
        display = extract_display_spans(result.response_text)

        self.bridge.complete(
            job_id=job_id,
            status="done",
            display=display,
            actor=result.actor or "claude",
            reply_text=result.response_text,
            turn_id=str(result.turn),
        )

        self.log(f"job {job_id} done (turn {result.turn}, {len(display)} display spans)")

    def run(self) -> None:
        self.log("worker starting")
        self.log(f"bridge: {self.cfg.web_base_url}")
        self.log(f"db: {self.cfg.db_path}")
        self.log(f"wake: {self.cfg.wake_context_path}")

        last_hb = 0.0

        while True:
            now = time.monotonic()
            if now - last_hb >= self.cfg.heartbeat_interval:
                self._heartbeat_safe(False)
                last_hb = now

            try:
                job = self.bridge.claim()
            except Exception as e:
                self.log(f"claim failed: {e}")
                time.sleep(self.cfg.claim_interval)
                continue

            if job is None:
                time.sleep(self.cfg.claim_interval)
                continue

            self._heartbeat_safe(True)
            try:
                self.process_job(job)
            except Exception as e:
                job_id = str(job.get("id", ""))
                self.log(f"job {job_id} error: {e}")
                if job_id:
                    try:
                        self.bridge.complete(
                            job_id=job_id,
                            status="error",
                            error_message=str(e),
                        )
                    except Exception as ce:
                        self.log(f"failed to report error: {ce}")
            finally:
                self._heartbeat_safe(False)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="silentstar bridge worker")
    parser.add_argument(
        "--config",
        default=str(REPO_ROOT / "worker" / "config.json"),
        help="Path to worker config JSON",
    )
    args = parser.parse_args()

    cfg = load_config(Path(args.config).expanduser().resolve())

    if not cfg.web_base_url:
        print("ERROR: web_base_url is required in config", file=sys.stderr)
        return 1
    if not cfg.bridge_secret:
        print("ERROR: bridge_secret is required in config", file=sys.stderr)
        return 1

    worker = Worker(cfg)
    worker.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
