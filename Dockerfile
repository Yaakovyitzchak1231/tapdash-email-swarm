FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Default ports; override via env if needed
ENV PORT=8080
ENV REVIEW_PORT=8090
ENV CRM_PORT=8095

# SERVICE_ROLE controls process profile:
# - pipeline (default): existing multi-process pipeline stack
# - swarm_worker: LangGraph swarm worker loop only
CMD ["bash", "/app/start_services.sh"]
