# Contributing

- Sign off every commit (Developer Certificate of Origin): `git commit -s`.
- Every source file starts with an SPDX header: `# SPDX-License-Identifier: Apache-2.0`
  (or `// SPDX-License-Identifier: Apache-2.0` in TypeScript).
- Backend: `cd backend && uv run ruff check . && uv run mypy src && uv run lint-imports && uv run pytest`
  (tests need a running Docker daemon for the PostgreSQL test container).
- Frontend: `cd frontend && pnpm lint && pnpm typecheck && pnpm test`.
