#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/opt/tapdash-swarm"
ENV_FILE="/etc/tapdash/swarm.env"
DATA_DIR="/var/lib/tapdash"
SYSTEMD_DIR="/etc/systemd/system"
LOG_DIR="/var/log/tapdash"
SERVICE_USER="tapdash"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/install_services.sh"
  exit 1
fi

if [[ ! -d "${PROJECT_DIR}" ]]; then
  echo "Missing project directory: ${PROJECT_DIR}"
  exit 1
fi

if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd -r -s /usr/sbin/nologin "${SERVICE_USER}"
fi

mkdir -p "${DATA_DIR}/pipeline_out" "${DATA_DIR}/intake_state" /etc/tapdash "${LOG_DIR}"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${DATA_DIR}" "${LOG_DIR}" "${PROJECT_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}"
  echo "Create it from deploy/swarm.env.example"
  exit 1
fi

install -m 0644 "${PROJECT_DIR}/deploy/systemd/tapdash-email-intake.service" "${SYSTEMD_DIR}/tapdash-email-intake.service"
install -m 0644 "${PROJECT_DIR}/deploy/systemd/tapdash-review-actions.service" "${SYSTEMD_DIR}/tapdash-review-actions.service"
install -m 0644 "${PROJECT_DIR}/deploy/systemd/tapdash-pipeline-daemon.service" "${SYSTEMD_DIR}/tapdash-pipeline-daemon.service"
install -m 0644 "${PROJECT_DIR}/deploy/systemd/tapdash-intake-processor.service" "${SYSTEMD_DIR}/tapdash-intake-processor.service"
install -m 0644 "${PROJECT_DIR}/deploy/systemd/tapdash-crm-enrichment.service" "${SYSTEMD_DIR}/tapdash-crm-enrichment.service"
install -m 0644 "${PROJECT_DIR}/deploy/systemd/tapdash-monitor.service" "${SYSTEMD_DIR}/tapdash-monitor.service"

systemctl daemon-reload
systemctl enable --now tapdash-email-intake.service
systemctl enable --now tapdash-review-actions.service
systemctl enable --now tapdash-pipeline-daemon.service
systemctl enable --now tapdash-intake-processor.service
systemctl enable --now tapdash-crm-enrichment.service
systemctl enable --now tapdash-monitor.service

echo "Installed and started:"
echo "  - tapdash-email-intake.service"
echo "  - tapdash-review-actions.service"
echo "  - tapdash-pipeline-daemon.service"
echo "  - tapdash-intake-processor.service"
echo "  - tapdash-crm-enrichment.service"
echo "  - tapdash-monitor.service"
