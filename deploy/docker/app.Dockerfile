# SPDX-License-Identifier: Apache-2.0
# Base image note: no distroless image ships Python >= 3.12 on a supported Debian yet; this is slim, non-root,
# without build tools, and meant to run with a read-only root filesystem. Revisit for distroless.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12-slim-bookworm
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin dewpoint
# Mount point for the evaluation anchor volume; a new named volume inherits this ownership.
RUN mkdir /anchors && chown 10001:10001 /anchors
WORKDIR /app
COPY --from=build --chown=10001:10001 /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001
EXPOSE 8000
# --forwarded-allow-ips "*" is acceptable ONLY because `api` is not published and is reachable solely through `web`
# on the internal network. The Helm chart (sub-project 4) sets the exact proxy CIDRs.
CMD ["uvicorn", "dewpoint.apps.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
