FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir curl_cffi 2>/dev/null || true

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

RUN adduser --disabled-password --gecos '' appuser
RUN mkdir -p /app/data && chown appuser:appuser /app/data

COPY app.py spreadsheet.py email_parser.py ./
COPY templates/ templates/
COPY static/ static/
COPY scripts/ scripts/

USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:5000/login || exit 1

CMD ["gunicorn", "-b", "0.0.0.0:5000", "-w", "1", "--timeout", "120", "app:app"]
