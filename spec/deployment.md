# Deployment

## Setup

- **Host**: mono.me.uk, cPanel shared hosting
- **Site URL**: mono.me.uk/silentstar
- **Deploy path**: `/home/monomeuk/public_html/silentstar`
- **Repo on host**: `/home/monomeuk/repositories/silentstar`
- **Venv + logs**: `/home/monomeuk/silentstar/`
- **No SSH access** — all management through cPanel UI or file manager

## How to deploy

1. Push to GitHub
2. cPanel → Git Version Control → **Update from Remote**
3. **Deploy HEAD Commit**

The `.cpanel.yml` at repo root runs:
```
/bin/cp -R web/. $DEPLOYPATH/
```
This copies everything in `web/` (including dotfiles) to the deploy path.

## What NOT to touch during deploy

These live on the host only and are not in the repo. A deploy overwrites code but preserves these because `cp` merges into existing directories:

- `data/` — history.jsonl, bridge state, job files
- `uploads/` — user-uploaded images
- `config.local.php` — password hash, local config overrides

**If you nuke `public_html/silentstar`**, back up these three first.

## Cron worker

```
* * * * * /home/monomeuk/silentstar/.venv/bin/python /home/monomeuk/repositories/silentstar/worker/worker_cron.py --config /home/monomeuk/silentstar/config.json >> /home/monomeuk/silentstar/logs/worker.log 2>&1
```

Runs every minute, loops for 65 seconds (zero-gap). Lock file is at `/tmp/silentstar-worker.lock`.

**Important**: If you need to nuke and redeploy, disable the cron job first. It creates directories in the deploy path and will interfere with deletion.

## Known issues and things that don't work

### No SSH
The host has no SSH access on any port (22, 2222, 2022, 2200, 22022, 21098 all tested). rsync/scp deploy scripts won't work. FTP is available but we haven't needed it — cPanel Git deploy works.

### cPanel deploy stops working (dirty repo)
If "Deploy HEAD Commit" does nothing (no new log entries at `/home/monomeuk/.cpanel/logs/`), the repository working tree is probably dirty. cPanel Git silently refuses to deploy from a dirty repo.

**Common causes:**
- `worker.lock` was previously written inside the repo (fixed — now goes to `/tmp`)
- `__pycache__/` directories created by Python imports
- Any file written into `repositories/silentstar/` by the cron worker or other processes

**Fix:** Open the repo directory in cPanel File Manager (`repositories/silentstar/`) and delete any files that shouldn't be there (lock files, `__pycache__/`, temp files). Then deploy again.

### Shell globs in .cpanel.yml don't work
cPanel's deploy engine does not reliably expand shell wildcards (`*`). Use `web/.` (POSIX dot-copy) instead of `web/*`. The dot-copy also handles dotfiles, so no separate `.htaccess` copy needed.

### .htaccess blocks manifest.json
The `.htaccess` denies access to `.json` files for security. `manifest.json` has an explicit exception (`<Files "manifest.json">` with `Require all granted`). If you add other JSON files that need to be web-accessible, they'll need similar exceptions.

### Removing and re-adding the repo
If cPanel Git deploy is completely broken:

1. **Disable the cron job first**
2. Back up `data/`, `uploads/`, `config.local.php` from `public_html/silentstar/`
3. Delete `repositories/silentstar/` via file manager
4. Delete `public_html/silentstar/` via file manager
5. Re-create repo in cPanel Git Version Control (same remote, deploy path `/home/monomeuk/public_html/silentstar`)
6. Update from Remote → Deploy HEAD Commit
7. Restore backed up files
8. Re-enable the cron job
