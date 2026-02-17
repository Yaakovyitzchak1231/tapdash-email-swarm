#!/usr/bin/env bash
set -euo pipefail

ROLE="${SERVICE_ROLE:-pipeline}"
PIPELINE_DIR="${PIPELINE_DIR:-/data/pipeline_out}"
INTAKE_STATE_DIR="${INTAKE_STATE_DIR:-/data/intake_state}"

mkdir -p "${PIPELINE_DIR}" "${INTAKE_STATE_DIR}"

if [[ "${ROLE}" == "swarm_worker" ]]; then
  exec python3 swarm_worker_runner.py --interval-seconds "${SWARM_INTERVAL_SECONDS:-10}"
fi

exec bash -lc "\
  python3 email_work_order_service.py & \
  python3 review_actions_service.py & \
  python3 intake_stream_processor.py --interval-seconds 10 & \
  python3 pipeline_daemon.py --interval-seconds 10 & \
  python3 publish_sender.py & \
  wait \
"
