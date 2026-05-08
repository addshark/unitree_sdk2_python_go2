#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SERVICE_NAME="go2-udp-control.service"
SERVICE_USER="${SERVICE_USER:-unitree}"
TEMPLATE_PATH="${SCRIPT_DIR}/go2_udp_control.service.template"
TARGET_SERVICE="/etc/systemd/system/${SERVICE_NAME}"
TARGET_ENV="/etc/default/go2-udp-control"
TMP_SERVICE="$(mktemp)"

cleanup() {
  rm -f "${TMP_SERVICE}"
}
trap cleanup EXIT

if [[ ! -f "${TEMPLATE_PATH}" ]]; then
  echo "Template not found: ${TEMPLATE_PATH}" >&2
  exit 1
fi

sed \
  -e "s|@REPO_ROOT@|${REPO_ROOT}|g" \
  -e "s|@SERVICE_USER@|${SERVICE_USER}|g" \
  "${TEMPLATE_PATH}" > "${TMP_SERVICE}"

sudo install -m 644 "${TMP_SERVICE}" "${TARGET_SERVICE}"

if [[ ! -f "${TARGET_ENV}" ]]; then
  sudo install -m 644 "${SCRIPT_DIR}/go2_udp_control.env.example" "${TARGET_ENV}"
  echo "Created ${TARGET_ENV} from example."
else
  echo "Keeping existing ${TARGET_ENV}."
fi

sudo systemctl daemon-reload
sudo systemctl enable --now "${SERVICE_NAME}"
sudo systemctl status --no-pager "${SERVICE_NAME}"

echo
echo "Service installed: ${SERVICE_NAME}"
echo "Edit config: sudo nano ${TARGET_ENV}"
echo "Restart service: sudo systemctl restart ${SERVICE_NAME}"
echo "View logs: sudo journalctl -u ${SERVICE_NAME} -f"
