#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/opt/tapdash-swarm"
SYSTEMD_DIR="/etc/systemd/system"
DATA_DIR="/var/lib/tapdash"
LOG_DIR="/var/log/tapdash"
SERVICE_USER="tapdash"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run with sudo: sudo bash $0"
  exit 1
fi

echo "--- 1. Creating service user and directories ---"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd -r -s /usr/sbin/nologin "$SERVICE_USER"
fi
mkdir -p "$DATA_DIR/pipeline_out" "$DATA_DIR/intake_state" "$DATA_DIR/monitor" "$DATA_DIR/agent-relay" "$LOG_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR" "$LOG_DIR" "$PROJECT_DIR"

echo "--- 2. Installing Systemd Services ---"
SERVICES=(
  "tapdash-email-intake.service"
  "tapdash-review-actions.service"
  "tapdash-pipeline-daemon.service"
  "tapdash-intake-processor.service"
  "tapdash-crm-enrichment.service"
  "tapdash-monitor.service"
)

for svc in "${SERVICES[@]}"; do
  echo "Installing $svc..."
  cp "$PROJECT_DIR/deploy/systemd/$svc" "$SYSTEMD_DIR/$svc"
  chmod 644 "$SYSTEMD_DIR/$svc"
done

echo "--- 3. Reloading and Starting Services ---"
systemctl daemon-reload

for svc in "${SERVICES[@]}"; do
  echo "Enabling and restarting $svc..."
  systemctl enable "$svc"
  systemctl restart "$svc"
done

echo "--- DONE ---"
echo "All 6 services have been installed and started for user '${SERVICE_USER}'."
echo "Monitor log: tail -f ${LOG_DIR}/swarm_monitor.log"
