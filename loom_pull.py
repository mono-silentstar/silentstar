#!/usr/bin/env python3
"""
loom_pull.py — pull phone-uploaded images from server to local.

Downloads all images from api/loom_images.php, saves to a local folder,
then clears the server copies. Server is transit only.

Usage:
    python loom_pull.py temp/room-inventory/pics/
    python loom_pull.py temp/room-inventory/pics/ --password mypass
    python loom_pull.py temp/room-inventory/pics/ --keep-server   # don't auto-clear

Password can be provided via:
    --password flag
    SILENTSTAR_PASSWORD env var
    Interactive prompt (if neither set)

Server URL read from worker/config.json (web_base_url).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print(
        "requests library required. Install with: pip install requests",
        file=sys.stderr,
    )
    sys.exit(1)


def _load_base_url() -> str:
    config_path = Path("worker/config.json")
    if config_path.exists():
        with open(config_path) as f:
            cfg = json.load(f)
        url = cfg.get("web_base_url", "")
        if url:
            return url.rstrip("/")

    return "https://mono.me.uk/silentstar"


def _login(session: requests.Session, base_url: str, password: str) -> bool:
    """Login to get a session cookie."""
    resp = session.post(
        f"{base_url}/api/login.php",
        data={"password": password},
        allow_redirects=False,
    )
    # Login redirects to ../ on success, ../?login_error=1 on failure
    location = resp.headers.get("Location", "")
    return "login_error" not in location


def _list_images(session: requests.Session, base_url: str) -> list[dict]:
    """List uploaded images on server."""
    resp = session.get(f"{base_url}/api/loom_images.php")
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"API error: {data.get('error', 'unknown')}")
    return data.get("files", [])


def _download_image(
    session: requests.Session, base_url: str, name: str, dest: Path
) -> None:
    """Download a single image."""
    resp = session.get(
        f"{base_url}/api/loom_images.php",
        params={"file": name},
        stream=True,
    )
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)


def _clear_server(session: requests.Session, base_url: str) -> int:
    """Clear all uploads from server. Returns count cleared."""
    resp = session.post(
        f"{base_url}/api/loom_images.php",
        data={"action": "clear"},
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("cleared", 0)


def main():
    parser = argparse.ArgumentParser(
        description="Pull phone-uploaded images from server to local folder"
    )
    parser.add_argument("dest", help="Local destination folder")
    parser.add_argument("--password", help="Login password")
    parser.add_argument(
        "--keep-server",
        action="store_true",
        help="Don't clear server copies after download",
    )
    parser.add_argument("--url", help="Server base URL (default: from config)")

    args = parser.parse_args()

    base_url = args.url or _load_base_url()
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)

    # Get password
    password = args.password or os.environ.get("SILENTSTAR_PASSWORD")
    if not password:
        password = getpass.getpass("Password: ")

    # Login
    session = requests.Session()
    if not _login(session, base_url, password):
        print("Login failed.", file=sys.stderr)
        sys.exit(1)

    # List images
    images = _list_images(session, base_url)
    if not images:
        print("No images on server.")
        return

    print(f"{len(images)} image(s) on server:")

    # Download each
    downloaded = 0
    for img in images:
        name = img["name"]
        size_kb = img["size"] / 1024
        dest_path = dest / name

        if dest_path.exists():
            print(f"  skip  {name} (already exists locally)")
            continue

        print(f"  pull  {name} ({size_kb:.0f} KB)")
        _download_image(session, base_url, name, dest_path)
        downloaded += 1

    print(f"\nDownloaded {downloaded} image(s) to {dest}")

    # Clear server
    if not args.keep_server:
        cleared = _clear_server(session, base_url)
        print(f"Cleared {cleared} image(s) from server.")
    else:
        print("Server copies kept (--keep-server).")


if __name__ == "__main__":
    main()
