# SPDX-License-Identifier: Apache-2.0
FROM node:22-bookworm-slim AS build
WORKDIR /src
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable
# pnpm-workspace.yaml carries the build-script allowlist (esbuild only); pnpm 12 refuses others.
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM nginxinc/nginx-unprivileged:1.30-alpine
# Pick up Alpine security fixes published after the base image was built, then drop back to the nginx user.
USER root
RUN apk upgrade --no-cache
USER 101
COPY deploy/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/docker/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --chmod=0755 deploy/docker/40-dewpoint-real-ip.sh /docker-entrypoint.d/40-dewpoint-real-ip.sh
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 8080
