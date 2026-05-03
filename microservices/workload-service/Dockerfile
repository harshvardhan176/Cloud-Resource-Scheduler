FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Don't run as root in production
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 5000

# gunicorn is a production WSGI server. 4 workers handle concurrent requests.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", \
     "--timeout", "30", "app.main:app"]
