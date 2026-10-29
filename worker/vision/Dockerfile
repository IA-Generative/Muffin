# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project
COPY app ./app
RUN uv sync --no-dev

# Florence-2 base, from Microsoft's own Hugging Face repository, at a pinned revision: the weights (safetensors) are
# checked against their SHA-256, and so are the three files of Python that transformers runs to build the model
# (`trust_remote_code`). The pod never downloads anything when it runs: transformers is told to read local files only.
FROM builder AS model
ARG MODEL_REPO=microsoft/Florence-2-base
ARG MODEL_REVISION=5ca5edf5bd017b9919c05d08aebef5e4c7ac3bac
ARG WEIGHTS_SHA256=03075d2d2d2bbd3e180b9ba0afae4aa8563226e2d32911656966e05b2f2ee060
ARG CONFIGURATION_SHA256=de2e45a975b3582de05d2f4d963a3e9f9a3d20dccf78d28e0052932a0be93bdf
ARG MODELING_SHA256=5162bf465e61b6e29cc113a467630ec3cb56ed8e4d46eb6207157f10fb9b8a24
ARG PROCESSING_SHA256=f146023a507c009f425a49ee39aa037f4f25c64e14336e3e4f3f1d7377a68e98
RUN /app/.venv/bin/python -c "\
from huggingface_hub import snapshot_download; \
snapshot_download('${MODEL_REPO}', revision='${MODEL_REVISION}', local_dir='/models/Florence-2-base', \
allow_patterns=['model.safetensors', 'config.json', 'preprocessor_config.json', 'tokenizer.json', \
'tokenizer_config.json', 'vocab.json', 'configuration_florence2.py', 'modeling_florence2.py', \
'processing_florence2.py'])" \
    && echo "${WEIGHTS_SHA256}  /models/Florence-2-base/model.safetensors" | sha256sum -c - \
    && echo "${CONFIGURATION_SHA256}  /models/Florence-2-base/configuration_florence2.py" | sha256sum -c - \
    && echo "${MODELING_SHA256}  /models/Florence-2-base/modeling_florence2.py" | sha256sum -c - \
    && echo "${PROCESSING_SHA256}  /models/Florence-2-base/processing_florence2.py" | sha256sum -c - \
    && rm -rf /models/Florence-2-base/.cache

FROM python:3.12-slim AS runtime
# pip is a build tool: the runtime image never installs anything, and the pip bundled with the base
# image carries known CVEs. Removed rather than upgraded, so there is nothing left to keep patched.
RUN python -m pip uninstall -y pip
RUN useradd --create-home --uid 1000 worker
WORKDIR /app
COPY --from=builder --chown=worker:worker /app/.venv /app/.venv
COPY --from=builder --chown=worker:worker /app/app /app/app
COPY --from=model --chown=worker:worker /models /models

USER worker
ENV PATH="/app/.venv/bin:$PATH"
# HOME is where the libraries keep their small working files: /tmp, the one writable place on a read-only root
# filesystem. Nothing looks for a model hoster: the model is in the image.
ENV HOME=/tmp
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1
ENV MODELS_DIR=/models
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD celery -A app.celery_app inspect ping -d celery@$$HOSTNAME || exit 1
# The model is loaded once per child process (about 2 GB of memory each): the concurrency is kept low, and
# TORCH_THREADS is the CPUs the pod is given divided by it. Inference is the slowest step of the chain on CPU.
CMD ["celery", "-A", "app.celery_app", "worker", "--loglevel=info", "-Q", "document_vision", "-c", "1"]
