# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
WORKDIR /app
ENV UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY app ./app

# Two works from the Hugging Face hub, each at a pinned revision, each file checked against a SHA-256 committed in this
# repository (`sha256sum -c`: a different file fails the build). The pod never downloads anything when it runs.
#  - KittenML/kitten-tts-2: the language model (ONE weights variant, see WEIGHTS), the tokenizer, the voices, the speaker
#    encoder, the optional distilled decoder and the LICENSE.md of the weights. NOT the `cpp/` bundle nor the 3.4 GB
#    bf16 `lm/model.safetensors`.
#  - ResembleAI/chatterbox-turbo (MIT): `s3gen_meanflow.safetensors`, the audio codec that kittenml fetches from the hub
#    on first use. Stored in the hub cache layout so that the library finds it offline.
FROM builder AS model
ARG WEIGHTS=packed
ARG KITTEN_REPO=KittenML/kitten-tts-2
ARG KITTEN_REVISION=c93cb7c271baa51d9ae8204d5277988906f235a2
ARG S3GEN_REPO=ResembleAI/chatterbox-turbo
ARG S3GEN_REVISION=749d1c1a46eb10492095d68fbcf55691ccf137cd
COPY weights.sha256 s3gen.sha256 ./
COPY scripts/fetch_weights.py ./scripts/fetch_weights.py
RUN case "${WEIGHTS}" in \
      packed) other=lm/model-tl2-emb4.safetensors ;; \
      emb4) other=lm/model-ternary.safetensors ;; \
      *) echo "WEIGHTS must be packed or emb4 (the 3.4 GB bf16 'full' variant is not shipped)" >&2; exit 1 ;; \
    esac \
    && grep -v "  ${other}\$" weights.sha256 > weights.selected.sha256 \
    && /app/.venv/bin/python scripts/fetch_weights.py "${KITTEN_REPO}" "${KITTEN_REVISION}" weights.selected.sha256 \
        --local-dir /models/kitten-tts-2 \
    && (cd /models/kitten-tts-2 && sha256sum --check --quiet --strict /app/weights.selected.sha256) \
    && rm -rf /models/kitten-tts-2/.cache
RUN /app/.venv/bin/python scripts/fetch_weights.py "${S3GEN_REPO}" "${S3GEN_REVISION}" s3gen.sha256 --cache-dir /models/hf \
    && (cd /models/hf/models--ResembleAI--chatterbox-turbo/snapshots/${S3GEN_REVISION} \
        && sha256sum --check --quiet --strict /app/s3gen.sha256)

FROM python:3.12-slim AS runtime
# pip is a build tool: the runtime image never installs anything, and the pip bundled with the base
# image carries known CVEs. Removed rather than upgraded, so there is nothing left to keep patched.
RUN python -m pip uninstall -y pip
RUN useradd --create-home --uid 1000 worker
WORKDIR /app
COPY --from=builder --chown=worker:worker /app/.venv /app/.venv
COPY --from=builder --chown=worker:worker /app/app /app/app
COPY --from=model --chown=worker:worker /models /models
COPY --chown=worker:worker LICENSES.md NOTICE /app/
ARG WEIGHTS=packed

USER worker
ENV PATH="/app/.venv/bin:$PATH"
# HOME is where the libraries keep their small working files: /tmp, the one writable place on a read-only root
# filesystem. Nothing looks for a model hoster: the models are in the image.
ENV HOME=/tmp
ENV NUMBA_CACHE_DIR=/tmp/numba
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1
ENV HF_HUB_CACHE=/models/hf
ENV TTS_MODEL_DIR=/models/kitten-tts-2
ENV TTS_WEIGHTS=${WEIGHTS}
EXPOSE 8080
# Loading the model takes a while (about a minute on a fast CPU, several on a slow one): /health answers 503 until it is
# there, and the start period keeps that from counting as a failure.
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=5)"]
# One process: the model is in its memory, and the concurrency is the service's own (TTS_MAX_CONCURRENCY).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header"]
