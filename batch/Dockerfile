FROM python:3.12-slim

WORKDIR /app

# Build context is the repo root (see docker-compose.yml) so this stage can
# reach shared/, the jarvis_shared package used by backend/batch/ingest.
COPY shared ./shared
RUN pip install --no-cache-dir ./shared

COPY batch/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY batch/app ./app

# Stays root: this container talks to /var/run/docker.sock (see
# docker-compose.yml's `batch` service and CLAUDE.md's security note),
# and a non-root user without a group matching the mounted socket's host
# GID gets PermissionError connecting to it. Docker socket access is
# root-equivalent regardless of in-container UID, so dropping privilege
# here buys no real isolation anyway.

EXPOSE 8080

CMD ["python", "-m", "app.main"]
