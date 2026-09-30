FROM python:3.11-slim

WORKDIR /app

# system deps for trafilatura / lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY eval ./eval

EXPOSE 8000

# --reload is for local dev only (source is bind-mounted); drop it in production.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "app"]
