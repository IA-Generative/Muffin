# syntax=docker/dockerfile:1

FROM node:26-alpine AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

# nginxinc/nginx-unprivileged already runs as the unprivileged `nginx` user
# (uid 101) and listens on 8080 instead of 80, so no extra USER/port setup
# is required to get a non-root container.
FROM nginxinc/nginx-unprivileged:1.31-alpine AS runtime
# The base image only gets rebuilt now and then: pull in the Alpine fixes published since (openssl,
# zlib, musl...). It needs root, which the base image doesn't run as - dropped again right after.
USER root
RUN apk upgrade --no-cache
COPY --chown=nginx:nginx docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --chown=nginx:nginx --from=build /app/dist /usr/share/nginx/html
# Explicit rather than inherited from the base image: same user as before (nginx, uid 101), but
# visible to scanners (Trivy DS-0002 can't see an inherited USER).
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://localhost:8080/ >/dev/null || exit 1
