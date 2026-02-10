"""
silentstar cron worker — filesystem-based job processing.

Runs via cron every minute. Internally loops for ~55 seconds with a short
sleep, processing any queued jobs from the shared data/jobs/ directory.
PHP writes job files, this worker reads and processes them directly.

No HTTP bridge, no polling endpoints — just shared filesystem.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import signal
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add project root to path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.orchestrator import turn, TurnConfig, TurnResult
from agents.claude_client import ClaudeConfig

# How long the worker loops before exiting (cron restarts it)
MAX_RUN_SECONDS = 55
# Sleep between job checks when idle
IDLE_SLEEP = 1.0
# Sleep between job checks when signal file was absent
POLL_SLEEP = 2.0


@dataclass
class CronConfig:
    jobs_dir: Path
    state_dir: Path
    uploads_dir: Path
    history_file: Path
    image_archive_dir: Path
    db_path: Path
    wake_context_path: Path
    wake_context_image_path: Path
    ambient_path: Path
    claude_timeout: int = 90
    claude_model: str | None = None
    claude_api_key: str | None = None
    verbose: bool = True


def load_config(path: Path) -> CronConfig:
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

    return CronConfig(
        jobs_dir=resolve(raw.get("jobs_dir", ""), REPO_ROOT / "data" / "jobs"),
        state_dir=resolve(raw.get("state_dir", ""), REPO_ROOT / "data" / "state"),
        uploads_dir=resolve(raw.get("uploads_dir", ""), REPO_ROOT / "data" / "uploads_tmp"),
        history_file=resolve(raw.get("history_file", ""), REPO_ROOT / "data" / "history.jsonl"),
        image_archive_dir=resolve(
            raw.get("image_archive_dir", ""), REPO_ROOT / "data" / "img-dump"
        ),
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
        claude_timeout=int(raw.get("claude_timeout", 90)),
        claude_model=raw.get("claude_model"),
        claude_api_key=raw.get("claude_api_key"),
        verbose=bool(raw.get("verbose", True)),
    )


def log(msg: str, verbose: bool = True) -> None:
    if verbose:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {msg}", flush=True)


def extract_display_spans(response_text: str) -> list[dict]:
    """Extract say/do/narrate spans from Claude's raw response."""
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


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def write_json_atomic(path: Path, data: dict) -> None:
    """Write JSON atomically using tmp + rename (matches PHP ss_write_json_atomic)."""
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    encoded = json.dumps(data, indent=2, ensure_ascii=False)
    tmp.write_text(encoded + "\n", encoding="utf-8")
    tmp.rename(path)


def read_json_file(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def list_jobs(jobs_dir: Path) -> list[dict]:
    """List all job files, sorted by created_at ascending."""
    if not jobs_dir.is_dir():
        return []
    jobs = []
    for p in sorted(jobs_dir.glob("*.json")):
        if p.name.endswith(".tmp"):
            continue
        job = read_json_file(p)
        if job and "id" in job:
            jobs.append(job)
    jobs.sort(key=lambda j: j.get("created_at", ""))
    return jobs


def find_queued_job(jobs_dir: Path) -> dict | None:
    for job in list_jobs(jobs_dir):
        if job.get("status") == "queued":
            return job
    return None


def update_job(jobs_dir: Path, job_id: str, mutator) -> dict | None:
    path = jobs_dir / f"{job_id}.json"
    job = read_json_file(path)
    if job is None:
        return None
    updated = mutator(job)
    if not isinstance(updated, dict):
        return None
    updated["id"] = job_id
    updated["updated_at"] = now_iso()
    write_json_atomic(path, updated)
    return updated


def claim_job(jobs_dir: Path, job: dict) -> dict | None:
    """Claim a queued job by setting it to running."""
    job_id = str(job["id"])

    def mutator(row: dict) -> dict:
        if row.get("status") != "queued":
            return row  # already claimed by someone else
        row["status"] = "running"
        row["claimed_at"] = now_iso()
        row["worker"] = "cron-worker"
        return row

    claimed = update_job(jobs_dir, job_id, mutator)
    if claimed and claimed.get("status") == "running":
        return claimed
    return None


def complete_job(
    jobs_dir: Path,
    job_id: str,
    status: str = "done",
    display: list[dict] | None = None,
    actor: str | None = None,
    reply_text: str | None = None,
    error_message: str | None = None,
    turn_id: str | None = None,
) -> dict | None:
    """Mark a job as complete (done or error)."""
    def mutator(row: dict) -> dict:
        row["status"] = status
        row["completed_at"] = now_iso()
        row["reply_text"] = reply_text
        row["display"] = display or []
        row["reply_actor"] = actor or "claude"
        row["error_message"] = error_message
        row["turn_id"] = turn_id
        return row

    return update_job(jobs_dir, job_id, mutator)


def append_history(cfg: CronConfig, job: dict, display: list[dict], actor: str) -> None:
    """Append a completed exchange to history.jsonl (replicates bridge_complete.php logic)."""
    upload = job.get("upload")
    image_name = None
    if isinstance(upload, dict):
        image_name = upload.get("host_name")

    entry = {
        "job_id": job.get("id"),
        "ts": now_iso(),
        "mono": {
            "actor": job.get("actor", "mono"),
            "text": job.get("message", ""),
            "tags": job.get("tags", []),
            "image": image_name,
        },
        "claude": {
            "actor": actor,
            "display": display,
        },
    }

    cfg.history_file.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with cfg.history_file.open("a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        f.write(line)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def update_bridge_state(cfg: CronConfig, busy: bool = False) -> None:
    """Write bridge.json so the frontend status indicator works."""
    state = {
        "last_seen_at": now_iso(),
        "busy": busy,
        "worker": "cron-worker",
    }
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(cfg.state_dir / "bridge.json", state)


def check_trigger(cfg: CronConfig) -> bool:
    """Check for and consume the trigger signal file."""
    trigger = cfg.state_dir / "trigger"
    if trigger.exists():
        try:
            trigger.unlink()
        except OSError:
            pass
        return True
    return False


def handle_image(cfg: CronConfig, job: dict) -> str | None:
    """Get image path from job upload data, archive it."""
    upload = job.get("upload")
    if not isinstance(upload, dict):
        return None

    host_path = upload.get("host_path", "")
    if not host_path or not os.path.isfile(host_path):
        return None

    # Archive the image
    cfg.image_archive_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_id = str(job.get("id", "unknown"))
    orig_name = upload.get("original_name", "image.bin")
    archive_name = f"{ts}__{job_id}__{orig_name}"
    archive_path = cfg.image_archive_dir / archive_name

    shutil.copy2(host_path, archive_path)

    return str(archive_path)


def delete_upload(job: dict) -> None:
    """Remove the temp upload file after processing."""
    upload = job.get("upload")
    if not isinstance(upload, dict):
        return
    path = upload.get("host_path", "")
    if path and os.path.isfile(path):
        try:
            os.unlink(path)
        except OSError:
            pass


def process_job(cfg: CronConfig, job: dict) -> None:
    job_id = str(job.get("id", ""))
    if not job_id:
        raise RuntimeError("Job missing ID")

    message = str(job.get("message", ""))
    actor = str(job.get("actor", "mono")) or "mono"
    tags = job.get("tags", [])

    log(f"processing {job_id}")

    # Handle image
    image_path = handle_image(cfg, job)
    if image_path:
        log(f"archived image: {Path(image_path).name}")

    # Build config for orchestrator
    cc = ClaudeConfig(timeout_seconds=cfg.claude_timeout)
    if cfg.claude_model:
        cc.model = cfg.claude_model
    if cfg.claude_api_key:
        cc.api_key = cfg.claude_api_key

    turn_config = TurnConfig(
        db_path=cfg.db_path,
        wake_context_path=cfg.wake_context_path,
        wake_context_image_path=cfg.wake_context_image_path,
        ambient_path=cfg.ambient_path,
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
        complete_job(
            cfg.jobs_dir, job_id,
            status="error",
            error_message=result.error or "turn failed",
        )
        log(f"job {job_id} failed: {result.error}")
        delete_upload(job)
        return

    # Debug: show what Claude said
    raw = result.response_text
    log(f"raw response ({len(raw)} chars): {raw[:300]}{'...' if len(raw) > 300 else ''}")

    # Extract display spans
    display = extract_display_spans(result.response_text)
    reply_actor = result.actor or "claude"
    turn_id = str(result.turn)

    # Complete the job
    updated = complete_job(
        cfg.jobs_dir, job_id,
        status="done",
        display=display,
        actor=reply_actor,
        reply_text=result.response_text,
        turn_id=turn_id,
    )

    # Append to history
    if updated:
        append_history(cfg, updated, display, reply_actor)

    # Clean up temp upload
    delete_upload(job)

    log(f"job {job_id} done (turn {result.turn}, {len(display)} display spans)")


def run(cfg: CronConfig) -> int:
    """Main loop. Runs for MAX_RUN_SECONDS then exits for cron to restart."""
    log("cron worker starting")
    log(f"jobs_dir: {cfg.jobs_dir}")
    log(f"db: {cfg.db_path}")

    # Acquire exclusive lock — prevents overlapping cron runs
    lock_path = Path(__file__).parent / "worker.lock"
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("another worker is running, exiting")
        lock_fd.close()
        return 0

    # Graceful shutdown on SIGTERM/SIGINT
    shutdown = False

    def handle_signal(signum, frame):
        nonlocal shutdown
        shutdown = True
        log(f"received signal {signum}, finishing current work...")

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    start = time.monotonic()

    try:
        while not shutdown:
            elapsed = time.monotonic() - start
            if elapsed >= MAX_RUN_SECONDS:
                log("time limit reached, exiting")
                break

            # Heartbeat — keeps bridge status "online"
            update_bridge_state(cfg, busy=False)

            # Check for trigger (sub-second wakeup)
            triggered = check_trigger(cfg)

            # Look for a queued job
            queued = find_queued_job(cfg.jobs_dir)
            if queued is None:
                time.sleep(IDLE_SLEEP if triggered else POLL_SLEEP)
                continue

            # Claim it
            claimed = claim_job(cfg.jobs_dir, queued)
            if claimed is None:
                continue  # someone else got it

            # Process
            update_bridge_state(cfg, busy=True)
            try:
                process_job(cfg, claimed)
            except Exception as e:
                job_id = str(claimed.get("id", ""))
                log(f"job {job_id} error: {e}")
                if job_id:
                    try:
                        complete_job(
                            cfg.jobs_dir, job_id,
                            status="error",
                            error_message=str(e),
                        )
                    except Exception as ce:
                        log(f"failed to report error: {ce}")
            finally:
                update_bridge_state(cfg, busy=False)

    finally:
        # Final heartbeat before exit
        try:
            update_bridge_state(cfg, busy=False)
        except Exception:
            pass
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()
        log("worker exiting")

    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="silentstar cron worker")
    parser.add_argument(
        "--config",
        default=str(REPO_ROOT / "worker" / "config.json"),
        help="Path to worker config JSON",
    )
    args = parser.parse_args()

    cfg = load_config(Path(args.config).expanduser().resolve())
    return run(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
