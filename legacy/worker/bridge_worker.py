#!/usr/bin/env python3
"""
silentstar bridge worker

Host-side PHP app queues jobs. This worker runs locally, claims jobs,
assembles wake context against local SQLite, calls Claude CLI, and
completes the job back to the host bridge.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

try:
    import dateparser  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    dateparser = None


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wake.assemble import WakeConfig, assemble, render  # noqa: E402
from wake.recall import RecallResult, recall  # noqa: E402


IDENTITY_TAGS = {
    "mono",
    "hasuki",
    "renki",
    "luna",
    "chloe",
    "strah",
    "claude",
    "y'lhara",
}
CONTENT_TAGS = {"plan", "secret"}
DISPLAY_TAGS = {"say", "rp", "nr"}
ALL_EVENT_TAGS = CONTENT_TAGS | DISPLAY_TAGS

TAG_TOKEN_RE = re.compile(r"<\s*([a-zA-Z0-9_'-]{1,32})\s*>")
RECALL_RE = re.compile(
    r"recall\(\s*['\"]([^'\"]+)['\"]\s*(?:,\s*deep\s*=\s*(true|false))?\s*\)",
    re.IGNORECASE,
)
IMAGE_MARKER_RE = re.compile(r"\[image:\s*([^\]]+)\]")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def slug_token(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    cleaned = cleaned.strip("._")
    return cleaned or fallback


def normalize_identity(actor: str | None, fallback: str) -> str:
    raw = (actor or "").strip().lower()
    if raw == "ylhara":
        raw = "y'lhara"
    if raw in IDENTITY_TAGS:
        return raw
    return fallback


def normalize_tags(values: list[str] | None, allowed: set[str]) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        t = v.strip().lower()
        if t in allowed and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def flatten_tag_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(flatten_tag_values(item))
        return out
    if isinstance(value, str):
        parts = re.split(r"[\s,;|]+", value.strip())
        return [p for p in parts if p]
    return []


def parse_response_leading_tags(text: str) -> tuple[str | None, list[str], list[str], str]:
    cursor = text.lstrip()
    actor: str | None = None
    content_tags: list[str] = []
    display_tags: list[str] = []
    consumed_any = False

    while True:
        m = TAG_TOKEN_RE.match(cursor)
        if not m:
            break
        token = m.group(1).strip().lower()
        if token == "ylhara":
            token = "y'lhara"
        consumed_any = True
        if token in IDENTITY_TAGS and actor is None:
            actor = token
        elif token in CONTENT_TAGS and token not in content_tags:
            content_tags.append(token)
        elif token in DISPLAY_TAGS and token not in display_tags:
            display_tags.append(token)
        cursor = cursor[m.end() :].lstrip()

    cleaned = cursor if consumed_any else text
    return actor, content_tags, display_tags, cleaned


def parse_recall_requests(text: str) -> list[tuple[str, bool]]:
    requests_out: list[tuple[str, bool]] = []
    seen: set[tuple[str, bool]] = set()
    for m in RECALL_RE.finditer(text):
        key = m.group(1).strip()
        if not key:
            continue
        deep_str = (m.group(2) or "").strip().lower()
        deep = deep_str == "true"
        item = (key, deep)
        if item not in seen:
            seen.add(item)
            requests_out.append(item)
    return requests_out


def has_time_language(text: str) -> bool:
    pattern = (
        r"\b("
        r"today|tonight|tomorrow|tmr|next|this\s+(?:week|month|year)|"
        r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
        r"in\s+\d+\s*(?:m|min|mins|minute|minutes|h|hr|hrs|hour|hours|day|days|week|weeks|month|months|year|years)|"
        r"\d{1,2}:\d{2}\s*(?:am|pm)?|"
        r"\d{1,2}\s*(?:am|pm)|"
        r"\d{4}-\d{1,2}-\d{1,2}|"
        r"\d{1,2}/\d{1,2}(?:/\d{2,4})?"
        r")\b"
    )
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def parse_due_with_fallback(content: str, now: datetime) -> datetime | None:
    raw = content.strip()
    if not raw:
        return None
    lower = raw.lower()

    if re.search(r"\b(daily|every day)\b", lower):
        return now + timedelta(days=1)
    if re.search(r"\b(weekly|every week)\b", lower):
        return now + timedelta(weeks=1)
    if re.search(r"\b(monthly|every month)\b", lower):
        # "Next month" approximation for fallback parsing.
        return now + timedelta(days=30)

    if dateparser is not None:
        parsed = dateparser.parse(
            raw,
            settings={
                "RELATIVE_BASE": now,
                "PREFER_DATES_FROM": "future",
                "TIMEZONE": "UTC",
                "RETURN_AS_TIMEZONE_AWARE": True,
            },
        )
        if parsed is not None:
            parsed_utc = parsed.astimezone(timezone.utc)
            day_name = re.search(
                r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
                lower,
            )
            has_past = re.search(r"\b(last|ago|yesterday)\b", lower) is not None
            has_explicit_date = re.search(
                r"\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b",
                lower,
            )
            if day_name and not has_past and not has_explicit_date and parsed_utc <= now:
                parsed_utc = parsed_utc + timedelta(days=7)
            return parsed_utc

    rel = re.search(
        r"\bin\s+(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|day|days|week|weeks)\b",
        lower,
    )
    if rel:
        qty = int(rel.group(1))
        unit = rel.group(2)
        if unit.startswith(("m", "min")):
            return now + timedelta(minutes=qty)
        if unit.startswith(("h", "hr")):
            return now + timedelta(hours=qty)
        if unit.startswith("day"):
            return now + timedelta(days=qty)
        if unit.startswith("week"):
            return now + timedelta(weeks=qty)

    days = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    for name, weekday in days.items():
        if re.search(rf"\b{name}\b", lower):
            delta = (weekday - now.weekday()) % 7
            if delta == 0:
                delta = 7
            return now + timedelta(days=delta)

    if "tomorrow" in lower or "tmr" in lower:
        return now + timedelta(days=1)
    if "next week" in lower:
        return now + timedelta(weeks=1)

    return None


def parse_plan_due(content: str, now: datetime) -> str | None:
    if not has_time_language(content):
        # still allow recurring words that are treated specially
        recurring = re.search(r"\b(daily|every day|weekly|every week|monthly|every month)\b", content.lower())
        if not recurring:
            return None
    parsed = parse_due_with_fallback(content, now)
    return parsed.isoformat() if parsed is not None else None


def connect_db(db_path: Path) -> sqlite3.Connection:
    ensure_dir(db_path.parent)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.DatabaseError:
        pass
    return conn


def migrate_db(conn: sqlite3.Connection) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            content TEXT NOT NULL,
            actor TEXT,
            image_path TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC)",
        """
        CREATE TABLE IF NOT EXISTS event_tags (
            event_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            PRIMARY KEY (event_id, tag),
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_event_tags_tag ON event_tags(tag)",
        """
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            actor TEXT,
            summary TEXT NOT NULL,
            due TEXT,
            status TEXT NOT NULL CHECK (status IN ('active', 'done', 'cancelled', 'expired')),
            created_at TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_plans_status_due ON plans(status, due)",
        """
        CREATE TABLE IF NOT EXISTS fragments (
            key TEXT PRIMARY KEY,
            ambient TEXT,
            recognition TEXT,
            inventory TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS fragment_sources (
            fragment_key TEXT NOT NULL,
            event_id INTEGER NOT NULL,
            PRIMARY KEY (fragment_key, event_id),
            FOREIGN KEY (fragment_key) REFERENCES fragments(key) ON DELETE CASCADE,
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS fragment_edges (
            source_key TEXT NOT NULL,
            target_key TEXT NOT NULL,
            relation TEXT,
            PRIMARY KEY (source_key, target_key),
            FOREIGN KEY (source_key) REFERENCES fragments(key) ON DELETE CASCADE,
            FOREIGN KEY (target_key) REFERENCES fragments(key) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_fragment_edges_source ON fragment_edges(source_key)",
        "CREATE INDEX IF NOT EXISTS idx_fragment_edges_target ON fragment_edges(target_key)",
        """
        CREATE TABLE IF NOT EXISTS state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS maintenance_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            run_type TEXT NOT NULL CHECK (run_type IN ('weekly', 'monthly', 'manual', 'bootstrap'))
        )
        """,
    ]
    for stmt in statements:
        conn.execute(stmt)
    conn.commit()


def state_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    v = row["value"]
    return str(v) if v is not None else None


def state_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO state (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, value, utc_now_iso()),
    )


def increment_turn(conn: sqlite3.Connection) -> int:
    cur = state_get(conn, "current_turn")
    now_turn = int(cur) if cur and cur.isdigit() else 0
    if now_turn < 0:
        now_turn = 0
    next_turn = now_turn + 1
    state_set(conn, "current_turn", str(next_turn))
    return next_turn


@dataclass
class IngestResult:
    event_id: int
    actor: str
    tags: list[str]
    plan_id: int | None
    due: str | None
    turn: int | None
    ts: str


def ingest_event(
    conn: sqlite3.Connection,
    *,
    content: str,
    actor: str | None,
    fallback_actor: str,
    tags: list[str] | None = None,
    image_path: str | None = None,
    increment_turn_counter: bool = False,
) -> IngestResult:
    now_iso = utc_now_iso()
    now = utc_now()
    actor_norm = normalize_identity(actor, fallback_actor)
    tag_norm = normalize_tags(tags, ALL_EVENT_TAGS)

    with conn:
        cur = conn.execute(
            "INSERT INTO events (ts, content, actor, image_path) VALUES (?, ?, ?, ?)",
            (now_iso, content, actor_norm, image_path),
        )
        event_id = int(cur.lastrowid)

        for tag in tag_norm:
            conn.execute(
                "INSERT OR IGNORE INTO event_tags (event_id, tag) VALUES (?, ?)",
                (event_id, tag),
            )

        plan_id: int | None = None
        due: str | None = None
        if "plan" in tag_norm:
            due = parse_plan_due(content, now)
            cur_plan = conn.execute(
                """
                INSERT INTO plans (event_id, actor, summary, due, status, created_at)
                VALUES (?, ?, ?, ?, 'active', ?)
                """,
                (event_id, actor_norm, content, due, now_iso),
            )
            plan_id = int(cur_plan.lastrowid)

        turn: int | None = None
        if increment_turn_counter:
            turn = increment_turn(conn)

    return IngestResult(
        event_id=event_id,
        actor=actor_norm,
        tags=tag_norm,
        plan_id=plan_id,
        due=due,
        turn=turn,
        ts=now_iso,
    )


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class WorkerConfig:
    raw: dict[str, Any]
    repo_root: Path
    web_base_url: str
    bridge_shared_secret: str
    worker_name: str
    heartbeat_interval_sec: float
    claim_interval_sec: float
    request_timeout_sec: float
    db_path: Path
    wake_context_path: Path
    ambient_path: Path
    image_archive_dir: Path
    work_dir: Path
    claude_binary: str
    claude_command_template: list[str]
    claude_timeout_sec: float
    claude_env: dict[str, str]
    verbose: bool


def default_wake_context_path(repo_root: Path) -> Path:
    candidates = [
        repo_root / "mdfiles" / "wake-context.md",
        repo_root / "mdfiles" / "claude" / "wake-context.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def load_config(path: Path) -> WorkerConfig:
    defaults: dict[str, Any] = {
        "bridge": {
            "web_base_url": "",
            "shared_secret": "",
            "worker_name": "silentstar-worker",
            "heartbeat_interval_sec": 2.0,
            "claim_interval_sec": 1.2,
            "request_timeout_sec": 20.0,
        },
        "paths": {
            "repo_root": str(REPO_ROOT),
            "db_path": "data/memory.sqlite",
            "wake_context_path": "",
            "ambient_path": "ambient.md",
            "image_archive_dir": "data/img-dump",
            "work_dir": "data/worker",
        },
        "claude_cli": {
            "binary": "",
            "command_template": [],
            "timeout_sec": 240.0,
            "env": {},
        },
        "worker": {
            "verbose": True,
        },
    }

    if not path.is_file():
        raise RuntimeError(
            f"config file not found: {path}\n"
            "Copy worker/config.example.json to worker/config.json and edit it."
        )
    with path.open("r", encoding="utf-8") as f:
        loaded = json.load(f)
    if not isinstance(loaded, dict):
        raise RuntimeError("worker config must be a JSON object")

    merged = deep_merge(defaults, loaded)

    repo_root_raw = str(merged["paths"].get("repo_root", str(REPO_ROOT)))
    repo_root = Path(repo_root_raw).expanduser()
    if not repo_root.is_absolute():
        repo_root = (path.parent / repo_root).resolve()

    def resolve_path(value: str, fallback: Path) -> Path:
        raw = value.strip()
        if not raw:
            return fallback
        # Treat /data/... as a repo-relative alias.
        if raw == "/data" or raw.startswith("/data/"):
            return (repo_root / raw.lstrip("/")).resolve()
        p = Path(raw).expanduser()
        if p.is_absolute():
            return p
        return (repo_root / p).resolve()

    wake_cfg = str(merged["paths"].get("wake_context_path", "")).strip()
    wake_path = resolve_path(wake_cfg, default_wake_context_path(repo_root))

    cfg = WorkerConfig(
        raw=merged,
        repo_root=repo_root,
        web_base_url=str(merged["bridge"].get("web_base_url", "")).rstrip("/"),
        bridge_shared_secret=str(merged["bridge"].get("shared_secret", "")),
        worker_name=str(merged["bridge"].get("worker_name", "silentstar-worker")),
        heartbeat_interval_sec=float(merged["bridge"].get("heartbeat_interval_sec", 2.0)),
        claim_interval_sec=float(merged["bridge"].get("claim_interval_sec", 1.2)),
        request_timeout_sec=float(merged["bridge"].get("request_timeout_sec", 20.0)),
        db_path=resolve_path(str(merged["paths"].get("db_path", "")), repo_root / "data" / "memory.sqlite"),
        wake_context_path=wake_path,
        ambient_path=resolve_path(str(merged["paths"].get("ambient_path", "")), repo_root / "ambient.md"),
        image_archive_dir=resolve_path(
            str(merged["paths"].get("image_archive_dir", "")),
            repo_root / "data" / "img-dump",
        ),
        work_dir=resolve_path(str(merged["paths"].get("work_dir", "")), repo_root / "data" / "worker"),
        claude_binary=str(merged["claude_cli"].get("binary", "")).strip(),
        claude_command_template=list(merged["claude_cli"].get("command_template", [])),
        claude_timeout_sec=float(merged["claude_cli"].get("timeout_sec", 240.0)),
        claude_env={str(k): str(v) for k, v in dict(merged["claude_cli"].get("env", {})).items()},
        verbose=bool(merged["worker"].get("verbose", True)),
    )

    if not cfg.web_base_url:
        raise RuntimeError("bridge.web_base_url is required")
    if not cfg.bridge_shared_secret:
        raise RuntimeError("bridge.shared_secret is required")
    if cfg.claude_command_template:
        has_known_placeholder = any(
            ("{prompt_file}" in p)
            or ("{prompt}" in p)
            or ("{prompt_text}" in p)
            or ("{prompt_stdin}" in p)
            for p in cfg.claude_command_template
        )
        if not has_known_placeholder:
            # No explicit prompt placeholder means prompt will be piped via stdin.
            pass
    return cfg


class BridgeClient:
    def __init__(self, config: WorkerConfig):
        self.cfg = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-Bridge-Secret": config.bridge_shared_secret,
                "Content-Type": "application/json",
                "User-Agent": "silentstar-worker/1.0",
            }
        )

    def _url(self, path: str) -> str:
        return f"{self.cfg.web_base_url}/api/{path}"

    def heartbeat(self, busy: bool) -> None:
        payload = {"busy": busy, "worker": self.cfg.worker_name}
        r = self.session.post(
            self._url("bridge_heartbeat.php"),
            data=json.dumps(payload),
            timeout=self.cfg.request_timeout_sec,
        )
        r.raise_for_status()

    def claim(self) -> dict[str, Any] | None:
        payload = {"worker": self.cfg.worker_name}
        r = self.session.post(
            self._url("bridge_claim.php"),
            data=json.dumps(payload),
            timeout=self.cfg.request_timeout_sec,
        )
        r.raise_for_status()
        body = r.json()
        if not isinstance(body, dict) or not body.get("ok"):
            raise RuntimeError(f"claim failed: {body}")
        job = body.get("job")
        if not isinstance(job, dict):
            return None
        return job

    def download_upload(self, job_id: str, original_name: str | None, dest_dir: Path) -> Path:
        ensure_dir(dest_dir)
        safe_name = slug_token(original_name or "upload.bin", "upload.bin")
        local_name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}__{job_id}__{safe_name}"
        target = dest_dir / local_name
        r = self.session.get(
            self._url("bridge_download.php"),
            params={"id": job_id},
            timeout=self.cfg.request_timeout_sec,
            stream=True,
        )
        r.raise_for_status()
        with target.open("wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
        return target

    def complete(
        self,
        *,
        job_id: str,
        status: str,
        reply_text: str | None,
        error_message: str | None,
        turn_id: str | None,
        local_image_path: str | None,
        actor: str | None,
        tags: list[str] | None,
        content_tags: list[str] | None,
        display_tags: list[str] | None,
        meta: dict[str, Any] | None,
    ) -> None:
        payload: dict[str, Any] = {
            "id": job_id,
            "status": status,
            "reply_text": reply_text,
            "error_message": error_message,
            "turn_id": turn_id,
            "local_image_path": local_image_path,
            "actor": actor,
            "tags": tags or [],
            "content_tags": content_tags or [],
            "display_tags": display_tags or [],
            "meta": meta or {},
        }
        r = self.session.post(
            self._url("bridge_complete.php"),
            data=json.dumps(payload),
            timeout=self.cfg.request_timeout_sec,
        )
        r.raise_for_status()
        body = r.json()
        if not isinstance(body, dict) or not body.get("ok"):
            raise RuntimeError(f"complete failed: {body}")


class ClaudeCliRunner:
    def __init__(self, config: WorkerConfig):
        self.cfg = config

    def run(
        self,
        prompt: str,
        image_paths: list[str],
        heartbeat_cb: callable | None = None,
    ) -> str:
        ensure_dir(self.cfg.work_dir)

        with tempfile.TemporaryDirectory(dir=str(self.cfg.work_dir)) as td:
            td_path = Path(td)
            prompt_file = td_path / "prompt.txt"
            prompt_file.write_text(prompt, encoding="utf-8")

            command, use_stdin = self._build_command(prompt, prompt_file, image_paths)
            env = dict(os.environ)
            env.update(self.cfg.claude_env)

            stdin_mode: int | None = subprocess.PIPE if use_stdin else subprocess.DEVNULL
            image_payload = "\n".join(image_paths)

            proc = subprocess.Popen(
                command,
                cwd=str(self.cfg.repo_root),
                env=env,
                stdin=stdin_mode,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            start = time.monotonic()
            interval = max(0.5, self.cfg.heartbeat_interval_sec)
            pending_input: str | None = prompt if use_stdin else None
            while True:
                if heartbeat_cb is not None:
                    heartbeat_cb()
                try:
                    stdout, stderr = proc.communicate(input=pending_input, timeout=interval)
                    break
                except subprocess.TimeoutExpired:
                    pending_input = None
                    elapsed = time.monotonic() - start
                    if elapsed > self.cfg.claude_timeout_sec:
                        proc.kill()
                        stdout, stderr = proc.communicate(timeout=5)
                        raise RuntimeError(
                            f"Claude CLI timeout after {self.cfg.claude_timeout_sec}s.\n"
                            f"stdout tail: {stdout[-600:]}\n"
                            f"stderr tail: {stderr[-600:]}"
                        )

            if proc.returncode != 0:
                raise RuntimeError(
                    f"Claude CLI exited with code {proc.returncode}\n"
                    f"stdout tail: {stdout[-600:]}\n"
                    f"stderr tail: {stderr[-600:]}"
                )

            out = (stdout or "").strip()
            if not out:
                raise RuntimeError("Claude CLI returned empty stdout")
            return out

    def _build_command(self, prompt: str, prompt_file: Path, image_paths: list[str]) -> tuple[list[str], bool]:
        image_payload = "\n".join(image_paths)

        if self.cfg.claude_command_template:
            use_stdin = False
            command: list[str] = []
            for token in self.cfg.claude_command_template:
                if "{prompt_stdin}" in token:
                    use_stdin = True
                    replaced = token.replace("{prompt_stdin}", "")
                    if replaced.strip() == "":
                        continue
                else:
                    replaced = token
                replaced = (
                    replaced.replace("{prompt_file}", str(prompt_file))
                    .replace("{prompt}", prompt)
                    .replace("{prompt_text}", prompt)
                    .replace("{image_paths}", image_payload)
                )
                command.append(replaced)

            has_prompt_placeholder = any(
                ("{prompt_file}" in t) or ("{prompt}" in t) or ("{prompt_text}" in t) or ("{prompt_stdin}" in t)
                for t in self.cfg.claude_command_template
            )
            if not has_prompt_placeholder:
                use_stdin = True

            if not command:
                raise RuntimeError("claude_cli.command_template resolved to an empty command")
            return command, use_stdin

        binary = self._resolve_claude_binary()
        # Default for Claude subscription CLI: non-interactive print mode via stdin.
        return [binary, "-p", "--output-format", "text"], True

    def _resolve_claude_binary(self) -> str:
        candidates = []
        if self.cfg.claude_binary:
            candidates.append(self.cfg.claude_binary)
        candidates.extend(["claude", "claude.exe", "claude.cmd"])

        for c in candidates:
            if shutil.which(c):
                return c
        raise RuntimeError(
            "Claude CLI binary not found. Set claude_cli.binary in worker/config.json "
            "or add `claude` to PATH."
        )


class Worker:
    def __init__(self, cfg: WorkerConfig):
        self.cfg = cfg
        self.client = BridgeClient(cfg)
        self.cli = ClaudeCliRunner(cfg)
        self.previous_recall_results: list[RecallResult] = []

        ensure_dir(self.cfg.image_archive_dir)
        ensure_dir(self.cfg.work_dir)
        ensure_dir(self.cfg.db_path.parent)

    def log(self, msg: str) -> None:
        if self.cfg.verbose:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

    def _heartbeat_safe(self, busy: bool) -> None:
        try:
            self.client.heartbeat(busy)
        except Exception as e:
            self.log(f"heartbeat failed: {e}")

    def _extract_image_markers(self, prompt: str) -> list[str]:
        out: list[str] = []
        for m in IMAGE_MARKER_RE.finditer(prompt):
            p = m.group(1).strip()
            if p and p not in out:
                out.append(p)
        return out

    def _resolve_recalls(self, response_text: str, db_path: Path) -> list[RecallResult]:
        recall_requests = parse_recall_requests(response_text)
        if not recall_requests:
            return []
        results: list[RecallResult] = []
        seen: set[tuple[str, bool]] = set()
        for key, deep in recall_requests:
            item = (key, deep)
            if item in seen:
                continue
            seen.add(item)
            res = recall(key, db_path=db_path, deep=deep)
            if res is not None:
                results.append(res)
        return results

    def process_job(self, job: dict[str, Any]) -> None:
        job_id = str(job.get("id", "")).strip()
        if not job_id:
            raise RuntimeError("claimed job is missing id")

        message = str(job.get("message") or "")
        mono_actor = normalize_identity(str(job.get("actor") or ""), "mono")
        mono_content_tags = normalize_tags(flatten_tag_values(job.get("content_tags")), CONTENT_TAGS)
        mono_display_tags = normalize_tags(flatten_tag_values(job.get("display_tags")), DISPLAY_TAGS)
        mono_tags = normalize_tags(flatten_tag_values(job.get("tags")), ALL_EVENT_TAGS)
        if not mono_content_tags and mono_tags:
            mono_content_tags = [t for t in mono_tags if t in CONTENT_TAGS]
        if not mono_display_tags and mono_tags:
            mono_display_tags = [t for t in mono_tags if t in DISPLAY_TAGS]
        mono_tags = normalize_tags(mono_content_tags + mono_display_tags + mono_tags, ALL_EVENT_TAGS)

        self.log(f"processing job {job_id}")

        local_upload_path: Path | None = None
        if bool(job.get("has_upload")):
            upload = job.get("upload")
            upload_name = None
            if isinstance(upload, dict):
                upload_name = upload.get("original_name")
            local_upload_path = self.client.download_upload(job_id, upload_name, self.cfg.image_archive_dir)
            self.log(f"downloaded upload for {job_id} -> {local_upload_path}")

        conn = connect_db(self.cfg.db_path)
        try:
            migrate_db(conn)

            mono_ingest = ingest_event(
                conn,
                content=message,
                actor=mono_actor,
                fallback_actor="mono",
                tags=mono_tags,
                image_path=str(local_upload_path) if local_upload_path else None,
                increment_turn_counter=True,
            )
            current_turn = mono_ingest.turn or 1

            wake_cfg = WakeConfig(
                db_path=self.cfg.db_path,
                wake_context_path=self.cfg.wake_context_path,
                ambient_path=self.cfg.ambient_path,
            )
            package = assemble(
                config=wake_cfg,
                hot_context=message,
                current_turn=current_turn,
                recall_results=self.previous_recall_results,
            )
            prompt = render(package)
            image_markers = self._extract_image_markers(prompt)

            def hb_busy() -> None:
                self._heartbeat_safe(True)

            raw_response = self.cli.run(prompt, image_markers, heartbeat_cb=hb_busy)
            actor_tag, content_tags, display_tags, cleaned_text = parse_response_leading_tags(raw_response)
            claude_actor = normalize_identity(actor_tag, "claude")
            claude_content_tags = normalize_tags(content_tags, CONTENT_TAGS)
            claude_display_tags = normalize_tags(display_tags, DISPLAY_TAGS)
            claude_tags = normalize_tags(claude_content_tags + claude_display_tags, ALL_EVENT_TAGS)

            claude_ingest = ingest_event(
                conn,
                content=cleaned_text,
                actor=claude_actor,
                fallback_actor="claude",
                tags=claude_tags,
                image_path=None,
                increment_turn_counter=False,
            )

            next_recalls = self._resolve_recalls(raw_response, self.cfg.db_path)
            self.previous_recall_results = next_recalls

            meta = {
                "worker": {
                    "name": self.cfg.worker_name,
                    "processed_at": utc_now_iso(),
                },
                "wake": {
                    "current_turn": current_turn,
                    "wake_context_path": str(self.cfg.wake_context_path),
                    "ambient_path": str(self.cfg.ambient_path),
                    "image_markers": image_markers,
                    "recall_requests": [
                        {"key": k, "deep": deep}
                        for (k, deep) in parse_recall_requests(raw_response)
                    ],
                    "resolved_recalls": [r.key for r in next_recalls],
                },
                "local_ingestion": {
                    "mono_event_id": mono_ingest.event_id,
                    "mono_tags": mono_tags,
                    "claude_event_id": claude_ingest.event_id,
                    "claude_tags": claude_tags,
                    "db_path": str(self.cfg.db_path),
                },
            }

            self.client.complete(
                job_id=job_id,
                status="done",
                reply_text=cleaned_text,
                error_message=None,
                turn_id=str(current_turn),
                local_image_path=None,
                actor=claude_actor,
                tags=claude_tags,
                content_tags=claude_content_tags,
                display_tags=claude_display_tags,
                meta=meta,
            )
            self.log(f"job {job_id} completed")
        finally:
            conn.close()

    def run_forever(self) -> None:
        self.log("worker starting")
        self.log(f"bridge base: {self.cfg.web_base_url}")
        self.log(f"local db: {self.cfg.db_path}")
        self.log(f"wake context: {self.cfg.wake_context_path}")
        self.log(f"ambient: {self.cfg.ambient_path}")
        self.log(f"dateparser available: {dateparser is not None}")

        last_hb = 0.0
        while True:
            now = time.monotonic()
            if now - last_hb >= self.cfg.heartbeat_interval_sec:
                self._heartbeat_safe(False)
                last_hb = now

            try:
                job = self.client.claim()
            except Exception as e:
                self.log(f"claim failed: {e}")
                time.sleep(self.cfg.claim_interval_sec)
                continue

            if job is None:
                time.sleep(self.cfg.claim_interval_sec)
                continue

            self._heartbeat_safe(True)
            try:
                self.process_job(job)
            except Exception as e:
                job_id = str(job.get("id") or "")
                err_msg = str(e)
                self.log(f"job {job_id} failed: {err_msg}")
                if job_id:
                    try:
                        self.client.complete(
                            job_id=job_id,
                            status="error",
                            reply_text=None,
                            error_message=err_msg,
                            turn_id=None,
                            local_image_path=None,
                            actor=None,
                            tags=[],
                            content_tags=[],
                            display_tags=[],
                            meta={"worker": {"name": self.cfg.worker_name, "processed_at": utc_now_iso()}},
                        )
                    except Exception as complete_err:
                        self.log(f"failed to report error for {job_id}: {complete_err}")
            finally:
                self._heartbeat_safe(False)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run silentstar local bridge worker")
    p.add_argument(
        "--config",
        default=str(REPO_ROOT / "worker" / "config.json"),
        help="Path to worker config JSON",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config(Path(args.config).expanduser().resolve())
    worker = Worker(cfg)
    worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
