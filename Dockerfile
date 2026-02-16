FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8080
ENV REVIEW_PORT=8090
ENV CRM_PORT=8095
CMD bash -lc "python3 email_work_order_service.py & python3 review_actions_service.py & python3 pipeline_daemon.py --interval-seconds 10; wait"
