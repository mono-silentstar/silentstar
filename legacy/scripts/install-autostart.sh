#!/usr/bin/env bash
set -euo pipefail

if ! command -v systemctl >/dev/null 2>&1; then
  echo "silentstar: systemd is not available on this machine." >&2
  echo "silentstar: use scripts/silentstar-start.sh with your platform scheduler." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_PATH="${UNIT_DIR}/silentstar.service"
REPO_ROOT_ESCAPED="$(printf '%q' "${REPO_ROOT}")"
START_SCRIPT_ESCAPED="$(printf '%q' "${REPO_ROOT}/scripts/silentstar-start.sh")"

mkdir -p "${UNIT_DIR}"

cat > "${UNIT_PATH}" <<EOF
[Unit]
Description=silentstar web service
After=network.target

[Service]
Type=simple
WorkingDirectory=${REPO_ROOT}
Environment=PHP_BIN=${PHP_BIN:-php}
Environment=SILENTSTAR_HOST=${SILENTSTAR_HOST:-127.0.0.1}
Environment=SILENTSTAR_PORT=${SILENTSTAR_PORT:-8080}
ExecStart=/usr/bin/env bash -lc 'cd ${REPO_ROOT_ESCAPED} && exec ${START_SCRIPT_ESCAPED}'
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now silentstar.service

echo "silentstar: installed ${UNIT_PATH}"
echo "silentstar: service enabled and started for this user."
echo "silentstar: for boot without login, run:"
echo "  sudo loginctl enable-linger $(whoami)"
