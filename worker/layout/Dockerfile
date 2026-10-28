# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project
COPY app ./app
RUN uv sync --no-dev

# The model comes from PaddlePaddle's own Hugging Face organization (its official ONNX export), at a pinned
# revision and checked against its hash: the pod never downloads anything when it runs.
FROM builder AS model
ARG LAYOUT_MODEL_REPO=PaddlePaddle/PP-DocLayoutV3_onnx
ARG LAYOUT_MODEL_REVISION=46bbdf188bb0a772c08aed74882ce7e51a8f1ea6
ARG LAYOUT_MODEL_SHA256=45bf71750b00739a41fc209f132eb104a4d6b5bb29483c9078164d8b87cf28ba
RUN /app/.venv/bin/python -c "\
from huggingface_hub import snapshot_download; \
snapshot_download('${LAYOUT_MODEL_REPO}', revision='${LAYOUT_MODEL_REVISION}', \
local_dir='/models/PP-DocLayoutV3_onnx', allow_patterns=['inference.onnx', 'inference.yml'])" \
    && echo "${LAYOUT_MODEL_SHA256}  /models/PP-DocLayoutV3_onnx/inference.onnx" | sha256sum -c - \
    && rm -rf /models/PP-DocLayoutV3_onnx/.cache

FROM python:3.12-slim AS runtime
# pip is a build tool: the runtime image never installs anything, and the pip bundled with the base
# image carries known CVEs. Removed rather than upgraded, so there is nothing left to keep patched.
RUN python -m pip uninstall -y pip
# OpenCV (a dependency of PaddleOCR) loads these two at import.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 worker
WORKDIR /app
COPY --from=builder --chown=worker:worker /app/.venv /app/.venv
COPY --from=builder --chown=worker:worker /app/app /app/app
COPY --from=model --chown=worker:worker /models /models

USER worker
ENV PATH="/app/.venv/bin:$PATH"
# HOME is where PaddleOCR keeps its small working files: /tmp, the one writable place on a read-only root
# filesystem. It looks for no model hoster (the model is in the image).
ENV HOME=/tmp
ENV PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
ENV MODELS_DIR=/models
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD celery -A app.celery_app inspect ping -d celery@$$HOSTNAME || exit 1
# The model is loaded once per child process: keep the concurrency to what the pod's memory allows (about
# 1 GB each), and ONNX_INTRA_OP_THREADS to the CPUs the pod is given divided by it.
CMD ["celery", "-A", "app.celery_app", "worker", "--loglevel=info", "-Q", "document_layout", "-c", "2"]
