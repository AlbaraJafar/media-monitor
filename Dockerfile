FROM python:3.11-slim

WORKDIR /app

# system deps for trafilatura / lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Large wheels (torch is ~195 MB) over a slow link can be cut off mid-download; the
# pip bundled with this base image (24.0) then fails with a misleading "hash
# mismatch" and never retries (--retries only covers opening a connection). pip
# >= 25.1 can resume or restart an incomplete download, so pin a version that can.
RUN pip install --no-cache-dir --disable-pip-version-check "pip==26.2.1"
COPY requirements.txt .
RUN pip install --no-cache-dir --resume-retries 10 --retries 10 --timeout 60 -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY eval ./eval

EXPOSE 8000

# --reload is for local dev only (source is bind-mounted); drop it in production.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "app"]
