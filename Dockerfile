FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Default ports; override via env if needed
ENV PORT=8080
ENV REVIEW_PORT=8090
ENV CRM_PORT=8095

# Run all core processes in one container so they can share the attached volume
# for state (work_orders, intake_state, pipeline_out).
CMD bash -lc "\
  mkdir -p ${PIPELINE_DIR:-/data/pipeline_out} ${INTAKE_STATE_DIR:-/data/intake_state} && \
  python3 email_work_order_service.py & \
  python3 review_actions_service.py & \
  python3 intake_stream_processor.py --interval-seconds 10 & \
  python3 pipeline_daemon.py --interval-seconds 10 & \
  wait \
"
