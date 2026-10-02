# SPDX-License-Identifier: Apache-2.0
# The isolated CEL evaluator (spec §5.7): only the runtime, protobuf and dewpoint.engine.cel, at the locked versions,
# with the pure modules it imports (engine.canonical, and engine.handles for bindings that hold handles; both standard
# library only). A test checks every Dewpoint module the evaluator loads is copied here.
# No database driver, no web framework, no Temporal SDK: the evaluator imports none of them (import-linter contract).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY backend/pyproject.toml backend/uv.lock ./
# The two locked requirements, with their hashes: each entry is its `name==version \` line plus hash lines.
RUN uv export --locked --no-dev --no-emit-project --no-header --no-annotate > all.txt \
 && awk '/^(cel-expr-python|protobuf)==/{keep=1} keep{print} keep && !/\\$/{keep=0}' all.txt > requirements.txt \
 && test "$(grep -cE '^(cel-expr-python|protobuf)==' requirements.txt)" = 2 \
 && uv venv /app/.venv \
 && uv pip install --python /app/.venv/bin/python --require-hashes --no-deps -r requirements.txt
COPY backend/src/dewpoint/__init__.py src/dewpoint/__init__.py
COPY backend/src/dewpoint/apps/__init__.py src/dewpoint/apps/__init__.py
COPY backend/src/dewpoint/apps/cel_evaluator src/dewpoint/apps/cel_evaluator
COPY backend/src/dewpoint/engine/__init__.py backend/src/dewpoint/engine/canonical.py backend/src/dewpoint/engine/handles.py src/dewpoint/engine/
COPY backend/src/dewpoint/engine/cel src/dewpoint/engine/cel
RUN /app/.venv/bin/python -m compileall -q src

FROM python:3.12-slim-bookworm
# Pick up Debian security fixes published after the base image was built.
RUN apt-get update && apt-get -y upgrade --no-install-recommends && rm -rf /var/lib/apt/lists/*
# Its own user, distinct from the app's 10001; the socket directory is the mount point of the shared volume.
RUN useradd --uid 10002 --no-create-home --shell /usr/sbin/nologin dewpoint-cel \
 && mkdir /run/dewpoint-cel && chown 10002:10002 /run/dewpoint-cel
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/src /app/src
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10002
CMD ["python", "-m", "dewpoint.apps.cel_evaluator"]
