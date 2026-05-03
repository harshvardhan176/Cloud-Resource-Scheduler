FROM python:3.11-slim

WORKDIR /app

# System packages needed for torch wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Install torch CPU first to avoid pulling CUDA
RUN pip install --no-cache-dir torch==2.2.0 \
    --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir flask==3.0.0 gunicorn==21.2.0 \
    boto3==1.34.0 numpy==1.26.4 stable-baselines3==2.2.1

COPY app/ ./app/

RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 5002

# Single worker — the model is loaded into memory and 4 copies wastes RAM
CMD ["gunicorn", "--bind", "0.0.0.0:5002", "--workers", "1", \
     "--timeout", "60", "--preload", "app.main:app"]
