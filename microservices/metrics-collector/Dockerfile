FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN useradd -m appuser && chown -R appuser /app
USER appuser

# No EXPOSE — this service has no HTTP API
CMD ["python", "-u", "app/main.py"]
