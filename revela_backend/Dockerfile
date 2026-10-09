FROM python:3.13-slim

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies for mysqlclient compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir gunicorn

# Copy application source code
COPY . .

EXPOSE 5000

# 1 worker + 16 threads (gthread): keeps the in-process SSE pub/sub (hub.py) on a single address space
# so background threads and SSE clients share memory queues without requiring external message brokers.
# Each persistent SSE client holds one thread for its duration; 16 threads provides expanded headroom
# for SSE streams alongside concurrent REST API requests. (Multi-replica scaling requires Redis pub/sub.)
# --timeout 120 serves as a worker-liveness threshold: with gthread, Gunicorn monitors worker process
# heartbeats rather than per-request deadlines (individual request threads and detached daemon threads
# continue running while the worker heartbeats). 120s gives an unresponsive or blocked worker process
# sufficient leeway before the master arbiter considers it dead and restarts it.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "16", "--timeout", "120", "app:create_app()"]
