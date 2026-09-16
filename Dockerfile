# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.10-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Compile the C++ extension
RUN pip install --no-cache-dir .

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1
ARG APP_PORT

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg lsb-release \
    && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
        > /etc/apt/sources.list.d/docker.list && \
    apt-get update && apt-get install -y --no-install-recommends docker-ce-cli && \
    apt-get purge -y --auto-remove curl gnupg lsb-release && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed Python packages and the compiled extension from builder
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app .

# Run as a non-root user. UID/GID are configurable (default 1000) so they can
# be matched to the host user in dev setups that bind-mount the repo into
# /app (docker-compose.yml's ".:/app") — otherwise the container user can't
# write to host-owned paths like biocypher-log/ under the bind mount.
# The docker-ce-cli install above creates a "docker" group whose members can
# talk to a mounted /var/run/docker.sock (used by
# app/services/mork_cli_generator.py when that socket is present) without
# needing to run the whole app as root.
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd -f docker \
    && groupadd -r -g ${APP_GID} appuser && useradd -r -u ${APP_UID} -g appuser -G docker -m appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE $APP_PORT
CMD uvicorn app.main:socket_app --host 0.0.0.0 --port $APP_PORT