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

# 1 worker + 8 threads: keeps the in-process SSE pub/sub (hub.py) on a single address space so
# background threads and SSE streams share the same queue. Long-lived SSE streams hold a thread
# each; 8 threads comfortably handles the single admin user + spare capacity for regular API calls.
# If multiple Railway replicas or high SSE concurrency is ever needed, migrate hub.py to Redis pub/sub.
# --timeout 120 prevents Gunicorn from killing threads during long snap/detection runs.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8", "--timeout", "120", "app:create_app()"]
