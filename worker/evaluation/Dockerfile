# syntax=docker/dockerfile:1

# Pinned, never "latest": the results.json/report.html format the task parses and the
# YAML options it generates must stay stable across builds.
ARG PROMPTFOO_VERSION=0.124.1

# promptfoo is a Node CLI: installed once here, from the official Node image so the
# runtime controls the version, then copied over. No npx --yes anywhere - the runtime
# image never downloads anything.
FROM node:22-slim AS promptfoo
ARG PROMPTFOO_VERSION
RUN npm install --global promptfoo@${PROMPTFOO_VERSION} \
    && npm cache clean --force

FROM python:3.12-slim AS builder
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project
COPY app ./app
RUN uv sync --no-dev

FROM python:3.12-slim AS runtime
# Node's binary links against these; the Python base image doesn't carry them.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 libgcc-s1 \
    && rm -rf /var/lib/apt/lists/*
# pip is a build tool: the runtime image never installs anything, and the pip bundled with the base
# image carries known CVEs. Removed rather than upgraded, so there is nothing left to keep patched.
RUN python -m pip uninstall -y pip
RUN useradd --create-home --uid 1000 worker
WORKDIR /app
COPY --from=builder --chown=worker:worker /app/.venv /app/.venv
COPY --from=builder --chown=worker:worker /app/app /app/app
COPY --from=promptfoo /usr/local/bin/node /usr/local/bin/node
COPY --from=promptfoo /usr/local/lib/node_modules /usr/local/lib/node_modules
# npm's bin is a relative symlink into the package - COPY would dereference it into a
# plain file whose relative imports then resolve next to the bin and fail
# (ERR_MODULE_NOT_FOUND on its sibling modules). Recreate the symlink instead.
RUN ln -s ../lib/node_modules/promptfoo/dist/src/entrypoint.js /usr/local/bin/promptfoo
USER worker
ENV PATH="/app/.venv/bin:/usr/local/bin:$PATH"
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD celery -A app.celery_app inspect ping -d celery@$HOSTNAME || exit 1
CMD ["celery", "-A", "app.celery_app", "worker", "--loglevel=info"]
