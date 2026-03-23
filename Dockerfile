FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN adduser --disabled-password --gecos '' appuser
RUN mkdir -p /app/data && chown appuser:appuser /app/data

COPY app.py spreadsheet.py ./
COPY templates/ templates/
COPY static/ static/

USER appuser

EXPOSE 5000

CMD ["gunicorn", "-b", "0.0.0.0:5000", "-w", "1", "--timeout", "120", "app:app"]
