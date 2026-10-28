# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project
COPY app ./app
RUN uv sync --no-dev

FROM python:3.12-slim AS runtime
# pip is a build tool: the runtime image never installs anything, and the pip bundled with the base
# image carries known CVEs. Removed rather than upgraded, so there is nothing left to keep patched.
RUN python -m pip uninstall -y pip
# tesseract-ocr-fra: liteparse bundles its own OCR engine, but not language
# data - this is what makes ocr_language="fra" actually work.
# libreoffice: liteparse shells out to it to convert docx/xlsx/pptx/odt to a
# renderable form before parsing.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr-fra \
    libreoffice \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 worker
WORKDIR /app
COPY --from=builder --chown=worker:worker /app/.venv /app/.venv
COPY --from=builder --chown=worker:worker /app/app /app/app

# HOME is on the one writable place of a read-only root filesystem. DuckDB, which reads the JSON and Parquet files on
# the local disk with the extensions it ships with, installs and loads nothing: it has neither httpfs nor spatial.
ENV HOME=/tmp

USER worker
ENV PATH="/app/.venv/bin:$PATH"
ENV TESSDATA_PATH="/usr/share/tesseract-ocr/5/tessdata"
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD celery -A app.celery_app inspect ping -d celery@$HOSTNAME || exit 1
# One image, three pods (#291), each started with its own queues - this default is the extraction
# one; the enrichment and import/rebuild pods override it (docker-compose.yaml, Helm values).
# document_processing, the queue before #291, is drained for one release.
# -B: it also runs the beat that triggers the scheduled refresh of URL documents (#19) - no extra
# service to deploy. With several replicas each runs its own, which is harmless: the backend hands
# each due document to one scan only. The schedule file lives in /tmp, the one writable place on a
# read-only root filesystem.
CMD ["celery", "-A", "app.celery_app", "worker", "-B", "--schedule=/tmp/celerybeat-schedule", "--loglevel=info", \
     "-Q", "document_extraction,document_processing"]
