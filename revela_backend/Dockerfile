ARG PYTHON_BASE_IMAGE=docker.io/library/python:3.13-slim-bookworm
FROM ${PYTHON_BASE_IMAGE}

ARG MYSQL_APT_COMPONENT=mysql-9.7-lts
ARG MYSQL_CLIENT_VERSION=9.7.4-1debian12

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DB_BACKUP_ENABLED=0
ENV DB_BACKUP_SCHEDULE_ENABLED=0
ENV DB_BACKUP_CLEANUP_ENABLED=0
ENV DB_BACKUP_EXTERNAL_TRIGGER_ENABLED=0
ENV DB_BACKUP_STORAGE=volume
ENV DB_BACKUP_ROLE=api
ENV DB_BACKUP_SCHEDULER_MODE=external_api
ENV DB_BACKUP_VOLUME_DIR=/app/instance/inspection_evidence
ENV DB_BACKUP_VOLUME_REQUIRE_MOUNT=1
ENV MYSQLDUMP_BIN=/usr/bin/mysqldump

# Install system dependencies for mysqlclient compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    default-libmysqlclient-dev \
    pkg-config \
    ca-certificates \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install a pinned Oracle MySQL client; the runtime exporter checks its major
# version against the live source before enabling scheduled execution.
RUN set -eu; \
    test -n "$MYSQL_APT_COMPONENT"; \
    test -n "$MYSQL_CLIENT_VERSION"; \
    curl --fail --silent --show-error --location --retry 3 \
        --proto '=https' --proto-redir '=https' \
        https://repo.mysql.com/RPM-GPG-KEY-mysql-2025 -o /tmp/mysql-release.asc; \
    fingerprint="$(gpg --batch --show-keys --with-colons /tmp/mysql-release.asc | awk -F: '$1 == "fpr" { print $10; exit }')"; \
    test "$fingerprint" = BCA43417C3B485DD128EC6D4B7B3B788A8D3785C; \
    gpg --batch --dearmor --output /usr/share/keyrings/mysql.gpg /tmp/mysql-release.asc; \
    printf 'deb [signed-by=/usr/share/keyrings/mysql.gpg] https://repo.mysql.com/apt/debian/ bookworm %s\n' "$MYSQL_APT_COMPONENT" > /etc/apt/sources.list.d/mysql.list; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        "mysql-community-client=$MYSQL_CLIENT_VERSION"; \
    test "$(dpkg-query -W -f='${Version}' mysql-community-client)" = "$MYSQL_CLIENT_VERSION"; \
    mysqldump --no-defaults --version; \
    rm -f /tmp/mysql-release.asc; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN mkdir -p /app/instance/inspection_evidence

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir gunicorn

# Copy application source code
COPY . .

# Verify the configured dump executable is the pinned Oracle client.
RUN python -c "from recovery.mysqltools import check_dump_client; check_dump_client('/usr/bin/mysqldump', '${MYSQL_CLIENT_VERSION}')"

EXPOSE 5000

# 1 worker + 16 threads (gthread): keeps the in-process SSE pub/sub (hub.py) on a single address space
# so background threads and SSE clients share memory queues without requiring external message brokers.
# Each persistent SSE client holds one thread for its duration; 16 threads provides expanded headroom
# for SSE streams alongside concurrent REST API requests. (Multi-replica scaling requires Redis pub/sub.)
# --timeout 120 serves as a worker-liveness threshold: with gthread, Gunicorn monitors worker process
# heartbeats rather than per-request deadlines (individual request threads and detached daemon threads
# continue running while the worker heartbeats). 120s gives an unresponsive or blocked worker process
# sufficient leeway before the master arbiter considers it dead and restarts it.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-5000} --workers 1 --threads 16 --timeout 120 'app:create_app()'"]
