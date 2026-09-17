# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project
COPY app ./app
RUN uv sync --no-dev

FROM python:3.12-slim AS runtime
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
USER worker
ENV PATH="/app/.venv/bin:$PATH"
ENV TESSDATA_PATH="/usr/share/tesseract-ocr/5/tessdata"
CMD ["celery", "-A", "app.celery_app", "worker", "--loglevel=info"]
