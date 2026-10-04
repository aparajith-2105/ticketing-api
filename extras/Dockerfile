FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# run as a non-root user
RUN useradd --create-home appuser && chown -R appuser /srv
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

# One worker: the rate limiter is in-memory and tables are created at startup.
# To scale out, move the limiter to Redis and use Alembic migrations first (see README).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
