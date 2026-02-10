#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PHP_BIN="${PHP_BIN:-php}"
SILENTSTAR_HOST="${SILENTSTAR_HOST:-127.0.0.1}"
SILENTSTAR_PORT="${SILENTSTAR_PORT:-8080}"

if ! command -v "${PHP_BIN}" >/dev/null 2>&1; then
  echo "silentstar: php runtime not found (PHP_BIN=${PHP_BIN})" >&2
  exit 1
fi

echo "silentstar: starting web server at http://${SILENTSTAR_HOST}:${SILENTSTAR_PORT}"
echo "silentstar: repo root ${REPO_ROOT}"

exec "${PHP_BIN}" -S "${SILENTSTAR_HOST}:${SILENTSTAR_PORT}" -t "${REPO_ROOT}/web"
