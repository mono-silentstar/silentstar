# silentstar Startup

Architecture reminder:
- Web host (`web/`) only accepts queued turns and serves status/results.
- Local worker (`worker/bridge_worker.py`) performs wake + memory ingestion.

## Run now

```bash
bash scripts/silentstar-start.sh
```

Windows PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\silentstar-start.ps1
```

Optional environment variables:

- `PHP_BIN` (default: `php`)
- `SILENTSTAR_HOST` (default: `127.0.0.1`)
- `SILENTSTAR_PORT` (default: `8080`)

## Enable auto-start on boot (Linux systemd user service)

```bash
bash scripts/install-autostart.sh
```

This installs and enables `silentstar.service` in:

`~/.config/systemd/user/silentstar.service`

To start at boot without interactive login:

```bash
sudo loginctl enable-linger "$USER"
```

## Enable auto-start on Windows Task Scheduler

Use logon trigger (no admin needed):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-autostart-windows.ps1 -Mode Logon
```

Use true boot trigger (admin PowerShell required):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-autostart-windows.ps1 -Mode Startup
```

## Run worker locally (Windows)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\silentstar-worker-start.ps1
```

## Run web + worker together (Windows)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\silentstar-start-all.ps1
```

## Enable worker auto-start on Windows Task Scheduler

Logon trigger:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-worker-autostart-windows.ps1 -Mode Logon
```

Boot trigger (admin PowerShell):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-worker-autostart-windows.ps1 -Mode Startup
```

## Enable web + worker auto-start together (Windows)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-autostart-windows-all.ps1 -Mode Logon
```
