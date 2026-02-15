#!/bin/bash
# Deploy web/ to the cPanel host.
# Run from project root: ./deploy.sh
#
# Requires: ssh access to the host
# Syncs web/ contents, skips data/, uploads/, and config.local.php

set -e

HOST="monomeuk@mono.me.uk"
REMOTE_PATH="/home/monomeuk/public_html/silentstar"

echo "Deploying web/ → $HOST:$REMOTE_PATH ..."

rsync -avz --delete \
  --exclude 'data/' \
  --exclude 'uploads/' \
  --exclude 'config.local.php' \
  --exclude 'generate-icons.html' \
  web/ "$HOST:$REMOTE_PATH/"

echo "Done."
