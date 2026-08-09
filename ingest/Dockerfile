FROM python:3.12-slim

WORKDIR /app

COPY shared ./shared
RUN pip install --no-cache-dir ./shared

COPY ingest/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ingest/app ./app

RUN useradd --create-home appuser
USER appuser

# No EXPOSE — this container has no HTTP surface. It runs one ingestion
# pass and exits; docker-compose.yml's `restart: "no"` leaves it "Exited"
# until batch's ingest_trigger job starts it again.
CMD ["python", "-m", "app.main"]
