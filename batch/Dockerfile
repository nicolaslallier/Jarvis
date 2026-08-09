FROM python:3.12-slim

WORKDIR /app

# Build context is the repo root (see docker-compose.yml) so this stage can
# reach shared/, the jarvis_shared package used by backend/batch/ingest.
COPY shared ./shared
RUN pip install --no-cache-dir ./shared

COPY batch/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY batch/app ./app

RUN useradd --create-home appuser
USER appuser

EXPOSE 8080

CMD ["python", "-m", "app.main"]
