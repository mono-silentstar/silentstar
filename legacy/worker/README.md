# silentstar Worker

Python bridge worker for local wake processing + Claude CLI execution.
The web host only queues turns and returns Claude replies; all ingestion,
memory, wake assembly, and tag behavior happens here.

## Setup

1. Copy `worker/config.example.json` to `worker/config.json`.
2. Edit:
- `bridge.web_base_url`
- `bridge.shared_secret`
- Optional: `claude_cli.binary` (default expects `claude` in PATH)
- Optional: `claude_cli.command_template` for custom invocation
- optional paths for wake/db/ambient files

Default Claude invocation (when `command_template` is empty):

- `claude -p --output-format text` with prompt piped on stdin

## Run

```bash
python3 worker/bridge_worker.py --config worker/config.json
```

Keep this process running continuously (or install the Windows Task Scheduler
autostart task in `scripts/`).

## What It Does

- Sends bridge heartbeat
- Claims queued jobs from host
- Downloads uploaded images
- Ingests Mono event into local SQLite (`data/memory.sqlite`)
- Assembles wake prompt from local DB + ambient/wake files
- Runs Claude CLI command
- Parses leading tags from response (`<claude><secret><rp> ...`)
- Ingests Claude event locally
- Reports completion back to host bridge APIs

## Tag Parsing

Recognized identity tags:
- `hasuki`, `renki`, `luna`, `chloe`, `strah`, `claude`, `y'lhara`

Recognized content tags:
- `plan`, `secret`

Recognized display tags:
- `say`, `rp`, `nr`
