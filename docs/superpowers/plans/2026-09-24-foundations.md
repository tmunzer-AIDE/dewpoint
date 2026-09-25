# Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A deployable, multi-tenant skeleton of Dewpoint. It includes:
- local authentication (password, TOTP, passkeys, server-side sessions with CSRF);
- tenants, memberships and permissions, with PostgreSQL RLS as defence in depth;
- envelope encryption;
- generic connections, with a verifiable Mist connection type;
- a tamper-evident audit log with external anchoring;
- a minimal React shell;
- Docker Compose.

**Architecture:** One Python backend package (`dewpoint`) with `core` (domain and services) and `apps` (thin FastAPI and CLI entrypoints). The import rules are enforced by import-linter. PostgreSQL is accessed through SQLAlchemy 2 async and asyncpg; Alembic owns schema, DB roles and RLS policies. The frontend is a separate Vite + React app that talks to `/api/v1`.

**Tech Stack:**
- Backend: Python 3.12, uv, FastAPI, Pydantic v2 / pydantic-settings, SQLAlchemy 2 (async) + asyncpg, Alembic, argon2-cffi, pyotp, webauthn (py_webauthn), cryptography, httpx, typer.
- Backend tests: pytest, pytest-asyncio, testcontainers[postgres], respx, hypothesis.
- Frontend: pnpm, React 19, Vite, TypeScript, TanStack Router and Query, Tailwind CSS v4, Radix UI, @simplewebauthn/browser, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-24-dewpoint-architecture-design.md` (§3, §4, §5, §11, §13, §14 item 1)

## Global Constraints

- License: Apache-2.0. Every source file starts with `# SPDX-License-Identifier: Apache-2.0` (or `// SPDX-License-Identifier: Apache-2.0` in TS).
- Python ≥ 3.12. Node ≥ 22. PostgreSQL ≥ 16.
- No Redis and no Celery. No JWTs in the browser: opaque server-side sessions only.
- The browser never receives secrets. Responses expose `secret_set: bool`, never ciphertext or plaintext.
- Never return `str(exc)` to clients. Log server-side; respond with generic messages.
- Passwords: argon2id. MFA is required by platform policy (`DEWPOINT_MFA_REQUIRED=true` by default).
- Tenant-scoped tables: `tenant_id` column, `ENABLE` + `FORCE ROW LEVEL SECURITY`, and the policy `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`. With no tenant context the result is no rows (fail closed).
- RLS is defence in depth. The authority is the membership and permission check in `api`.
- Tenant scope comes only from the route `/api/v1/t/{tenant_id}/…`, never from request bodies.
- Mist cloud hosts are an allowlist (Task 12). No user-supplied hostnames for Mist.
- UI rule (spec §10.1): no gradients, glow, glassmorphism, sparkle icons, emoji, or default Inter look. Fonts: IBM Plex Sans and IBM Plex Mono, self-hosted through `@fontsource` (the CSP forbids external font hosts).
- Import rules: `dewpoint.core` must not import `dewpoint.apps`. Nothing outside `dewpoint.apps` imports `fastapi` except `dewpoint.core.http` (shared dependencies).
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## File Structure

```
LICENSE, NOTICE, README.md, SECURITY.md, CONTRIBUTING.md, .gitignore, .editorconfig
.github/workflows/ci.yml              # lint, types, tests, import-linter, gitleaks, license check, trivy
.github/workflows/codeql.yml
backend/
  pyproject.toml                      # uv project "dewpoint"; ruff, mypy, pytest, importlinter config
  alembic.ini
  migrations/env.py
  migrations/versions/0001_roles_and_extensions.py
  migrations/versions/0002_identity.py
  migrations/versions/0003_tenancy_rls.py
  migrations/versions/0004_keys.py
  migrations/versions/0005_audit.py
  migrations/versions/0006_connections.py
  src/dewpoint/__init__.py
  src/dewpoint/core/config.py             # Settings (pydantic-settings)
  src/dewpoint/core/db.py                 # engine, session factory, tenant_scope()
  src/dewpoint/core/models/base.py        # Base, UUID pk, timestamps
  src/dewpoint/core/models/identity.py    # User, UserMfa, RecoveryCode, WebauthnCredential, Session, AuthThrottle, WebauthnChallenge
  src/dewpoint/core/models/tenancy.py     # Tenant, Membership
  src/dewpoint/core/models/keys.py        # DataKey
  src/dewpoint/core/models/connections.py # Connection
  src/dewpoint/core/models/audit.py       # AuditEntry, AuditAnchor
  src/dewpoint/core/crypto/kek.py         # KEK provider (env)
  src/dewpoint/core/crypto/keyring.py     # data keys, encrypt/decrypt with AAD, rotation
  src/dewpoint/core/auth/passwords.py     # hash/verify/policy
  src/dewpoint/core/auth/sessions.py      # create/load/touch/revoke sessions, CSRF
  src/dewpoint/core/auth/throttle.py      # rate limit + lockout
  src/dewpoint/core/auth/totp.py          # enroll/verify TOTP, recovery codes
  src/dewpoint/core/auth/passkeys.py      # WebAuthn registration/authentication
  src/dewpoint/core/authz/permissions.py  # Permission enum, ROLE_PERMISSIONS
  src/dewpoint/core/tenancy/service.py    # tenants, memberships
  src/dewpoint/core/audit/service.py      # record(); verify chain
  src/dewpoint/core/audit/anchor.py       # anchor sinks (file, signed)
  src/dewpoint/core/connections/types.py  # ConnectionType registry, Mist type + cloud allowlist
  src/dewpoint/core/connections/service.py# CRUD + verify
  src/dewpoint/core/connections/mist_verify.py
  src/dewpoint/core/http.py               # FastAPI dependencies: db, current session, require()
  src/dewpoint/apps/api/main.py           # create_app()
  src/dewpoint/apps/api/middleware.py     # security headers, CSRF enforcement
  src/dewpoint/apps/api/errors.py         # exception handlers (sanitized)
  src/dewpoint/apps/api/routes/{health,auth,mfa,passkeys,tenants,members,connections,audit}.py
  src/dewpoint/apps/cli/main.py           # typer: admin init, audit anchor/verify, keys status/rewrap/rotate-dek (Task 15)
  tests/conftest.py                       # postgres container, migrations, role engines, client
  tests/...                               # mirrors src
frontend/
  package.json, vite.config.ts, tsconfig.json, index.html, playwright.config.ts
  src/main.tsx, src/router.tsx, src/styles/tokens.css, src/styles/app.css
  src/lib/api.ts, src/lib/session.ts
  src/routes/{login,mfa,enroll,tenants,connections}.tsx
  src/components/{Button,Field,Shell,TenantSwitcher}.tsx
  e2e/login.spec.ts
deploy/compose/docker-compose.yml, deploy/compose/.env.example
deploy/docker/app.Dockerfile, deploy/docker/web.Dockerfile, deploy/docker/nginx.conf
```

---

### Task 1: Repository scaffolding and CI

**Files:**
- Create: `LICENSE` (Apache-2.0 full text), `NOTICE`, `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, `.gitignore`, `.editorconfig`
- Create: `backend/pyproject.toml`, `backend/src/dewpoint/__init__.py`, `backend/src/dewpoint/core/__init__.py`, `backend/src/dewpoint/apps/__init__.py`
- Create: `backend/tests/test_package.py`
- Create: `.github/workflows/ci.yml`, `.github/workflows/codeql.yml`

**Interfaces:**
- Produces: the `dewpoint` package importable from `backend/src`, the `uv run pytest` / `uv run ruff` / `uv run mypy` / `uv run lint-imports` commands, and the CI job names `backend`, `security`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_package.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import dewpoint


def test_package_exposes_version() -> None:
    assert dewpoint.__version__ == "0.1.0"
```

- [ ] **Step 2: Create `backend/pyproject.toml`**

```toml
[project]
name = "dewpoint"
version = "0.1.0"
description = "Multi-tenant no-code automation for Juniper Mist"
license = "Apache-2.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "pydantic>=2.9",
  "pydantic-settings>=2.6",
  "sqlalchemy[asyncio]>=2.0.36",
  "asyncpg>=0.30",
  "alembic>=1.14",
  "argon2-cffi>=23.1",
  "pyotp>=2.9",
  "webauthn>=2.2",
  "cryptography>=43",
  "httpx>=0.28",
  "typer>=0.13",
  "structlog>=24.4",
]

[project.scripts]
dewpoint = "dewpoint.apps.cli.main:app"

[dependency-groups]
dev = [
  "pytest>=8.3",
  "pytest-asyncio>=0.24",
  "testcontainers[postgres]>=4.8",
  "respx>=0.21",
  "hypothesis>=6.115",
  "ruff>=0.7",
  "mypy>=1.13",
  "import-linter>=2.1",
  "pip-licenses>=5.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/dewpoint"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
testpaths = ["tests"]

[tool.ruff]
line-length = 120
target-version = "py312"
[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "S", "ASYNC"]
[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "S105", "S106"]

[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]
mypy_path = "src"

[tool.importlinter]
root_package = "dewpoint"

[[tool.importlinter.contracts]]
name = "core does not depend on apps"
type = "forbidden"
source_modules = ["dewpoint.core"]
forbidden_modules = ["dewpoint.apps"]

[[tool.importlinter.contracts]]
name = "fastapi only in apps and core.http"
type = "forbidden"
source_modules = ["dewpoint.core"]
forbidden_modules = ["fastapi"]
ignore_imports = ["dewpoint.core.http -> fastapi"]
allow_indirect_imports = true
```

`backend/src/dewpoint/__init__.py`:
```python
# SPDX-License-Identifier: Apache-2.0
__version__ = "0.1.0"
```
Create empty `core/__init__.py` and `apps/__init__.py`, each holding only the SPDX line.

- [ ] **Step 3: Run the test**

Run: `cd backend && uv sync && uv run pytest tests/test_package.py -v`
Expected: PASS

- [ ] **Step 4: Add repo documents**

- `LICENSE`: the verbatim Apache License 2.0 text from https://www.apache.org/licenses/LICENSE-2.0.txt.
- `NOTICE`: `Dewpoint\nCopyright 2026 The Dewpoint Authors`.
- `SECURITY.md`: supported versions (latest minor); report privately through GitHub Security Advisories ("Report a vulnerability"); do not open public issues; acknowledgement within 5 business days.
- `CONTRIBUTING.md`: DCO sign-off (`git commit -s`), SPDX header rule, `uv run pytest`, `pnpm test`.
- `.gitignore`: `.venv/`, `__pycache__/`, `node_modules/`, `dist/`, `.env`, `*.pem`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `playwright-report/`, `test-results/`.

- [ ] **Step 5: Add CI**

`.github/workflows/ci.yml`:
```yaml
name: ci
on: [push, pull_request]
permissions: { contents: read }
jobs:
  backend:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: backend } }
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@38f3f104447c67c051c4a08e39b64a148898af3a # v4
      - run: uv sync --locked
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy src
      - run: uv run lint-imports
      - run: uv run pytest -q
      - run: uv run pip-licenses --fail-on="GPL;AGPL;LGPL;SSPL;BUSL" --partial-match
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: gitleaks/gitleaks-action@ff98106e4c7b2bc287b24eaf42907196329070c7 # v2
        env: { GITHUB_TOKEN: "${{ secrets.GITHUB_TOKEN }}" }
      - uses: aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25 # v0.36.0
        with: { scan-type: fs, scan-ref: ., severity: "HIGH,CRITICAL", exit-code: "1" }
```
`.github/workflows/codeql.yml`: the standard CodeQL workflow for languages `python` and `javascript-typescript`, triggered on push, PRs and a weekly cron, with `permissions: { security-events: write, contents: read }`.

- [ ] **Step 6: Lock and verify**

Run: `cd backend && uv lock && uv run ruff check . && uv run mypy src && uv run lint-imports`
Expected: all pass. `uv.lock` is created.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "chore: scaffold repository, backend package and CI

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Settings, API app factory, security headers, sanitized errors

**Files:**
- Create: `backend/src/dewpoint/core/config.py`
- Create: `backend/src/dewpoint/apps/api/__init__.py`, `main.py`, `middleware.py`, `errors.py`, `routes/__init__.py`, `routes/health.py`
- Test: `backend/tests/apps/api/test_app.py`

**Interfaces:**
- Produces:
  - `dewpoint.core.config.Settings` with the fields below, and `get_settings() -> Settings` (lru-cached).
  - `dewpoint.apps.api.main.create_app(settings: Settings | None = None) -> FastAPI`.
  - The `SecurityHeadersMiddleware` class.
  - `dewpoint.apps.api.errors.install_error_handlers(app)`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/apps/api/test_app.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import httpx
import pytest
from fastapi import APIRouter

from dewpoint.apps.api.main import create_app
from dewpoint.core.config import Settings


def _settings() -> Settings:
    return Settings(database_url="postgresql+asyncpg://u:p@localhost/x", kek_b64="A" * 43 + "=", public_origin="https://dewpoint.test")


async def test_health_ok_and_security_headers() -> None:
    app = create_app(_settings())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as c:
        r = await c.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "script-src 'self'" in csp and "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["strict-transport-security"].startswith("max-age=")


async def test_unhandled_error_is_sanitized() -> None:
    app = create_app(_settings())
    router = APIRouter()

    @router.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="https://testserver") as c:
        r = await c.get("/boom")
    assert r.status_code == 500
    assert "secret internal detail" not in r.text
    assert r.json() == {"error": "internal_error"}


async def test_error_envelope_is_flat() -> None:
    from fastapi import HTTPException
    from pydantic import BaseModel

    app = create_app(_settings())
    router = APIRouter()

    class In(BaseModel):
        password: str
        n: int

    @router.get("/denied")
    async def denied() -> None:
        raise HTTPException(403, detail={"error": "step_up_required"})

    @router.post("/typed")
    async def typed(body: In) -> None:
        return None

    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as c:
        assert (await c.get("/denied")).json() == {"error": "step_up_required"}
        assert (await c.get("/missing")).json() == {"error": "not_found"}
        r = await c.post("/typed", json={"password": "hunter2-secret", "n": "x"})
    assert r.status_code == 422 and r.json() == {"error": "invalid", "fields": ["n"]}
    assert "hunter2-secret" not in r.text
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `cd backend && uv run pytest tests/apps/api/test_app.py -v`
Expected: FAIL (`ModuleNotFoundError: dewpoint.apps.api`)

- [ ] **Step 3: Implement**

`core/config.py`:
```python
# SPDX-License-Identifier: Apache-2.0
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DEWPOINT_", env_file=".env", extra="ignore")

    database_url: str
    kek_b64: str = Field(description="Base64 32-byte key-encryption key")
    kek_id: str = "env-1"
    kek_previous_b64: str | None = None  # set only during a KEK rollout (see docs/operations/key-rotation.md)
    kek_previous_id: str | None = None
    public_origin: str = Field(description="Browser origin, e.g. https://dewpoint.example.com")
    rp_id: str | None = None  # WebAuthn RP ID; defaults to host of public_origin
    mfa_required: bool = True
    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    login_max_failures: int = 5  # per account and per MFA user
    login_ip_max_failures: int = 50  # per source IP: higher, because offices share NAT addresses
    login_lockout_minutes: int = 15
    reauth_minutes: int = 5  # adding/replacing a factor from an active session needs a second factor this recent
    totp_pending_minutes: int = 10  # an unconfirmed new TOTP secret expires after this
    passkey_options_per_ip: int = 30  # anonymous passkey challenges per source IP per 15-minute window
    webauthn_challenges_max: int = 10_000  # outstanding (unexpired) challenges across the platform
    audit_signing_key_b64: str | None = None  # Ed25519 private key (raw 32 bytes, base64)
    audit_anchor_path: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

`apps/api/middleware.py`:
```python
# SPDX-License-Identifier: Apache-2.0
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        response.headers["Cache-Control"] = "no-store"
        return response
```

`apps/api/errors.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = structlog.get_logger(__name__)


_STATUS_CODES = {400: "bad_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found",
                 405: "method_not_allowed", 409: "conflict", 422: "invalid", 429: "rate_limited"}


def install_error_handlers(app: FastAPI) -> None:
    """Every error response body is {"error": <code>, ...}. Routes raise HTTPException(detail={"error": ...})."""

    @app.exception_handler(StarletteHTTPException)  # also catches fastapi.HTTPException (subclass)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            body = exc.detail
        else:
            body = {"error": _STATUS_CODES.get(exc.status_code, "http_error")}
        return JSONResponse(status_code=exc.status_code, content=body, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [".".join(str(p) for p in e["loc"] if p != "body") for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": "invalid", "fields": fields})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_error", path=request.url.path, exc_info=exc)
        return JSONResponse(status_code=500, content={"error": "internal_error"})
```
Imports for `errors.py`: `from fastapi.exceptions import RequestValidationError` and `from starlette.exceptions import HTTPException as StarletteHTTPException`. The validation handler returns field paths only, never the submitted values (which may be passwords or tokens).

`apps/api/routes/health.py`:
```python
# SPDX-License-Identifier: Apache-2.0
from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}
```

`apps/api/main.py`:
```python
# SPDX-License-Identifier: Apache-2.0
from fastapi import FastAPI

from dewpoint.apps.api.errors import install_error_handlers
from dewpoint.apps.api.middleware import SecurityHeadersMiddleware
from dewpoint.apps.api.routes import health
from dewpoint.core.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Dewpoint API", docs_url=None, redoc_url=None, openapi_url="/api/v1/openapi.json")
    app.state.settings = settings
    app.add_middleware(SecurityHeadersMiddleware)
    install_error_handlers(app)
    app.include_router(health.router)
    return app
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/apps/api/test_app.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(api): app factory, settings, security headers, sanitized errors

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Database layer, migrations harness, DB roles, tenant scope helper

**Files:**
- Create: `backend/src/dewpoint/core/db.py`, `backend/src/dewpoint/core/models/__init__.py`, `backend/src/dewpoint/core/models/base.py`
- Create: `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/script.py.mako`, `backend/migrations/versions/0001_roles_and_extensions.py`
- Create: `backend/tests/conftest.py`
- Test: `backend/tests/core/test_db.py`

**Interfaces:**
- Produces:
  - `Base` (DeclarativeBase), plus the mixins `UUIDPk` (`id: Mapped[uuid.UUID]`, server default `gen_random_uuid()`) and `Timestamps` (`created_at`, `updated_at`).
  - `make_engine(url: str) -> AsyncEngine`, `make_sessionmaker(engine) -> async_sessionmaker[AsyncSession]`.
  - `async def tenant_scope(session: AsyncSession, tenant_id: uuid.UUID | None) -> None`: sets `app.tenant_id` **and clears `app.user_id`** (transaction-local).
  - `async def user_scope(session: AsyncSession, user_id: uuid.UUID) -> None`: sets `app.user_id` **and clears `app.tenant_id`**. It's used only for "which tenants do I belong to" discovery.
  - The two scopes are **mutually exclusive by construction**. RLS policies that allow `tenant match OR user match` therefore never widen a tenant-scoped query to the caller's other tenants.
  - DB group roles (NOLOGIN): `dewpoint_api`, `dewpoint_ingress`, `dewpoint_dispatch`, `dewpoint_worker`, `dewpoint_admin`.
  - Test fixtures:
    - `pg_url` (owner URL, session scope)
    - `_url_for(pg_url, group_role) -> str` (a URL for the LOGIN test user `t_<group_role>`, created once per session)
    - `api_sessionmaker` (async_sessionmaker bound to the `dewpoint_api` user)
    - `owner_sessionmaker`
    - `clean_db` (TRUNCATE all app tables between tests)

- [ ] **Step 1: Write the failing test**

`backend/tests/core/test_db.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import uuid

from sqlalchemy import text

from dewpoint.core.db import tenant_scope, user_scope


async def test_scopes_are_exclusive(api_sessionmaker) -> None:
    tid, uid = uuid.uuid4(), uuid.uuid4()
    q = text("select current_setting('app.tenant_id', true), current_setting('app.user_id', true)")
    async with api_sessionmaker() as s, s.begin():
        await user_scope(s, uid)
        assert tuple((await s.execute(q)).one()) == ("", str(uid))
        await tenant_scope(s, tid)
        assert tuple((await s.execute(q)).one()) == (str(tid), "")


async def test_tenant_scope_is_transaction_local(api_sessionmaker) -> None:
    tid = uuid.uuid4()
    async with api_sessionmaker() as s:
        async with s.begin():
            await tenant_scope(s, tid)
            assert (await s.execute(text("select current_setting('app.tenant_id', true)"))).scalar_one() == str(tid)
        async with s.begin():
            value = (await s.execute(text("select current_setting('app.tenant_id', true)"))).scalar_one()
            assert value in (None, "")


async def test_group_roles_exist(owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s:
        rows = (await s.execute(text("select rolname from pg_roles where rolname like 'dewpoint_%'"))).scalars().all()
    assert {"dewpoint_api", "dewpoint_ingress", "dewpoint_dispatch", "dewpoint_worker", "dewpoint_admin"} <= set(rows)
```

- [ ] **Step 2: Implement `core/db.py` and `models/base.py`**

```python
# SPDX-License-Identifier: Apache-2.0
# core/db.py
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _set_scope(session: AsyncSession, tenant: str, user: str) -> None:
    await session.execute(text("select set_config('app.tenant_id', :t, true), set_config('app.user_id', :u, true)"),
                          {"t": tenant, "u": user})


async def tenant_scope(session: AsyncSession, tenant_id: uuid.UUID | None) -> None:
    """Tenant RLS context for this transaction. Always clears the user-discovery context.
    Call only after the authoritative membership/run check."""
    await _set_scope(session, str(tenant_id) if tenant_id else "", "")


async def user_scope(session: AsyncSession, user_id: uuid.UUID) -> None:
    """User-discovery RLS context (own memberships/tenants only). Always clears the tenant context."""
    await _set_scope(session, "", str(user_id))
```

```python
# SPDX-License-Identifier: Apache-2.0
# core/models/base.py
import uuid
from datetime import datetime

from sqlalchemy import DateTime, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UUIDPk:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```
`models/__init__.py` imports every model module (added in later tasks) so Alembic and tests see the full metadata. For now it contains `from dewpoint.core.models.base import Base  # noqa: F401`.

- [ ] **Step 3: Set up Alembic**

- `alembic.ini`: `script_location = migrations`, with `sqlalchemy.url` left empty.
- `migrations/env.py`: generate it with `uv run alembic init -t async migrations`, then edit two lines so it uses `target_metadata = dewpoint.core.models.Base.metadata` and the URL `config.set_main_option("sqlalchemy.url", os.environ["DEWPOINT_DATABASE_URL"])`, keeping the asyncpg driver. Migrations run as the database owner.

`migrations/versions/0001_roles_and_extensions.py`:
```python
# SPDX-License-Identifier: Apache-2.0
"""roles and extensions"""
from alembic import op

revision = "0001"
down_revision = None

ROLES = ["dewpoint_api", "dewpoint_ingress", "dewpoint_dispatch", "dewpoint_worker", "dewpoint_admin"]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    for role in ROLES:
        op.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') "
            f"THEN CREATE ROLE {role} NOLOGIN; END IF; END $$"
        )
    op.execute("GRANT USAGE ON SCHEMA public TO " + ", ".join(ROLES))


def downgrade() -> None:
    for role in ROLES:
        op.execute(f"DROP ROLE IF EXISTS {role}")
```

- [ ] **Step 4: Write `tests/conftest.py`**

```python
# SPDX-License-Identifier: Apache-2.0
import os
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer

from dewpoint.core.db import make_engine, make_sessionmaker

BACKEND = Path(__file__).resolve().parents[1]
TEST_ROLES = ["dewpoint_api", "dewpoint_ingress", "dewpoint_dispatch", "dewpoint_worker", "dewpoint_admin",
              "dewpoint_auditor"]


@pytest.fixture(scope="session")
def pg_url() -> str:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        env = {**os.environ, "DEWPOINT_DATABASE_URL": url}
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True)
        yield url


@pytest.fixture(scope="session")
async def _test_users(pg_url: str) -> None:
    eng = make_engine(pg_url)
    async with eng.begin() as c:
        for role in TEST_ROLES:
            await c.execute(text(
                f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='t_{role}') "
                f"AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') "  # group roles appear as migrations land
                f"THEN CREATE ROLE t_{role} LOGIN PASSWORD 'pw' IN ROLE {role}; END IF; END $$"
            ))
    await eng.dispose()


def _url_for(pg_url: str, role: str) -> str:
    return f"postgresql+asyncpg://t_{role}:pw@{pg_url.split('@', 1)[1]}"


@pytest.fixture(scope="session")
async def owner_sessionmaker(pg_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = make_engine(pg_url)
    yield make_sessionmaker(eng)
    await eng.dispose()


@pytest.fixture(scope="session")
async def api_sessionmaker(pg_url: str, _test_users: None) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = make_engine(_url_for(pg_url, "dewpoint_api"))
    yield make_sessionmaker(eng)
    await eng.dispose()


@pytest.fixture(autouse=True)
async def clean_db(owner_sessionmaker: async_sessionmaker[AsyncSession]) -> AsyncIterator[None]:
    yield
    async with owner_sessionmaker() as s, s.begin():
        tables = (await s.execute(text(
            "select string_agg(format('%I', tablename), ',') from pg_tables "
            "where schemaname='public' and tablename <> 'alembic_version'"
        ))).scalar_one()
        if tables:
            await s.execute(text("SET LOCAL session_replication_role = replica"))  # bypass audit triggers
            await s.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
```
Later tasks add `worker_sessionmaker` and `ingress_sessionmaker` fixtures built the same way as `api_sessionmaker`, using `_url_for(pg_url, "dewpoint_worker")` and `_url_for(pg_url, "dewpoint_ingress")`. `dewpoint_auditor` is created by migration 0005 (Task 11). `_test_users` already skips group roles that don't exist yet.

- [ ] **Step 5: Run the tests**

Run: `cd backend && uv run pytest tests/core/test_db.py -v` (Docker must be running)
Expected: PASS for both tests.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(core): database layer, alembic harness, DB group roles, tenant scope

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 4: Identity and tenancy schema with RLS

**Files:**
- Create: `backend/src/dewpoint/core/models/identity.py`, `backend/src/dewpoint/core/models/tenancy.py`
- Modify: `backend/src/dewpoint/core/models/__init__.py` (import the new modules)
- Create: `backend/migrations/versions/0002_identity.py`, `backend/migrations/versions/0003_tenancy_rls.py`
- Test: `backend/tests/core/test_rls_tenancy.py`

**Interfaces:**
- Consumes: `Base`, `UUIDPk`, `Timestamps`, `tenant_scope()` (Task 3).
- Produces:
  - ORM classes `User`, `UserMfa`, `RecoveryCode`, `WebauthnCredential`, `AuthSession`, `AuthThrottle`, `WebauthnChallenge`, `Tenant`, `Membership`.
  - `Role = Literal["owner", "admin", "editor", "operator", "viewer"]`.
  - The SQL functions `app_tenant_id()` and `app_user_id()`, which are reused by every later RLS policy.

- [ ] **Step 1: Write the failing RLS tests**

`backend/tests/core/test_rls_tenancy.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from dewpoint.core.db import tenant_scope, user_scope
from dewpoint.core.models.tenancy import Membership, Tenant


async def _seed(owner_sessionmaker) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    a, b, u = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("insert into users(id,email,password_hash) values (:u,'u@x.test','h')"), {"u": u})
        await s.execute(text("insert into tenants(id,name,slug) values (:a,'A','a'),(:b,'B','b')"), {"a": a, "b": b})
        await s.execute(text("insert into memberships(tenant_id,user_id,role) values (:a,:u,'editor')"), {"a": a, "u": u})
    return a, b, u


async def test_no_context_sees_nothing(owner_sessionmaker, api_sessionmaker) -> None:
    await _seed(owner_sessionmaker)
    async with api_sessionmaker() as s, s.begin():
        assert (await s.execute(select(Tenant))).scalars().all() == []
        assert (await s.execute(select(Membership))).scalars().all() == []


async def test_tenant_context_isolates(owner_sessionmaker, api_sessionmaker) -> None:
    a, b, _ = await _seed(owner_sessionmaker)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, b)
        assert [t.id for t in (await s.execute(select(Tenant))).scalars()] == [b]
        assert (await s.execute(select(Membership))).scalars().all() == []


async def test_user_context_lists_own_memberships(owner_sessionmaker, api_sessionmaker) -> None:
    a, _, u = await _seed(owner_sessionmaker)
    async with api_sessionmaker() as s, s.begin():
        await user_scope(s, u)
        assert [m.tenant_id for m in (await s.execute(select(Membership))).scalars()] == [a]
        assert [t.id for t in (await s.execute(select(Tenant))).scalars()] == [a]


async def test_tenant_scope_does_not_leak_callers_other_tenants(owner_sessionmaker, api_sessionmaker) -> None:
    a, b, u = await _seed(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():  # u belongs to BOTH tenants
        await s.execute(text("insert into memberships(tenant_id,user_id,role) values (:b,:u,'viewer')"), {"b": b, "u": u})
    async with api_sessionmaker() as s, s.begin():
        await user_scope(s, u)
        assert len((await s.execute(select(Membership))).scalars().all()) == 2
        await tenant_scope(s, b)  # what require() does after the membership check
        assert [m.tenant_id for m in (await s.execute(select(Membership))).scalars()] == [b]
        assert [t.id for t in (await s.execute(select(Tenant))).scalars()] == [b]


async def test_cross_tenant_insert_rejected(owner_sessionmaker, api_sessionmaker) -> None:
    a, b, u = await _seed(owner_sessionmaker)
    with pytest.raises(DBAPIError, match="row-level security"):
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, a)
            s.add(Membership(tenant_id=b, user_id=u, role="viewer"))
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `uv run pytest tests/core/test_rls_tenancy.py -v`
Expected: FAIL (`ModuleNotFoundError: dewpoint.core.models.tenancy`)

- [ ] **Step 3: Implement the models**

`core/models/identity.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import uuid
from datetime import datetime

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base, Timestamps, UUIDPk


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320))
    password_hash: Mapped[str] = mapped_column(Text)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserMfa(Base):
    __tablename__ = "user_mfa"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    totp_secret_ct: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_totp_step: Mapped[int | None] = mapped_column(Integer)


class RecoveryCode(UUIDPk, Base):
    __tablename__ = "recovery_codes"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    code_hash: Mapped[str] = mapped_column(Text)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebauthnCredential(UUIDPk, Timestamps, Base):
    __tablename__ = "webauthn_credentials"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    transports: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    name: Mapped[str] = mapped_column(String(100))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(UUIDPk, Base):
    __tablename__ = "sessions"
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    state: Mapped[str] = mapped_column(String(20))  # mfa_pending | enroll_required | active
    auth_methods: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)  # password, totp, recovery, passkey
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(400))


class AuthThrottle(Base):
    __tablename__ = "auth_throttle"
    kind: Mapped[str] = mapped_column(String(20), primary_key=True)  # login_email | login_ip | mfa_user
    key: Mapped[str] = mapped_column(String(320), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebauthnChallenge(UUIDPk, Base):
    __tablename__ = "webauthn_challenges"
    challenge: Mapped[bytes] = mapped_column(LargeBinary)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(20))  # register | authenticate
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

`core/models/tenancy.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import uuid
from typing import Literal

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base, Timestamps, UUIDPk

Role = Literal["owner", "admin", "editor", "operator", "viewer"]
ROLES: tuple[Role, ...] = ("owner", "admin", "editor", "operator", "viewer")


class Tenant(UUIDPk, Timestamps, Base):
    __tablename__ = "tenants"
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    require_passkey: Mapped[bool] = mapped_column(Boolean, default=False)


class Membership(UUIDPk, Timestamps, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id"),)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))
```

- [ ] **Step 4: Write the migrations**

`0002_identity.py`: create the seven identity tables with `op.create_table`, matching the models column for column. **Every column with an ORM default also gets a `server_default`**, because tests and bootstrap SQL insert raw rows: booleans `sa.false()`/`sa.true()`, integers `'0'`, arrays `'{}'`, `sessions.state` has none (always set explicitly), and `created_at`/`updated_at` get `sa.func.now()`. The same rule applies to `0003` (`tenants.require_passkey` → `sa.false()`) and to `0006` (`connections.status` → `'unverified'`, `status_detail` → `''`). Add:
- a unique index `ix_users_email_lower` on `lower(email)`;
- an index `ix_sessions_user` on `sessions(user_id)`;
- `op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON users, user_mfa, recovery_codes, webauthn_credentials, sessions, auth_throttle, webauthn_challenges TO dewpoint_api, dewpoint_admin")`.

Set `revision = "0002"`, `down_revision = "0001"`, and have `downgrade()` drop the tables in reverse order.

`0003_tenancy_rls.py`: create `tenants` and `memberships` with `op.create_table` (a CHECK constraint on `role IN ('owner','admin','editor','operator','viewer')`), then run:
```python
op.execute("""
CREATE FUNCTION app_tenant_id() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$;
CREATE FUNCTION app_user_id() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$;

ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY memberships_scope ON memberships
  USING (tenant_id = app_tenant_id() OR user_id = app_user_id())
  WITH CHECK (tenant_id = app_tenant_id());

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
CREATE POLICY tenants_scope ON tenants
  USING (id = app_tenant_id()
         OR EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = tenants.id AND m.user_id = app_user_id()))
  WITH CHECK (id = app_tenant_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON tenants, memberships TO dewpoint_api, dewpoint_admin;
GRANT SELECT ON tenants, memberships TO dewpoint_worker, dewpoint_dispatch;
""")
```
`downgrade()` drops the policies, the tables and both functions.

**Why FORCE:** the migration owner still bypasses RLS unless `FORCE` is set. With `FORCE` on, the owner-seeded test data in Step 1 is only possible because the owner is a superuser in the test container, and superusers bypass RLS. That's expected.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/core/test_rls_tenancy.py -v`
Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(core): identity and tenancy schema with RLS policies

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Envelope encryption keyring

**Files:**
- Create: `backend/src/dewpoint/core/crypto/__init__.py`, `kek.py`, `keyring.py`
- Create: `backend/src/dewpoint/core/models/keys.py`, `backend/migrations/versions/0004_keys.py`
- Test: `backend/tests/core/crypto/test_keyring.py`, `backend/tests/core/crypto/test_keyring_rls.py`

**Interfaces:**
- Consumes: `Base`, `UUIDPk` (Task 3); `Settings.kek_b64`, `kek_id`, `kek_previous_b64`, `kek_previous_id` (Task 2).
- Produces:
  - `Kek(key_id: str, key: bytes)` with `.wrap(dek: bytes, aad: bytes) -> bytes` and `.unwrap(blob: bytes, aad: bytes) -> bytes`.
  - `KekSet(current: Kek, previous: Sequence[Kek] = ())`:
    - `.current` wraps every *new* data key;
    - `.get(kek_id) -> Kek` unwraps with whichever key wrapped the row, and raises `UnknownKekError` otherwise;
    - `KekSet.from_settings(settings)`.
  - `Keyring(keks: KekSet)` with:
    - `async encrypt(session, *, tenant_id: UUID | None, purpose: str, context: str, plaintext: bytes) -> bytes`
    - `async decrypt(session, *, tenant_id: UUID | None, purpose: str, context: str, blob: bytes) -> bytes`
    - `async rotate(session, tenant_id: UUID | None) -> int` (data-key rotation; returns the new active version)
    - `async rewrap_batch(session, batch_size: int = 100) -> int`: rewraps up to `batch_size` rows **not** wrapped by `current` (`FOR UPDATE SKIP LOCKED`); returns the count, 0 when done
    - `async kek_usage(session) -> dict[str, int]` (`kek_id` → number of data keys)
  - `tenant_id=None` means the platform scope, used for user TOTP secrets. It's stored in `platform_keys`, while tenant keys live in `data_keys` under RLS.
  - Callers must run `tenant_scope(session, tenant_id)` before using a tenant's key. Key creation and rotation are serialized per scope with `pg_advisory_xact_lock`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/core/crypto/test_keyring.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import os
import uuid

import pytest
from cryptography.exceptions import InvalidTag

from dewpoint.core.crypto.kek import Kek, KekSet, UnknownKekError
from dewpoint.core.crypto.keyring import Keyring


def _kek(kid: str = "k1") -> Kek:
    return Kek(kid, os.urandom(32))


async def test_roundtrip_and_aad_binding(owner_sessionmaker) -> None:
    kr, t = Keyring(KekSet(_kek())), uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        blob = await kr.encrypt(s, tenant_id=t, purpose="connection.secret", context="c1", plaintext=b"tok")
        assert b"tok" not in blob
        assert await kr.decrypt(s, tenant_id=t, purpose="connection.secret", context="c1", blob=blob) == b"tok"
        with pytest.raises(InvalidTag):
            await kr.decrypt(s, tenant_id=t, purpose="connection.secret", context="c2", blob=blob)
        with pytest.raises(InvalidTag):
            await kr.decrypt(s, tenant_id=uuid.uuid4(), purpose="connection.secret", context="c1", blob=blob)


async def test_rotation_keeps_old_ciphertext_readable(owner_sessionmaker) -> None:
    kr, t = Keyring(KekSet(_kek())), uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        old = await kr.encrypt(s, tenant_id=t, purpose="p", context="x", plaintext=b"a")
        assert await kr.rotate(s, t) == 2
        new = await kr.encrypt(s, tenant_id=t, purpose="p", context="x", plaintext=b"b")
        assert old[1:5] != new[1:5]  # different key version header
        assert await kr.decrypt(s, tenant_id=t, purpose="p", context="x", blob=old) == b"a"


async def test_kek_rollout_phases(owner_sessionmaker) -> None:
    """Phases from docs/operations/key-rotation.md. Old and new processes coexist in phases A and B."""
    old, new = _kek("old"), _kek("new")
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    only_old = Keyring(KekSet(old))
    phase_a = Keyring(KekSet(old, previous=[new]))   # new key is read-only everywhere
    phase_b = Keyring(KekSet(new, previous=[old]))   # new key writes; old still readable
    only_new = Keyring(KekSet(new))                  # phase D
    async with owner_sessionmaker() as s, s.begin():
        b1 = await only_old.encrypt(s, tenant_id=t1, purpose="p", context="x", plaintext=b"one")
        b2 = await phase_b.encrypt(s, tenant_id=t2, purpose="p", context="x", plaintext=b"two")  # new DEK, new KEK
        # a phase-A process (not yet switched) can read what a phase-B process wrote
        assert await phase_a.decrypt(s, tenant_id=t2, purpose="p", context="x", blob=b2) == b"two"
        # a process that never got the new key cannot, which is why phase A exists
        with pytest.raises(UnknownKekError):
            await only_old.decrypt(s, tenant_id=t2, purpose="p", context="x", blob=b2)
        assert await phase_b.kek_usage(s) == {"old": 1, "new": 1}
        with pytest.raises(UnknownKekError):
            await only_new.decrypt(s, tenant_id=t1, purpose="p", context="x", blob=b1)
        # phase C: rewrap in batches until nothing references the old KEK
        assert await phase_b.rewrap_batch(s, batch_size=1) == 1
        assert await phase_b.rewrap_batch(s, batch_size=1) == 0
        assert await phase_b.kek_usage(s) == {"new": 2}
        # phase D: the old KEK can be removed from configuration
        assert await only_new.decrypt(s, tenant_id=t1, purpose="p", context="x", blob=b1) == b"one"
        assert await only_new.decrypt(s, tenant_id=t2, purpose="p", context="x", blob=b2) == b"two"
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `uv run pytest tests/core/crypto/test_keyring.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement**

`core/models/keys.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base, UUIDPk


class _WrappedKey(UUIDPk):
    version: Mapped[int] = mapped_column(Integer)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    kek_id: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataKey(_WrappedKey, Base):
    """A tenant's wrapped data-encryption keys. RLS-scoped to the tenant (FORCE); key admins see all."""

    __tablename__ = "data_keys"
    __table_args__ = (UniqueConstraint("tenant_id", "version"),)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))


class PlatformKey(_WrappedKey, Base):
    """The platform scope's wrapped data keys (user TOTP secrets). Granted to api and admin roles only."""

    __tablename__ = "platform_keys"
    __table_args__ = (UniqueConstraint("version"),)
```

`core/crypto/kek.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from dewpoint.core.config import Settings


class UnknownKekError(LookupError):
    pass


class Kek:
    def __init__(self, key_id: str, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("KEK must be 32 bytes")
        self.key_id, self._aes = key_id, AESGCM(key)

    def wrap(self, dek: bytes, aad: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._aes.encrypt(nonce, dek, aad)

    def unwrap(self, blob: bytes, aad: bytes) -> bytes:
        return self._aes.decrypt(blob[:12], blob[12:], aad)


class KekSet:
    """The current KEK wraps new data keys; previous KEKs only unwrap (used during a rollout)."""

    def __init__(self, current: Kek, previous: Sequence[Kek] = ()) -> None:
        self.current = current
        self._by_id = {k.key_id: k for k in (*previous, current)}
        if len(self._by_id) != len(previous) + 1:
            raise ValueError("KEK ids must be unique")

    def get(self, kek_id: str) -> Kek:
        try:
            return self._by_id[kek_id]
        except KeyError:
            raise UnknownKekError(kek_id) from None

    @classmethod
    def from_settings(cls, settings: Settings) -> "KekSet":
        current = Kek(settings.kek_id, base64.b64decode(settings.kek_b64))
        previous = []
        if settings.kek_previous_b64:
            if not settings.kek_previous_id:
                raise ValueError("DEWPOINT_KEK_PREVIOUS_ID is required with DEWPOINT_KEK_PREVIOUS_B64")
            previous.append(Kek(settings.kek_previous_id, base64.b64decode(settings.kek_previous_b64)))
        return cls(current, previous)
```
Add `from collections.abc import Sequence` to the imports.

`core/crypto/keyring.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import os
import struct
import uuid
from collections.abc import Sequence
from typing import Any, cast

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.crypto.kek import KekSet
from dewpoint.core.models.keys import DataKey, PlatformKey

FORMAT_V1 = b"\x01"
type AnyKey = DataKey | PlatformKey


def _scope(tenant_id: uuid.UUID | None) -> str:
    return str(tenant_id) if tenant_id else "platform"


def _aad(scope: str, purpose: str, context: str) -> bytes:
    return f"dewpoint|{scope}|{purpose}|{context}".encode()


def _dek_aad(row: AnyKey) -> bytes:
    scope = str(row.tenant_id) if isinstance(row, DataKey) else "platform"
    return f"dek|{scope}|{row.version}".encode()


def _scope_filter(tenant_id: uuid.UUID | None) -> tuple[type[AnyKey], list[Any]]:
    """Tenant keys live in RLS-scoped data_keys; the platform key in the narrowly granted platform_keys."""
    if tenant_id is None:
        return PlatformKey, []
    return DataKey, [DataKey.tenant_id == tenant_id]


class Keyring:
    def __init__(self, keks: KekSet) -> None:
        self._keks = keks

    async def _active(self, s: AsyncSession, tenant_id: uuid.UUID | None) -> AnyKey:
        # Serialize first-use creation and rotation per scope until commit; FOR UPDATE alone can't lock a
        # row that doesn't exist yet, so two first uses would both insert version 1.
        await s.execute(
            text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"dewpoint:dek:{_scope(tenant_id)}"}
        )
        model, where = _scope_filter(tenant_id)
        found = (
            await s.execute(select(model).where(*where, model.active.is_(True)).with_for_update())
        ).scalar_one_or_none()
        row = cast(AnyKey | None, found)
        if row is None:
            row = self._new_key(tenant_id, 1)
            s.add(row)
            await s.flush()
        return row

    def _new_key(self, tenant_id: uuid.UUID | None, version: int) -> AnyKey:
        kek = self._keks.current
        row: AnyKey = (
            PlatformKey(version=version) if tenant_id is None else DataKey(tenant_id=tenant_id, version=version)
        )
        row.wrapped_key = kek.wrap(AESGCM.generate_key(256), _dek_aad(row))
        row.kek_id = kek.key_id
        return row

    def _dek(self, row: AnyKey) -> AESGCM:
        kek = self._keks.get(row.kek_id)  # UnknownKekError if this process lacks the wrapping key
        return AESGCM(kek.unwrap(row.wrapped_key, _dek_aad(row)))

    async def encrypt(
        self, s: AsyncSession, *, tenant_id: uuid.UUID | None, purpose: str, context: str, plaintext: bytes
    ) -> bytes:
        row = await self._active(s, tenant_id)
        nonce = os.urandom(12)
        ct = self._dek(row).encrypt(nonce, plaintext, _aad(_scope(tenant_id), purpose, context))
        return FORMAT_V1 + struct.pack(">I", row.version) + nonce + ct

    async def decrypt(
        self, s: AsyncSession, *, tenant_id: uuid.UUID | None, purpose: str, context: str, blob: bytes
    ) -> bytes:
        if blob[:1] != FORMAT_V1:
            raise ValueError("unknown ciphertext format")
        (version,) = struct.unpack(">I", blob[1:5])
        model, where = _scope_filter(tenant_id)
        found = (await s.execute(select(model).where(*where, model.version == version))).scalar_one_or_none()
        row = cast(AnyKey | None, found)
        if row is None:  # missing, or invisible under RLS: indistinguishable from a bad tag on purpose
            raise InvalidTag()
        return self._dek(row).decrypt(blob[5:17], blob[17:], _aad(_scope(tenant_id), purpose, context))

    async def rotate(self, s: AsyncSession, tenant_id: uuid.UUID | None) -> int:
        current = await self._active(s, tenant_id)
        await s.execute(update(type(current)).where(type(current).id == current.id).values(active=False))
        new = self._new_key(tenant_id, current.version + 1)
        s.add(new)
        await s.flush()
        return new.version

    async def rewrap_batch(self, s: AsyncSession, batch_size: int = 100) -> int:
        """Rewrap up to batch_size keys not wrapped by the current KEK. Run as a key-admin role."""
        current = self._keks.current
        done = 0
        for model in (DataKey, PlatformKey):
            if done >= batch_size:
                break
            q = select(model).where(model.kek_id != current.key_id).limit(batch_size - done)
            rows = cast(Sequence[AnyKey], (await s.execute(q.with_for_update(skip_locked=True))).scalars().all())
            for row in rows:
                aad = _dek_aad(row)
                row.wrapped_key = current.wrap(self._keks.get(row.kek_id).unwrap(row.wrapped_key, aad), aad)
                row.kek_id = current.key_id
            done += len(rows)
        await s.flush()
        return done

    async def kek_usage(self, s: AsyncSession) -> dict[str, int]:
        usage: dict[str, int] = {}
        for model in (DataKey, PlatformKey):
            for kek_id, n in (await s.execute(select(model.kek_id, func.count()).group_by(model.kek_id))).all():
                usage[kek_id] = usage.get(kek_id, 0) + int(n)
        return usage
```
Add `func` to the `sqlalchemy` import.

`migrations/versions/0004_keys.py` (tenant keys under FORCE RLS plus a key-admin policy; the platform key in a separate table granted to `api`/`admin` only; one statement per `op.execute`, as asyncpg requires):
```python
# SPDX-License-Identifier: Apache-2.0
"""envelope-encryption keys: tenant data keys (RLS) and platform keys (narrow grants)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _key_columns() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("wrapped_key", sa.LargeBinary, nullable=False),
        sa.Column("kek_id", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.create_table(
        "data_keys",
        *_key_columns(),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "version"),
    )
    op.create_index("ux_data_keys_active", "data_keys", ["tenant_id"], unique=True, postgresql_where=sa.text("active"))
    op.create_table("platform_keys", *_key_columns(), sa.UniqueConstraint("version"))
    op.create_index(
        "ux_platform_keys_active", "platform_keys", [sa.text("(true)")], unique=True, postgresql_where=sa.text("active")
    )
    for stmt in (
        "ALTER TABLE data_keys ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE data_keys FORCE ROW LEVEL SECURITY",
        # Services only ever touch the key of the tenant they are scoped to.
        "CREATE POLICY data_keys_tenant ON data_keys "
        "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
        # Key administration (status, rewrap, rotate-dek) spans tenants by design.
        "CREATE POLICY data_keys_key_admin ON data_keys TO dewpoint_admin USING (true) WITH CHECK (true)",
        "GRANT SELECT, INSERT, UPDATE ON data_keys TO dewpoint_api, dewpoint_worker, dewpoint_admin",
        # Platform keys protect user TOTP secrets: needed by the API (sign-in) and key admins, never by workers.
        "GRANT SELECT, INSERT, UPDATE ON platform_keys TO dewpoint_api, dewpoint_admin",
    ):
        op.execute(stmt)


def downgrade() -> None:
    op.drop_table("platform_keys")
    op.execute("DROP POLICY IF EXISTS data_keys_key_admin ON data_keys")
    op.execute("DROP POLICY IF EXISTS data_keys_tenant ON data_keys")
    op.drop_table("data_keys")
```

Add `tests/core/crypto/test_keyring_rls.py`, which covers:
- concurrent first use creates exactly one key;
- concurrent rotations serialize to versions 2, 3, 4;
- tenant keys are invisible without context or under another tenant, and a key can't be created for another tenant;
- workers are denied the platform key;
- the admin role sees every key.

It also needs the `worker_sessionmaker` and `admin_sessionmaker` fixtures, built like `api_sessionmaker`.
```python
# SPDX-License-Identifier: Apache-2.0
import asyncio
import os
import uuid

import pytest
from cryptography.exceptions import InvalidTag
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from dewpoint.core.crypto.kek import Kek, KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.keys import DataKey, PlatformKey

KR = Keyring(KekSet(Kek("k1", os.urandom(32))))


async def test_concurrent_first_use_creates_one_key(api_sessionmaker, owner_sessionmaker) -> None:
    t = uuid.uuid4()

    async def first_use(i: int) -> bytes:
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, t)
            blob = await KR.encrypt(s, tenant_id=t, purpose="p", context=str(i), plaintext=b"x")
            await asyncio.sleep(0.1)  # keep transactions overlapping
            return blob

    blobs = await asyncio.gather(*(first_use(i) for i in range(5)))
    async with owner_sessionmaker() as s:
        assert (
            await s.execute(select(func.count()).select_from(DataKey).where(DataKey.tenant_id == t))
        ).scalar_one() == 1
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        for i, b in enumerate(blobs):
            assert await KR.decrypt(s, tenant_id=t, purpose="p", context=str(i), blob=b) == b"x"


async def test_concurrent_rotations_serialize(api_sessionmaker) -> None:
    t = uuid.uuid4()

    async def rotate() -> int:
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, t)
            v = await KR.rotate(s, t)
            await asyncio.sleep(0.1)
            return v

    assert sorted(await asyncio.gather(rotate(), rotate(), rotate())) == [2, 3, 4]


async def test_tenant_keys_are_rls_scoped(api_sessionmaker) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, a)
        blob = await KR.encrypt(s, tenant_id=a, purpose="p", context="c", plaintext=b"secret")
    async with api_sessionmaker() as s, s.begin():  # no tenant context: nothing visible
        assert (await s.execute(select(DataKey))).scalars().all() == []
    async with api_sessionmaker() as s, s.begin():  # other tenant's context: key invisible, decrypt fails
        await tenant_scope(s, b)
        assert (await s.execute(select(DataKey))).scalars().all() == []
        with pytest.raises(InvalidTag):
            await KR.decrypt(s, tenant_id=a, purpose="p", context="c", blob=blob)
    with pytest.raises(DBAPIError, match="row-level security"):  # can't create a key for another tenant
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, b)
            await KR.encrypt(s, tenant_id=a, purpose="p", context="c", plaintext=b"x")


async def test_platform_key_path_is_narrow(api_sessionmaker, worker_sessionmaker) -> None:
    async with api_sessionmaker() as s, s.begin():
        blob = await KR.encrypt(s, tenant_id=None, purpose="user.totp", context="u1", plaintext=b"totp")
        assert await KR.decrypt(s, tenant_id=None, purpose="user.totp", context="u1", blob=blob) == b"totp"
        assert (await s.execute(select(func.count()).select_from(PlatformKey))).scalar_one() == 1
    with pytest.raises(DBAPIError, match="permission denied"):
        async with worker_sessionmaker() as s, s.begin():
            await s.execute(select(PlatformKey))


async def test_admin_role_sees_all_keys(api_sessionmaker, admin_sessionmaker) -> None:
    for t in (uuid.uuid4(), uuid.uuid4()):
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, t)
            await KR.encrypt(s, tenant_id=t, purpose="p", context="c", plaintext=b"x")
    async with api_sessionmaker() as s, s.begin():
        await KR.encrypt(s, tenant_id=None, purpose="p", context="c", plaintext=b"x")
    async with admin_sessionmaker() as s, s.begin():
        assert await KR.kek_usage(s) == {"k1": 3}
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/core/crypto/test_keyring.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(core): envelope encryption keyring with AAD binding, data-key rotation and dual-KEK rewrap

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Passwords, users and the `dewpoint admin init` CLI

**Files:**
- Create: `backend/src/dewpoint/core/auth/__init__.py`, `passwords.py`, `users.py`
- Create: `backend/src/dewpoint/apps/cli/__init__.py`, `backend/src/dewpoint/apps/cli/main.py`
- Test: `backend/tests/core/auth/test_passwords.py`, `backend/tests/apps/cli/test_admin_init.py`

**Interfaces:**
- Consumes: `User` (Task 4), `make_engine`/`make_sessionmaker` (Task 3), `get_settings` (Task 2).
- Produces:
  - `hash_password(pw: str) -> str`, `verify_password(stored: str, pw: str) -> bool`, `needs_rehash(stored: str) -> bool`, `policy_violations(pw: str, email: str) -> list[str]`.
  - `async create_user(s, *, email: str, password: str, platform_admin: bool = False) -> User`, which raises `PasswordPolicyError(violations)` or `EmailTakenError`.
  - `async get_user_by_email(s, email: str) -> User | None`.
  - The Typer `app` exposing `dewpoint admin init --email E` (password read from a hidden prompt or `DEWPOINT_INIT_PASSWORD`).

- [ ] **Step 1: Write the failing tests**

`backend/tests/core/auth/test_passwords.py`:
```python
# SPDX-License-Identifier: Apache-2.0
from dewpoint.core.auth.passwords import hash_password, needs_rehash, policy_violations, verify_password


def test_hash_verify() -> None:
    h = hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "correct horse battery staple")
    assert not verify_password(h, "wrong")
    assert not needs_rehash(h)


def test_policy() -> None:
    assert "min_length" in policy_violations("short", "a@b.c")
    assert "contains_email" in policy_violations("alice-is-great-2026", "alice@corp.test")
    assert "common" in policy_violations("password1234", "x@y.z")
    assert policy_violations("violet-otter-canyon-42", "alice@corp.test") == []


def test_email_type_accepts_internal_domains_and_rejects_garbage() -> None:
    import pytest
    from pydantic import TypeAdapter, ValidationError

    from dewpoint.core.auth.users import Email

    ta = TypeAdapter(Email)
    for ok in ("dana@corp.test", "ops@site.local", "a.b+c@mist.internal", "  x@example.com "):
        assert ta.validate_python(ok) == ok.strip()
    for bad in ("", "nodomain", "@x.y", "a@", "a b@c.d", "a@b@c", "x" * 321 + "@a.b"):
        with pytest.raises(ValidationError):
            ta.validate_python(bad)
```

`backend/tests/apps/cli/test_admin_init.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import base64
import os

from sqlalchemy import select
from typer.testing import CliRunner

from dewpoint.apps.cli.main import app
from dewpoint.core.config import get_settings
from dewpoint.core.models.identity import User


def _env(pg_url: str) -> dict[str, str]:
    return {"DEWPOINT_DATABASE_URL": pg_url, "DEWPOINT_KEK_B64": base64.b64encode(os.urandom(32)).decode(),
            "DEWPOINT_PUBLIC_ORIGIN": "https://dewpoint.test", "DEWPOINT_INIT_PASSWORD": "violet-otter-canyon-42"}


def test_admin_init_creates_platform_admin_once(pg_url, monkeypatch) -> None:
    for k, v in _env(pg_url).items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    runner = CliRunner()
    first = runner.invoke(app, ["admin", "init", "--email", "root@corp.test"])
    assert first.exit_code == 0, first.output
    second = runner.invoke(app, ["admin", "init", "--email", "other@corp.test"])
    assert second.exit_code == 1
    assert "already initialized" in second.output


async def test_admin_row(owner_sessionmaker, pg_url, monkeypatch) -> None:
    for k, v in _env(pg_url).items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    import asyncio
    await asyncio.to_thread(CliRunner().invoke, app, ["admin", "init", "--email", "root@corp.test"])
    async with owner_sessionmaker() as s:
        u = (await s.execute(select(User))).scalar_one()
    assert u.is_platform_admin and u.email == "root@corp.test"
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `uv run pytest tests/core/auth/test_passwords.py tests/apps/cli -v`
Expected: FAIL (modules not found)

- [ ] **Step 3: Implement**

`core/auth/passwords.py`:
```python
# SPDX-License-Identifier: Apache-2.0
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_ph = PasswordHasher()  # argon2id, library defaults (RFC 9106 low-memory profile)
MIN_LENGTH = 12
_COMMON = frozenset({"password1234", "123456789012", "qwertyuiop12", "letmein12345", "welcome12345", "admin1234567"})


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(stored: str, pw: str) -> bool:
    try:
        return _ph.verify(stored, pw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored: str) -> bool:
    return _ph.check_needs_rehash(stored)


def policy_violations(pw: str, email: str) -> list[str]:
    out: list[str] = []
    if len(pw) < MIN_LENGTH:
        out.append("min_length")
    local = email.split("@", 1)[0].lower()
    if len(local) >= 3 and local in pw.lower():
        out.append("contains_email")
    if pw.lower() in _COMMON:
        out.append("common")
    return out
```

`core/auth/users.py`:
```python
# SPDX-License-Identifier: Apache-2.0
from datetime import UTC, datetime
from typing import Annotated

from pydantic import StringConstraints
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.auth.passwords import hash_password, policy_violations
from dewpoint.core.models.identity import User

# Deliberately lenient: self-hosted customers use internal/special-use domains (.local, .internal, .test)
# that RFC-strict validators reject. Uniqueness is case-insensitive (see ix_users_email_lower).
Email = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
]


class PasswordPolicyError(ValueError):
    def __init__(self, violations: list[str]) -> None:
        super().__init__("password policy")
        self.violations = violations


class EmailTakenError(ValueError):
    pass


async def get_user_by_email(s: AsyncSession, email: str) -> User | None:
    return (await s.execute(select(User).where(func.lower(User.email) == email.lower()))).scalar_one_or_none()


async def create_user(s: AsyncSession, *, email: str, password: str, platform_admin: bool = False) -> User:
    if v := policy_violations(password, email):
        raise PasswordPolicyError(v)
    if await get_user_by_email(s, email):
        raise EmailTakenError(email)
    user = User(
        email=email.strip(),
        password_hash=hash_password(password),
        is_platform_admin=platform_admin,
        password_changed_at=datetime.now(UTC),
    )
    s.add(user)
    await s.flush()
    return user
```

`apps/cli/main.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import asyncio
import os

import typer
from sqlalchemy import select

from dewpoint.core.auth.users import PasswordPolicyError, create_user
from dewpoint.core.config import get_settings
from dewpoint.core.db import make_engine, make_sessionmaker
from dewpoint.core.models.identity import User

app = typer.Typer(no_args_is_help=True)
admin = typer.Typer(no_args_is_help=True)
app.add_typer(admin, name="admin")


async def _init(email: str, password: str) -> None:
    engine = make_engine(get_settings().database_url)
    try:
        async with make_sessionmaker(engine)() as s, s.begin():
            if (await s.execute(select(User.id).where(User.is_platform_admin.is_(True)).limit(1))).first():
                typer.echo("already initialized: a platform admin exists")
                raise typer.Exit(1)
            await create_user(s, email=email, password=password, platform_admin=True)
    finally:
        await engine.dispose()


@admin.command("init")
def admin_init(email: str = typer.Option(...)) -> None:
    """Create the first platform admin. Refuses if one already exists."""
    password = os.environ.get("DEWPOINT_INIT_PASSWORD") or typer.prompt("Password", hide_input=True,
                                                                        confirmation_prompt=True)
    try:
        asyncio.run(_init(email, password))
    except PasswordPolicyError as e:
        typer.echo(f"password rejected: {', '.join(e.violations)}")
        raise typer.Exit(2) from None
    typer.echo(f"platform admin {email} created. Sign in to enroll MFA.")
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/core/auth/test_passwords.py tests/apps/cli -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(auth): argon2id passwords, policy, user creation and admin init CLI

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 7: Server-side sessions, CSRF, and request dependencies

**Files:**
- Create: `backend/src/dewpoint/core/auth/sessions.py`, `backend/src/dewpoint/core/http.py`
- Modify: `backend/src/dewpoint/apps/api/main.py` (engine and sessionmaker on `app.state`, `ClientHeaderMiddleware`)
- Modify: `backend/src/dewpoint/apps/api/middleware.py` (add `ClientHeaderMiddleware`)
- Modify: `backend/tests/conftest.py` (add the `api_settings`, `app` and `client` fixtures)
- Test: `backend/tests/core/auth/test_sessions.py`, `backend/tests/apps/api/test_csrf.py`

**Interfaces:**
- Consumes: `AuthSession`, `User` (Task 4); `Settings` (Task 2).
- Produces:
  - `SESSION_COOKIE = "__Host-dewpoint_session"`.
  - `async create_session(s, *, user_id, state, methods, settings, ip, user_agent) -> tuple[AuthSession, str]`.
  - `async load_session(s, token: str, settings, now: datetime | None = None) -> AuthSession | None`.
  - `async elevate(s, sess, *, method: str, state: str = "active") -> str`: appends the method, sets the state, **rotates the token**, and returns the new token.
  - `async revoke(s, sess)` and `async revoke_all(s, user_id, except_id: UUID | None = None)`.
  - `set_session_cookie(response, token, settings)` and `clear_session_cookie(response)`.
  - Dependencies in `dewpoint.core.http`:
    - `get_db` (a request-scoped `AsyncSession` inside a transaction);
    - `current_session` (any state; 401 `{"error":"unauthenticated"}`; enforces CSRF on unsafe methods);
    - `active_session` (state must be `active`, else 403 `{"error":"mfa_required"}`);
    - `current_user` (returns the `User` for the active session).
  - `ClientHeaderMiddleware`: unsafe methods under `/api/` must carry `X-Dewpoint-Client: web`, else 403. This custom header forces a CORS preflight and blocks cross-site form posts, including on the unauthenticated login endpoint.
  - Test fixtures: `api_settings`, `app`, and `client` (an `httpx.AsyncClient` on `https://testserver` with `X-Dewpoint-Client: web` preset).

- [ ] **Step 1: Write the failing tests**

`backend/tests/core/auth/test_sessions.py`:
```python
# SPDX-License-Identifier: Apache-2.0
from datetime import UTC, datetime, timedelta

from dewpoint.core.auth.sessions import create_session, elevate, load_session, revoke_all
from dewpoint.core.auth.users import create_user


async def _user(s):
    return await create_user(s, email="a@corp.test", password="violet-otter-canyon-42")


async def test_create_load_and_rotate(owner_sessionmaker, api_settings) -> None:
    async with owner_sessionmaker() as s, s.begin():
        u = await _user(s)
        sess, token = await create_session(s, user_id=u.id, state="mfa_pending", methods=["password"],
                                           settings=api_settings, ip="192.0.2.1", user_agent="t")
        assert (await load_session(s, token, api_settings)).id == sess.id
        new_token = await elevate(s, sess, method="totp")
        assert new_token != token
        assert await load_session(s, token, api_settings) is None
        loaded = await load_session(s, new_token, api_settings)
        assert loaded.state == "active" and loaded.auth_methods == ["password", "totp"]


async def test_idle_and_absolute_expiry(owner_sessionmaker, api_settings) -> None:
    async with owner_sessionmaker() as s, s.begin():
        u = await _user(s)
        _, token = await create_session(s, user_id=u.id, state="active", methods=["password"],
                                        settings=api_settings, ip=None, user_agent=None)
        now = datetime.now(UTC)
        assert await load_session(s, token, api_settings, now=now + timedelta(minutes=31)) is None
        assert await load_session(s, token, api_settings, now=now + timedelta(hours=13)) is None


async def test_revoke_all_keeps_current(owner_sessionmaker, api_settings) -> None:
    async with owner_sessionmaker() as s, s.begin():
        u = await _user(s)
        keep, t1 = await create_session(s, user_id=u.id, state="active", methods=[], settings=api_settings,
                                        ip=None, user_agent=None)
        _, t2 = await create_session(s, user_id=u.id, state="active", methods=[], settings=api_settings,
                                     ip=None, user_agent=None)
        await revoke_all(s, u.id, except_id=keep.id)
        assert await load_session(s, t1, api_settings) is not None
        assert await load_session(s, t2, api_settings) is None
```

`backend/tests/apps/api/test_csrf.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import httpx
from fastapi import APIRouter, Depends

from dewpoint.core.auth.sessions import SESSION_COOKIE, create_session
from dewpoint.core.auth.users import create_user
from dewpoint.core.http import active_session


async def test_unsafe_request_requires_client_header_and_csrf(app, owner_sessionmaker, api_settings) -> None:
    router = APIRouter()

    @router.post("/api/v1/_probe")
    async def probe(_=Depends(active_session)) -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router)
    async with owner_sessionmaker() as s, s.begin():
        u = await create_user(s, email="c@corp.test", password="violet-otter-canyon-42")
        sess, token = await create_session(s, user_id=u.id, state="active", methods=["password", "totp"],
                                           settings=api_settings, ip=None, user_agent=None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver",
                                 cookies={SESSION_COOKIE: token}) as c:
        assert (await c.post("/api/v1/_probe")).status_code == 403  # no client header
        h = {"X-Dewpoint-Client": "web"}
        assert (await c.post("/api/v1/_probe", headers=h)).status_code == 403  # no csrf
        h["X-CSRF-Token"] = sess.csrf_token
        r = await c.post("/api/v1/_probe", headers=h)
        assert r.status_code == 200 and r.json() == {"ok": True}
```

- [ ] **Step 2: Add the fixtures to `tests/conftest.py`**

```python
import base64
import httpx
from dewpoint.apps.api.main import create_app
from dewpoint.core.config import Settings


@pytest.fixture(scope="session")
def api_settings(pg_url: str, _test_users: None) -> Settings:
    return Settings(database_url=_url_for(pg_url, "dewpoint_api"), kek_b64=base64.b64encode(b"k" * 32).decode(),
                    public_origin="https://testserver", rp_id="testserver")


@pytest.fixture
async def app(api_settings: Settings):
    application = create_app(api_settings)
    yield application
    await application.state.engine.dispose()


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver",
                                 headers={"X-Dewpoint-Client": "web"}) as c:
        yield c
```

- [ ] **Step 3: Run the tests to confirm they fail**

Run: `uv run pytest tests/core/auth/test_sessions.py tests/apps/api/test_csrf.py -v`
Expected: FAIL (module not found)

- [ ] **Step 4: Implement**

`core/auth/sessions.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.config import Settings
from dewpoint.core.models.identity import AuthSession

SESSION_COOKIE = "__Host-dewpoint_session"
TOUCH_EVERY = timedelta(seconds=60)


SameSite = Literal["lax", "strict", "none"]


class _CookieResponse(Protocol):
    """The cookie API of a Starlette response, without importing a web framework into core."""

    def set_cookie(
        self,
        key: str,
        value: str = ...,
        *,
        max_age: int | None = ...,
        path: str | None = ...,
        secure: bool = ...,
        httponly: bool = ...,
        samesite: SameSite | None = ...,
    ) -> None: ...

    def delete_cookie(
        self, key: str, *, path: str = ..., secure: bool = ..., httponly: bool = ..., samesite: SameSite | None = ...
    ) -> None: ...


def _hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


async def create_session(
    s: AsyncSession,
    *,
    user_id: uuid.UUID,
    state: str,
    methods: list[str],
    settings: Settings,
    ip: str | None,
    user_agent: str | None,
    reauth: bool = False,
) -> tuple[AuthSession, str]:
    """reauth=True when the session starts with a proven second factor (passkey with user verification)."""
    token, now = secrets.token_urlsafe(32), datetime.now(UTC)
    sess = AuthSession(
        token_hash=_hash(token),
        user_id=user_id,
        state=state,
        auth_methods=list(methods),
        csrf_token=secrets.token_urlsafe(32),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_absolute_hours),
        ip=ip,
        user_agent=(user_agent or "")[:400] or None,
        reauth_at=now if reauth else None,
    )
    s.add(sess)
    await s.flush()
    return sess, token


async def load_session(
    s: AsyncSession, token: str, settings: Settings, now: datetime | None = None
) -> AuthSession | None:
    now = now or datetime.now(UTC)
    sess = (await s.execute(select(AuthSession).where(AuthSession.token_hash == _hash(token)))).scalar_one_or_none()
    if sess is None or sess.revoked_at is not None or now >= sess.expires_at:
        return None
    if now - sess.last_seen_at > timedelta(minutes=settings.session_idle_minutes):
        return None
    if now - sess.last_seen_at > TOUCH_EVERY:
        sess.last_seen_at = now
    return sess


async def rotate(s: AsyncSession, sess: AuthSession) -> str:
    """New session token and CSRF token after any privilege-relevant change. Returns the new token."""
    token = secrets.token_urlsafe(32)
    sess.token_hash, sess.csrf_token = _hash(token), secrets.token_urlsafe(32)
    await s.flush()
    return token


async def elevate(s: AsyncSession, sess: AuthSession, *, method: str, state: str = "active") -> str:
    """Record a proven factor: append the method, stamp reauth_at, set the state and rotate tokens."""
    sess.state = state
    sess.auth_methods = [*sess.auth_methods, method]
    sess.reauth_at = datetime.now(UTC)
    return await rotate(s, sess)


def reauth_fresh(sess: AuthSession, settings: Settings, now: datetime | None = None) -> bool:
    if sess.reauth_at is None:
        return False
    return (now or datetime.now(UTC)) - sess.reauth_at <= timedelta(minutes=settings.reauth_minutes)


async def revoke(s: AsyncSession, sess: AuthSession) -> None:
    sess.revoked_at = datetime.now(UTC)
    await s.flush()


async def revoke_all(s: AsyncSession, user_id: uuid.UUID, except_id: uuid.UUID | None = None) -> None:
    q = update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    if except_id:
        q = q.where(AuthSession.id != except_id)
    await s.execute(q.values(revoked_at=datetime.now(UTC)))


def csrf_valid(sess: AuthSession, header: str | None) -> bool:
    return bool(header) and hmac.compare_digest(sess.csrf_token, header or "")


def set_session_cookie(response: _CookieResponse, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        max_age=settings.session_absolute_hours * 3600,
    )


def clear_session_cookie(response: _CookieResponse) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
```

`core/http.py`:
```python
# SPDX-License-Identifier: Apache-2.0
from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.auth.sessions import SESSION_COOKIE, csrf_valid, load_session
from dewpoint.core.config import Settings
from dewpoint.core.models.identity import AuthSession, User

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as s, s.begin():
        yield s


async def current_session(request: Request, db: AsyncSession = Depends(get_db),
                          settings: Settings = Depends(get_settings_dep)) -> AuthSession:
    token = request.cookies.get(SESSION_COOKIE)
    sess = await load_session(db, token, settings) if token else None
    if sess is None:
        raise HTTPException(401, detail={"error": "unauthenticated"})
    if request.method not in SAFE_METHODS and not csrf_valid(sess, request.headers.get("X-CSRF-Token")):
        raise HTTPException(403, detail={"error": "csrf"})
    return sess


async def active_session(sess: AuthSession = Depends(current_session)) -> AuthSession:
    if sess.state != "active":
        raise HTTPException(403, detail={"error": "mfa_required", "state": sess.state})
    return sess


async def current_user(sess: AuthSession = Depends(active_session), db: AsyncSession = Depends(get_db)) -> User:
    user = await db.get(User, sess.user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, detail={"error": "unauthenticated"})
    return user
```
FastAPI caches `get_db` per request, so every dependency shares one transaction.

Add to `apps/api/middleware.py`:
```python
from starlette.responses import JSONResponse


class ClientHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("X-Dewpoint-Client") != "web":
                return JSONResponse({"error": "forbidden"}, status_code=403)
        return await call_next(request)
```

In `create_app`, after `app.state.settings = settings`:
```python
    app.state.engine = make_engine(settings.database_url)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)
    app.add_middleware(ClientHeaderMiddleware)
```
(import `make_engine` and `make_sessionmaker` from `dewpoint.core.db`). Error bodies are already flat `{"error": …}` thanks to Task 2's handlers; the CSRF test above asserts status codes, and Task 10's step-up test asserts the exact body.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/core/auth/test_sessions.py tests/apps/api -v`
Expected: all PASS, including Task 2's tests.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(auth): server-side sessions with rotation, idle/absolute expiry, CSRF and client header

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Login, lockout, TOTP, recovery codes, password change

**Files:**
- Create: `backend/src/dewpoint/core/auth/throttle.py`, `backend/src/dewpoint/core/auth/totp.py`
- Create: `backend/src/dewpoint/apps/api/routes/auth.py`, `backend/src/dewpoint/apps/api/routes/mfa.py`, `backend/src/dewpoint/apps/api/deps.py`
- Modify: `backend/src/dewpoint/apps/api/main.py` (include the routers)
- Test: `backend/tests/core/auth/test_throttle.py`, `backend/tests/apps/api/test_login_flow.py`

**Interfaces:**
- Consumes: sessions (Task 7), passwords and users (Task 6), `Keyring` and `KekSet` (Task 5), `UserMfa` and `RecoveryCode` (Task 4).
- Produces:
  - `throttle.is_locked(s, kind, key, now=None) -> bool`, `throttle.record_failure(s, kind, key, settings, now=None) -> None`, `throttle.reset(s, kind, key) -> None`.
  - `totp.start_enrollment(s, keyring, user) -> str` (an otpauth URI), `totp.confirm_enrollment(s, keyring, user, code) -> list[str]` (10 recovery codes, shown once), `totp.verify(s, keyring, user, code) -> bool` (with replay protection), `totp.use_recovery_code(s, user, code) -> bool`, `totp.has_totp(s, user_id) -> bool`.
  - `apps/api/deps.py`: `get_keyring(request) -> Keyring`. `create_app` stores `app.state.keyring = Keyring(KekSet.from_settings(settings))`.
  - HTTP endpoints, all under `/api/v1/auth`:
    - `POST /login` `{email,password}` → `{state, csrf_token}` and sets the cookie. States: `mfa_pending`, `enroll_required`, `active`.
    - `POST /mfa/totp` `{code}` and `POST /mfa/recovery` `{code}`: valid only from `mfa_pending` → `{state:"active", csrf_token}`.
    - `POST /mfa/totp/enroll` → `{otpauth_uri}` (valid in `enroll_required` or `active`).
    - `POST /mfa/totp/confirm` `{code}` → `{recovery_codes, state, csrf_token}`.
    - `GET /session` → `{user:{id,email,is_platform_admin}, state, auth_methods, csrf_token}`.
    - `POST /logout` → 204.
    - `POST /password` `{current_password,new_password}` → **200 `{csrf_token}`**. It revokes all other sessions and rotates the current session's token without elevating it, because a password isn't a second factor. The client uses the returned CSRF token for its next unsafe request.
    - `POST /mfa/totp/reauth` `{code}` (session `active`, throttled) → `{state, csrf_token}`. It re-proves the confirmed TOTP and stamps `sessions.reauth_at`.
  - **Changing factors:**
    - `/totp/enroll` stages a *pending* secret (`user_mfa.totp_pending_ct`, which expires after `totp_pending_minutes`). The confirmed secret stays in force until `/totp/confirm` verifies a code from the pending one.
    - From an `active` session, `/totp/enroll`, `/totp/confirm`, `/passkeys/register/options` and `/passkeys/register/verify` require `reauth_at` within `reauth_minutes`, else 403 `{"error":"reauth_required"}`. Completion is re-checked because a pending secret (10 minutes) or challenge (5 minutes) can outlive the reauth window, and a 403 doesn't consume the pending secret or challenge. `enroll_required` sessions have no factor yet, so they're exempt.
    - `elevate()` stamps `reauth_at`. `rotate()` issues new session and CSRF tokens without elevating.

- [ ] **Step 1: Write the failing tests**

`backend/tests/core/auth/test_throttle.py`:
```python
# SPDX-License-Identifier: Apache-2.0
from datetime import UTC, datetime, timedelta

from dewpoint.core.auth import throttle


async def test_locks_after_max_failures_then_expires(owner_sessionmaker, api_settings) -> None:
    now = datetime.now(UTC)
    async with owner_sessionmaker() as s, s.begin():
        for _ in range(api_settings.login_max_failures):
            assert not await throttle.is_locked(s, "login_email", "a@x.test", now)
            await throttle.record_failure(s, "login_email", "a@x.test", api_settings, now)
        assert await throttle.is_locked(s, "login_email", "a@x.test", now)
        later = now + timedelta(minutes=api_settings.login_lockout_minutes + 1)
        assert not await throttle.is_locked(s, "login_email", "a@x.test", later)
        await throttle.reset(s, "login_email", "a@x.test")


async def test_ip_threshold_is_separate_and_higher(owner_sessionmaker, api_settings) -> None:
    assert api_settings.login_ip_max_failures > api_settings.login_max_failures
    async with owner_sessionmaker() as s, s.begin():
        for _ in range(api_settings.login_max_failures):
            await throttle.record_failure(s, "login_ip", "192.0.2.7", api_settings)
        assert not await throttle.is_locked(s, "login_ip", "192.0.2.7")
        for _ in range(api_settings.login_ip_max_failures - api_settings.login_max_failures):
            await throttle.record_failure(s, "login_ip", "192.0.2.7", api_settings)
        assert await throttle.is_locked(s, "login_ip", "192.0.2.7")
```

`backend/tests/apps/api/test_login_flow.py` (see also `tests/apps/api/test_factor_changes.py`, which covers: an abandoned TOTP setup keeps the old factor; replacement needs fresh reauth; an expired pending setup can't be confirmed; adding a passkey while active needs reauth and rotates tokens; password change returns the new CSRF token; anonymous options are rate-limited; expired challenges are purged; outstanding challenges are capped):
```python
# SPDX-License-Identifier: Apache-2.0
from urllib.parse import parse_qs, urlparse

import pyotp
from sqlalchemy import text

from dewpoint.core.auth.users import create_user

PW = "violet-otter-canyon-42"


async def _seed(owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s, s.begin():
        await create_user(s, email="dana@corp.test", password=PW)


async def test_enroll_then_login_with_totp(client, owner_sessionmaker) -> None:
    await _seed(owner_sessionmaker)
    r = await client.post("/api/v1/auth/login", json={"email": "dana@corp.test", "password": PW})
    assert r.status_code == 200 and r.json()["state"] == "enroll_required"
    csrf = r.json()["csrf_token"]
    uri = (await client.post("/api/v1/auth/mfa/totp/enroll", headers={"X-CSRF-Token": csrf})).json()["otpauth_uri"]
    secret = parse_qs(urlparse(uri).query)["secret"][0]
    r = await client.post(
        "/api/v1/auth/mfa/totp/confirm", json={"code": pyotp.TOTP(secret).now()}, headers={"X-CSRF-Token": csrf}
    )
    body = r.json()
    assert r.status_code == 200 and body["state"] == "active" and len(body["recovery_codes"]) == 10
    csrf = body["csrf_token"]
    assert (await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})).status_code == 204

    r = await client.post("/api/v1/auth/login", json={"email": "dana@corp.test", "password": PW})
    assert r.json()["state"] == "mfa_pending"
    csrf = r.json()["csrf_token"]
    # the same TOTP code must not be accepted twice (replay)
    code = pyotp.TOTP(secret).now()
    r = await client.post("/api/v1/auth/mfa/totp", json={"code": code}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 401
    r = await client.post(
        "/api/v1/auth/mfa/recovery", json={"code": body["recovery_codes"][0]}, headers={"X-CSRF-Token": csrf}
    )
    assert r.status_code == 200 and r.json()["state"] == "active"
    me = (await client.get("/api/v1/auth/session")).json()
    assert me["user"]["email"] == "dana@corp.test" and me["auth_methods"] == ["password", "recovery"]


async def test_bad_password_is_generic_and_locks(client, owner_sessionmaker, api_settings) -> None:
    await _seed(owner_sessionmaker)
    for _ in range(api_settings.login_max_failures):
        r = await client.post("/api/v1/auth/login", json={"email": "dana@corp.test", "password": "nope-nope-nope"})
        assert r.status_code == 401 and r.json() == {"error": "invalid_credentials"}
    r = await client.post("/api/v1/auth/login", json={"email": "dana@corp.test", "password": PW})
    assert r.status_code == 429 and r.json() == {"error": "locked"}
    # an unknown account gets the same generic answer; the shared client IP is still under its own higher limit
    r = await client.post("/api/v1/auth/login", json={"email": "ghost@corp.test", "password": PW})
    assert r.status_code == 401 and r.json() == {"error": "invalid_credentials"}


async def test_enrollment_confirm_is_throttled(client, owner_sessionmaker, api_settings) -> None:
    await _seed(owner_sessionmaker)
    csrf = (await client.post("/api/v1/auth/login", json={"email": "dana@corp.test", "password": PW})).json()[
        "csrf_token"
    ]
    await client.post("/api/v1/auth/mfa/totp/enroll", headers={"X-CSRF-Token": csrf})
    for _ in range(api_settings.login_max_failures):
        r = await client.post("/api/v1/auth/mfa/totp/confirm", json={"code": "000000"}, headers={"X-CSRF-Token": csrf})
        assert r.status_code == 401
    r = await client.post("/api/v1/auth/mfa/totp/confirm", json={"code": "000000"}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 429 and r.json() == {"error": "locked"}


async def test_password_change_revokes_other_sessions(app, owner_sessionmaker) -> None:
    import httpx

    await _seed(owner_sessionmaker)
    t = httpx.ASGITransport(app=app)
    h = {"X-Dewpoint-Client": "web"}
    async with (
        httpx.AsyncClient(transport=t, base_url="https://testserver", headers=h) as a,
        httpx.AsyncClient(transport=t, base_url="https://testserver", headers=h) as b,
    ):
        for c in (a, b):
            r = await c.post("/api/v1/auth/login", json={"email": "dana@corp.test", "password": PW})
            c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        async with owner_sessionmaker() as s, s.begin():  # both sessions completed MFA (not under test here)
            await s.execute(text("update sessions set state = 'active'"))
        r = await a.post(
            "/api/v1/auth/password", json={"current_password": PW, "new_password": "amber-heron-valley-77"}
        )
        assert r.status_code == 200 and "csrf_token" in r.json()
        assert (await b.get("/api/v1/auth/session")).status_code == 401
        assert (await a.get("/api/v1/auth/session")).status_code == 200
```
**Note on the MFA-policy test setting:** `api_settings.mfa_required` is `True`, so a fresh user is always `enroll_required`. Task 10 adds the check that an `enroll_required` session gets 403 on tenant APIs.

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `uv run pytest tests/core/auth/test_throttle.py tests/apps/api/test_login_flow.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement the throttle and TOTP**

`core/auth/throttle.py`:
```python
# SPDX-License-Identifier: Apache-2.0
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.config import Settings
from dewpoint.core.models.identity import AuthThrottle

WINDOW = timedelta(minutes=15)


async def consume(s: AsyncSession, kind: str, key: str, limit: int, now: datetime | None = None) -> bool:
    """Count one use of a rate-limited action in the current window. False once `limit` uses are exceeded."""
    now, key = now or datetime.now(UTC), key.lower()
    await s.execute(
        insert(AuthThrottle).values(kind=kind, key=key, failures=0, window_start=now).on_conflict_do_nothing()
    )
    row = await s.get(AuthThrottle, (kind, key), with_for_update=True)
    if row is None:  # inserted just above; only reachable if the row was deleted concurrently
        raise RuntimeError("auth_throttle row vanished")
    if now - row.window_start > WINDOW:
        row.failures, row.window_start = 0, now
    row.failures += 1
    await s.flush()
    return row.failures <= limit


async def purge_stale(s: AsyncSession, now: datetime | None = None, limit: int = 500) -> int:
    """Delete up to `limit` throttle rows whose window and lockout are both over."""
    now = now or datetime.now(UTC)
    doomed = (
        select(AuthThrottle.kind, AuthThrottle.key)
        .where(
            AuthThrottle.window_start < now - WINDOW,
            (AuthThrottle.locked_until.is_(None)) | (AuthThrottle.locked_until < now),
        )
        .limit(limit)
    )
    result = await s.execute(
        delete(AuthThrottle).where(tuple_(AuthThrottle.kind, AuthThrottle.key).in_(doomed.subquery().select()))
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def is_locked(s: AsyncSession, kind: str, key: str, now: datetime | None = None) -> bool:
    row = await s.get(AuthThrottle, (kind, key.lower()))
    return bool(row and row.locked_until and row.locked_until > (now or datetime.now(UTC)))


async def record_failure(s: AsyncSession, kind: str, key: str, settings: Settings, now: datetime | None = None) -> None:
    now, key = now or datetime.now(UTC), key.lower()
    await s.execute(
        insert(AuthThrottle).values(kind=kind, key=key, failures=0, window_start=now).on_conflict_do_nothing()
    )
    row = await s.get(AuthThrottle, (kind, key), with_for_update=True)
    if row is None:  # inserted just above; only reachable if the row was deleted concurrently
        raise RuntimeError("auth_throttle row vanished")
    if now - row.window_start > WINDOW:
        row.failures, row.window_start, row.locked_until = 0, now, None
    row.failures += 1
    limit = settings.login_ip_max_failures if kind == "login_ip" else settings.login_max_failures
    if row.failures >= limit:
        row.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
    await s.flush()


async def reset(s: AsyncSession, kind: str, key: str) -> None:
    await s.execute(delete(AuthThrottle).where(AuthThrottle.kind == kind, AuthThrottle.key == key.lower()))
```

`core/auth/totp.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import secrets
import time
from datetime import UTC, datetime, timedelta

import pyotp
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.auth.passwords import hash_password, verify_password
from dewpoint.core.config import Settings
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.models.identity import RecoveryCode, User, UserMfa

ISSUER = "Dewpoint"
PURPOSE = "user.totp"


async def has_totp(s: AsyncSession, user_id: object) -> bool:
    row = await s.get(UserMfa, user_id)
    return bool(row and row.totp_confirmed_at)


def _context(user: User, *, pending: bool) -> str:
    # Distinct AAD contexts: a pending ciphertext can't be copied into the confirmed slot (or vice versa).
    return f"{user.id}:pending" if pending else str(user.id)


async def start_enrollment(s: AsyncSession, keyring: Keyring, user: User, settings: Settings) -> str:
    """Stage a new secret. The confirmed factor (if any) stays in force until confirm_enrollment succeeds."""
    secret = pyotp.random_base32()
    ct = await keyring.encrypt(
        s, tenant_id=None, purpose=PURPOSE, context=_context(user, pending=True), plaintext=secret.encode()
    )
    row = await s.get(UserMfa, user.id, with_for_update=True) or UserMfa(user_id=user.id)
    row.totp_pending_ct = ct
    row.totp_pending_expires_at = datetime.now(UTC) + timedelta(minutes=settings.totp_pending_minutes)
    s.add(row)
    await s.flush()
    return pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=ISSUER)


def _match(secret: str, code: str, last_step: int | None) -> int | None:
    """The matching time step (current +/- 1) newer than last_step, else None."""
    if not code.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    current = totp.timecode(datetime.fromtimestamp(time.time(), UTC))
    for step in (current - 1, current, current + 1):
        if step > (last_step if last_step is not None else -1) and secrets.compare_digest(
            totp.generate_otp(step), code
        ):
            return step
    return None


async def _secret(s: AsyncSession, keyring: Keyring, user: User, blob: bytes, *, pending: bool) -> str:
    raw = await keyring.decrypt(s, tenant_id=None, purpose=PURPOSE, context=_context(user, pending=pending), blob=blob)
    return raw.decode()


async def confirm_enrollment(s: AsyncSession, keyring: Keyring, user: User, code: str) -> list[str] | None:
    """Promote the pending secret to the confirmed factor. Returns fresh recovery codes, or None."""
    row = await s.get(UserMfa, user.id, with_for_update=True)
    if row is None or row.totp_pending_ct is None or row.totp_pending_expires_at is None:
        return None
    if row.totp_pending_expires_at <= datetime.now(UTC):
        return None
    secret = await _secret(s, keyring, user, row.totp_pending_ct, pending=True)
    step = _match(secret, code, None)
    if step is None:
        return None
    row.totp_secret_ct = await keyring.encrypt(
        s, tenant_id=None, purpose=PURPOSE, context=_context(user, pending=False), plaintext=secret.encode()
    )
    row.totp_confirmed_at, row.last_totp_step = datetime.now(UTC), step
    row.totp_pending_ct, row.totp_pending_expires_at = None, None
    await s.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    codes = [f"{secrets.token_hex(4)}-{secrets.token_hex(4)}" for _ in range(10)]
    s.add_all(RecoveryCode(user_id=user.id, code_hash=hash_password(c)) for c in codes)
    await s.flush()
    return codes


async def verify(s: AsyncSession, keyring: Keyring, user: User, code: str) -> bool:
    """Check a code against the confirmed factor only, with replay protection."""
    row = await s.get(UserMfa, user.id, with_for_update=True)
    if row is None or row.totp_confirmed_at is None or row.totp_secret_ct is None:
        return False
    step = _match(await _secret(s, keyring, user, row.totp_secret_ct, pending=False), code, row.last_totp_step)
    if step is None:
        return False
    row.last_totp_step = step
    await s.flush()
    return True


async def use_recovery_code(s: AsyncSession, user: User, code: str) -> bool:
    rows = (
        (
            await s.execute(
                select(RecoveryCode)
                .where(RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None))
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for rc in rows:
        if verify_password(rc.code_hash, code.strip().lower()):
            rc.used_at = datetime.now(UTC)
            await s.flush()
            return True
    return False
```

**Replay-test note:** in `test_enroll_then_login_with_totp`, confirming enrollment consumes the current step, so reusing the same `now()` code at login is rejected. That's the behaviour under test.

- [ ] **Step 4: Implement the routes**

`apps/api/deps.py`:
```python
# SPDX-License-Identifier: Apache-2.0
from fastapi import Request

from dewpoint.core.crypto.keyring import Keyring


def get_keyring(request: Request) -> Keyring:
    return request.app.state.keyring  # type: ignore[no-any-return]
```

`apps/api/routes/auth.py`:
```python
# SPDX-License-Identifier: Apache-2.0
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.auth import throttle, totp
from dewpoint.core.auth.passwords import hash_password, policy_violations, verify_password
from dewpoint.core.auth.sessions import (
    clear_session_cookie,
    create_session,
    revoke,
    revoke_all,
    rotate,
    set_session_cookie,
)
from dewpoint.core.auth.users import Email, get_user_by_email
from dewpoint.core.config import Settings
from dewpoint.core.http import current_session, current_user, get_db, get_settings_dep
from dewpoint.core.models.identity import AuthSession, User, WebauthnCredential

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
_DUMMY_HASH = hash_password("dewpoint-timing-equalizer")


class LoginIn(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=1024)


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


async def initial_state(db: AsyncSession, user: User, settings: Settings) -> str:
    has_passkey = (
        await db.execute(select(WebauthnCredential.id).where(WebauthnCredential.user_id == user.id).limit(1))
    ).first() is not None
    if has_passkey or await totp.has_totp(db, user.id):
        return "mfa_pending"
    return "enroll_required" if settings.mfa_required else "active"


@router.post("/login")
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    ip = request.client.host if request.client else "unknown"
    if await throttle.is_locked(db, "login_email", body.email) or await throttle.is_locked(db, "login_ip", ip):
        raise HTTPException(429, detail={"error": "locked"})
    user = await get_user_by_email(db, body.email)
    ok = verify_password(user.password_hash if user else _DUMMY_HASH, body.password) and bool(user and user.is_active)
    if not ok or user is None:
        await throttle.record_failure(db, "login_email", body.email, settings)
        await throttle.record_failure(db, "login_ip", ip, settings)
        await db.commit()  # persist failure counters despite the error response
        raise HTTPException(401, detail={"error": "invalid_credentials"})
    await throttle.reset(db, "login_email", body.email)
    state = await initial_state(db, user, settings)
    sess, token = await create_session(
        db,
        user_id=user.id,
        state=state,
        methods=["password"],
        settings=settings,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    set_session_cookie(response, token, settings)
    return {"state": state, "csrf_token": sess.csrf_token}


@router.get("/session")
async def session_info(
    sess: AuthSession = Depends(current_session), db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    user = await db.get(User, sess.user_id)
    if user is None:  # deleted while signed in
        raise HTTPException(401, detail={"error": "unauthenticated"})
    return {
        "user": {"id": str(user.id), "email": user.email, "is_platform_admin": user.is_platform_admin},
        "state": sess.state,
        "auth_methods": sess.auth_methods,
        "csrf_token": sess.csrf_token,
    }


@router.post("/logout", status_code=204)
async def logout(
    response: Response, sess: AuthSession = Depends(current_session), db: AsyncSession = Depends(get_db)
) -> Response:
    await revoke(db, sess)
    clear_session_cookie(response)
    response.status_code = 204
    return response


@router.post("/password")
async def change_password(
    body: PasswordIn,
    response: Response,
    user: User = Depends(current_user),
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    """Returns the rotated CSRF token so the client can make its next unsafe request."""
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(401, detail={"error": "invalid_credentials"})
    if v := policy_violations(body.new_password, user.email):
        raise HTTPException(422, detail={"error": "password_policy", "violations": v})
    from datetime import UTC, datetime

    user.password_hash, user.password_changed_at = hash_password(body.new_password), datetime.now(UTC)
    await revoke_all(db, user.id, except_id=sess.id)
    token = await rotate(db, sess)  # a password is not a second factor: rotate, don't elevate
    set_session_cookie(response, token, settings)
    return {"csrf_token": sess.csrf_token}
```
**Note:** `elevate()` appends `"password_change"` to `auth_methods`. That's intentional: it records that the session re-proved the password.

`apps/api/routes/mfa.py`:
```python
# SPDX-License-Identifier: Apache-2.0
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps.api.deps import get_keyring
from dewpoint.core.auth import throttle, totp
from dewpoint.core.auth.sessions import elevate, set_session_cookie
from dewpoint.core.config import Settings
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.http import current_session, ensure_fresh_reauth, get_db, get_settings_dep
from dewpoint.core.models.identity import AuthSession, User

router = APIRouter(prefix="/api/v1/auth/mfa", tags=["auth"])


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=32)


async def _user(db: AsyncSession, sess: AuthSession) -> User:
    user = await db.get(User, sess.user_id)
    if user is None:  # deleted while signing in
        raise HTTPException(401, detail={"error": "unauthenticated"})
    return user


def _require_state(sess: AuthSession, *states: str) -> None:
    if sess.state not in states:
        raise HTTPException(409, detail={"error": "wrong_state", "state": sess.state})


async def _complete(
    db: AsyncSession, sess: AuthSession, response: Response, settings: Settings, method: str
) -> dict[str, str]:
    token = await elevate(db, sess, method=method, state="active")
    set_session_cookie(response, token, settings)
    return {"state": "active", "csrf_token": sess.csrf_token}


async def _second_factor(
    kind: str,
    body: CodeIn,
    response: Response,
    sess: AuthSession,
    db: AsyncSession,
    keyring: Keyring,
    settings: Settings,
) -> dict[str, str]:
    _require_state(sess, "mfa_pending")
    key = str(sess.user_id)
    if await throttle.is_locked(db, "mfa_user", key):
        raise HTTPException(429, detail={"error": "locked"})
    user = await _user(db, sess)
    ok = (
        await totp.verify(db, keyring, user, body.code)
        if kind == "totp"
        else await totp.use_recovery_code(db, user, body.code)
    )
    if not ok:
        await throttle.record_failure(db, "mfa_user", key, settings)
        await db.commit()
        raise HTTPException(401, detail={"error": "invalid_code"})
    await throttle.reset(db, "mfa_user", key)
    return await _complete(db, sess, response, settings, kind)


@router.post("/totp")
async def mfa_totp(
    body: CodeIn,
    response: Response,
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    keyring: Keyring = Depends(get_keyring),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    return await _second_factor("totp", body, response, sess, db, keyring, settings)


@router.post("/recovery")
async def mfa_recovery(
    body: CodeIn,
    response: Response,
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    keyring: Keyring = Depends(get_keyring),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    return await _second_factor("recovery", body, response, sess, db, keyring, settings)


@router.post("/totp/enroll")
async def enroll(
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    keyring: Keyring = Depends(get_keyring),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    """Stage a new TOTP secret. An existing confirmed factor stays in force until /totp/confirm succeeds."""
    _require_state(sess, "enroll_required", "active")
    ensure_fresh_reauth(sess, settings)
    return {"otpauth_uri": await totp.start_enrollment(db, keyring, await _user(db, sess), settings)}


@router.post("/totp/reauth")
async def reauth(
    body: CodeIn,
    response: Response,
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    keyring: Keyring = Depends(get_keyring),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    """Prove the confirmed TOTP again from an active session (before changing factors)."""
    _require_state(sess, "active")
    key = str(sess.user_id)
    if await throttle.is_locked(db, "mfa_user", key):
        raise HTTPException(429, detail={"error": "locked"})
    if not await totp.verify(db, keyring, await _user(db, sess), body.code):
        await throttle.record_failure(db, "mfa_user", key, settings)
        await db.commit()
        raise HTTPException(401, detail={"error": "invalid_code"})
    await throttle.reset(db, "mfa_user", key)
    return await _complete(db, sess, response, settings, "totp")


@router.post("/totp/confirm")
async def confirm(
    body: CodeIn,
    response: Response,
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    keyring: Keyring = Depends(get_keyring),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, object]:
    _require_state(sess, "enroll_required", "active")
    ensure_fresh_reauth(sess, settings)  # re-checked here: the pending secret outlives the reauth window
    key = str(sess.user_id)
    if await throttle.is_locked(db, "mfa_user", key):
        raise HTTPException(429, detail={"error": "locked"})
    codes = await totp.confirm_enrollment(db, keyring, await _user(db, sess), body.code)
    if codes is None:
        await throttle.record_failure(db, "mfa_user", key, settings)
        await db.commit()
        raise HTTPException(401, detail={"error": "invalid_code"})
    await throttle.reset(db, "mfa_user", key)
    out: dict[str, object] = {"recovery_codes": codes}
    out.update(await _complete(db, sess, response, settings, "totp"))
    return out
```
In `create_app`, add `app.state.keyring = Keyring(KekSet.from_settings(settings))` and include `auth.router` and `mfa.router`.

**Transaction note:** `get_db` wraps the request in `s.begin()`. The explicit `await db.commit()` before raising in `login` and `_second_factor` persists the failure counters; `begin()`'s context manager then finds no active transaction and exits cleanly. Verify this with the lockout test in Step 5.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/core/auth tests/apps/api -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(auth): login with lockout, TOTP enrollment with replay protection, recovery codes, password change

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 9: Passkeys (WebAuthn): enrollment, passwordless login, second factor, step-up

**Files:**
- Create: `backend/src/dewpoint/core/auth/passkeys.py`, `backend/src/dewpoint/apps/api/routes/passkeys.py`
- Modify: `backend/src/dewpoint/apps/api/main.py` (include the router)
- Test: `backend/tests/core/auth/test_passkeys.py`, `backend/tests/apps/api/test_passkey_routes.py`

**Interfaces:**
- Consumes: `WebauthnCredential`, `WebauthnChallenge`, `User` (Task 4); sessions (Task 7); `throttle` and `initial_state` (Task 8).
- Produces:
  - `passkeys.registration_options(s, user, settings) -> tuple[dict, UUID]` (the options as a JSON-ready dict, plus the challenge ID).
  - `passkeys.finish_registration(s, user, challenge_id, credential: dict, name: str, settings) -> WebauthnCredential`.
  - `passkeys.authentication_options(s, settings, user_id: UUID | None) -> tuple[dict, UUID]`.
  - `passkeys.finish_authentication(s, challenge_id, credential: dict, settings, expected_user_id: UUID | None = None) -> User`.
  - `PasskeyError` (a generic failure, mapped to 401 `{"error":"passkey_failed"}`).
  - Endpoints under `/api/v1/auth/passkeys`:
    - `POST /register/options` and `POST /register/verify` (session in `enroll_required` or `active`);
    - `POST /login/options` and `POST /login/verify` (no session; passwordless; creates an `active` session with methods `["passkey"]`);
    - `POST /mfa/options` and `POST /mfa/verify` (session `mfa_pending`);
    - `POST /stepup/options` and `POST /stepup/verify` (session `active`; appends `passkey`).
  - Every `*/verify` returns `{state, csrf_token}` and rotates the session token, including registration from an `active` session.
  - Challenge issuance:
    - `/login/options` (anonymous) is limited to `passkey_options_per_ip` per 15-minute window (`throttle.consume`, kind `challenge_ip`), returning 429 `{"error":"rate_limited"}`.
    - Every issuance purges up to 500 expired challenges and refuses to issue (`ChallengeCapacityError`, which becomes 429) once `webauthn_challenges_max` unexpired challenges exist.
    - Stale throttle rows are purged the same way (`throttle.purge_stale`).

- [ ] **Step 1: Write the failing unit tests**

The WebAuthn crypto itself belongs to the `webauthn` library and is exercised end-to-end with a Playwright virtual authenticator in Task 14. These tests cover *our* rules: challenges are single-use, expire and are bound to a user; user verification is required; the sign count is updated; a user mismatch fails.

`backend/tests/core/auth/test_passkeys.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import update

from dewpoint.core.auth import passkeys
from dewpoint.core.auth.users import create_user
from dewpoint.core.models.identity import WebauthnChallenge

CRED = {"id": "Y3JlZA", "rawId": "Y3JlZA", "type": "public-key", "response": {}}


@pytest.fixture
def fake_webauthn(monkeypatch):
    calls: dict[str, dict] = {}

    def reg(**kw):
        calls["reg"] = kw
        return SimpleNamespace(credential_id=b"cred", credential_public_key=b"pk", sign_count=0)

    def auth(**kw):
        calls["auth"] = kw
        return SimpleNamespace(new_sign_count=7)

    monkeypatch.setattr(passkeys, "verify_registration_response", reg)
    monkeypatch.setattr(passkeys, "verify_authentication_response", auth)
    return calls


async def test_register_then_authenticate(owner_sessionmaker, api_settings, fake_webauthn) -> None:
    async with owner_sessionmaker() as s, s.begin():
        u = await create_user(s, email="p@corp.test", password="violet-otter-canyon-42")
        opts, cid = await passkeys.registration_options(s, u, api_settings)
        assert opts["authenticatorSelection"]["userVerification"] == "required"
        cred = await passkeys.finish_registration(s, u, cid, CRED, "laptop", api_settings)
        assert cred.credential_id == b"cred"
        assert fake_webauthn["reg"]["require_user_verification"] is True
        with pytest.raises(passkeys.PasskeyError):  # challenge is single-use
            await passkeys.finish_registration(s, u, cid, CRED, "again", api_settings)

        _, aid = await passkeys.authentication_options(s, api_settings, None)
        user = await passkeys.finish_authentication(s, aid, CRED, api_settings)
        assert user.id == u.id and cred.sign_count == 7
        assert fake_webauthn["auth"]["require_user_verification"] is True


async def test_expired_and_user_mismatch(owner_sessionmaker, api_settings, fake_webauthn) -> None:
    async with owner_sessionmaker() as s, s.begin():
        u = await create_user(s, email="q@corp.test", password="violet-otter-canyon-42")
        _, cid = await passkeys.registration_options(s, u, api_settings)
        await passkeys.finish_registration(s, u, cid, CRED, "k", api_settings)
        _, aid = await passkeys.authentication_options(s, api_settings, None)
        await s.execute(update(WebauthnChallenge).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        with pytest.raises(passkeys.PasskeyError):
            await passkeys.finish_authentication(s, aid, CRED, api_settings)
        _, aid2 = await passkeys.authentication_options(s, api_settings, None)
        with pytest.raises(passkeys.PasskeyError):
            await passkeys.finish_authentication(s, aid2, CRED, api_settings, expected_user_id=uuid.uuid4())
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `uv run pytest tests/core/auth/test_passkeys.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `core/auth/passkeys.py`**

```python
# SPDX-License-Identifier: Apache-2.0
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from dewpoint.core.config import Settings
from dewpoint.core.models.identity import User, WebauthnChallenge, WebauthnCredential

CHALLENGE_TTL = timedelta(minutes=5)


PURGE_BATCH = 500


class PasskeyError(Exception):
    pass


class ChallengeCapacityError(Exception):
    """Too many outstanding challenges platform-wide; callers answer 429."""


def _rp_id(settings: Settings) -> str:
    return settings.rp_id or (urlparse(settings.public_origin).hostname or "")


async def purge_expired_challenges(s: AsyncSession, limit: int = PURGE_BATCH) -> int:
    """Delete up to `limit` expired challenges (bounded, so one request never does unbounded work)."""
    doomed = select(WebauthnChallenge.id).where(WebauthnChallenge.expires_at <= func.now()).limit(limit)
    result = await s.execute(delete(WebauthnChallenge).where(WebauthnChallenge.id.in_(doomed.scalar_subquery())))
    return int(getattr(result, "rowcount", 0) or 0)


async def _store(
    s: AsyncSession, challenge: bytes, user_id: uuid.UUID | None, purpose: str, settings: Settings
) -> uuid.UUID:
    await purge_expired_challenges(s)
    outstanding = (
        await s.execute(
            select(func.count()).select_from(WebauthnChallenge).where(WebauthnChallenge.expires_at > func.now())
        )
    ).scalar_one()
    if outstanding >= settings.webauthn_challenges_max:
        raise ChallengeCapacityError()
    row = WebauthnChallenge(
        challenge=challenge, user_id=user_id, purpose=purpose, expires_at=datetime.now(UTC) + CHALLENGE_TTL
    )
    s.add(row)
    await s.flush()
    return row.id


async def _consume(s: AsyncSession, challenge_id: uuid.UUID, purpose: str) -> WebauthnChallenge:
    row = (
        await s.execute(
            delete(WebauthnChallenge)
            .where(WebauthnChallenge.id == challenge_id, WebauthnChallenge.purpose == purpose)
            .returning(WebauthnChallenge)
        )
    ).scalar_one_or_none()
    if row is None or row.expires_at <= datetime.now(UTC):
        raise PasskeyError("challenge")
    return row


async def registration_options(s: AsyncSession, user: User, settings: Settings) -> tuple[dict[str, Any], uuid.UUID]:
    existing = (
        (await s.execute(select(WebauthnCredential.credential_id).where(WebauthnCredential.user_id == user.id)))
        .scalars()
        .all()
    )
    opts = generate_registration_options(
        rp_id=_rp_id(settings),
        rp_name="Dewpoint",
        user_id=user.id.bytes,
        user_name=user.email,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED
        ),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=c) for c in existing],
    )
    return json.loads(options_to_json(opts)), await _store(s, opts.challenge, user.id, "register", settings)


async def finish_registration(
    s: AsyncSession, user: User, challenge_id: uuid.UUID, credential: dict[str, Any], name: str, settings: Settings
) -> WebauthnCredential:
    ch = await _consume(s, challenge_id, "register")
    if ch.user_id != user.id:
        raise PasskeyError("user")
    try:
        v = verify_registration_response(
            credential=credential,
            expected_challenge=ch.challenge,
            expected_origin=settings.public_origin,
            expected_rp_id=_rp_id(settings),
            require_user_verification=True,
        )
    except Exception as exc:  # library raises several types; never leak details
        raise PasskeyError("verify") from exc
    cred = WebauthnCredential(
        user_id=user.id,
        credential_id=v.credential_id,
        public_key=v.credential_public_key,
        sign_count=v.sign_count,
        transports=[],
        name=name[:100],
    )
    s.add(cred)
    await s.flush()
    return cred


async def authentication_options(
    s: AsyncSession, settings: Settings, user_id: uuid.UUID | None
) -> tuple[dict[str, Any], uuid.UUID]:
    allow = []
    if user_id:
        ids = (
            (await s.execute(select(WebauthnCredential.credential_id).where(WebauthnCredential.user_id == user_id)))
            .scalars()
            .all()
        )
        allow = [PublicKeyCredentialDescriptor(id=c) for c in ids]
    opts = generate_authentication_options(
        rp_id=_rp_id(settings), allow_credentials=allow, user_verification=UserVerificationRequirement.REQUIRED
    )
    return json.loads(options_to_json(opts)), await _store(s, opts.challenge, user_id, "authenticate", settings)


async def finish_authentication(
    s: AsyncSession,
    challenge_id: uuid.UUID,
    credential: dict[str, Any],
    settings: Settings,
    expected_user_id: uuid.UUID | None = None,
) -> User:
    ch = await _consume(s, challenge_id, "authenticate")
    try:
        raw_id = base64url_to_bytes(str(credential["rawId"]))
    except Exception as exc:
        raise PasskeyError("format") from exc
    cred = (
        await s.execute(select(WebauthnCredential).where(WebauthnCredential.credential_id == raw_id).with_for_update())
    ).scalar_one_or_none()
    if (
        cred is None
        or (ch.user_id and ch.user_id != cred.user_id)
        or (expected_user_id and expected_user_id != cred.user_id)
    ):
        raise PasskeyError("credential")
    try:
        v = verify_authentication_response(
            credential=credential,
            expected_challenge=ch.challenge,
            expected_origin=settings.public_origin,
            expected_rp_id=_rp_id(settings),
            credential_public_key=cred.public_key,
            credential_current_sign_count=cred.sign_count,
            require_user_verification=True,
        )
    except Exception as exc:
        raise PasskeyError("verify") from exc
    cred.sign_count, cred.last_used_at = v.new_sign_count, datetime.now(UTC)
    user = await s.get(User, cred.user_id)
    if user is None or not user.is_active:
        raise PasskeyError("user")
    await s.flush()
    return user
```

- [ ] **Step 4: Write the failing route test**

`backend/tests/apps/api/test_passkey_routes.py`:
```python
# SPDX-License-Identifier: Apache-2.0
from types import SimpleNamespace

from dewpoint.core.auth import passkeys
from dewpoint.core.auth.users import create_user

CRED = {"id": "Y3JlZA", "rawId": "Y3JlZA", "type": "public-key", "response": {}}
PW = "violet-otter-canyon-42"


async def test_enroll_passkey_then_passwordless_login(client, owner_sessionmaker, monkeypatch) -> None:
    monkeypatch.setattr(passkeys, "verify_registration_response",
                        lambda **kw: SimpleNamespace(credential_id=b"cred", credential_public_key=b"pk", sign_count=0))
    monkeypatch.setattr(passkeys, "verify_authentication_response", lambda **kw: SimpleNamespace(new_sign_count=1))
    async with owner_sessionmaker() as s, s.begin():
        await create_user(s, email="e@corp.test", password=PW)
    r = await client.post("/api/v1/auth/login", json={"email": "e@corp.test", "password": PW})
    csrf = r.json()["csrf_token"]
    o = (await client.post("/api/v1/auth/passkeys/register/options", headers={"X-CSRF-Token": csrf})).json()
    r = await client.post("/api/v1/auth/passkeys/register/verify", headers={"X-CSRF-Token": csrf},
                          json={"challenge_id": o["challenge_id"], "credential": CRED, "name": "laptop"})
    assert r.status_code == 200 and r.json()["state"] == "active"
    await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": r.json()["csrf_token"]})

    o = (await client.post("/api/v1/auth/passkeys/login/options")).json()
    r = await client.post("/api/v1/auth/passkeys/login/verify", json={"challenge_id": o["challenge_id"], "credential": CRED})
    assert r.status_code == 200 and r.json()["state"] == "active"
    me = (await client.get("/api/v1/auth/session")).json()
    assert me["auth_methods"] == ["passkey"]


async def test_passkey_stepup_is_throttled(client, owner_sessionmaker, api_settings, monkeypatch) -> None:
    def _reject(**kw):
        raise ValueError("bad signature")

    monkeypatch.setattr(passkeys, "verify_registration_response",
                        lambda **kw: SimpleNamespace(credential_id=b"cred", credential_public_key=b"pk", sign_count=0))
    async with owner_sessionmaker() as s, s.begin():
        await create_user(s, email="f@corp.test", password=PW)
    csrf = (await client.post("/api/v1/auth/login", json={"email": "f@corp.test", "password": PW})).json()["csrf_token"]
    o = (await client.post("/api/v1/auth/passkeys/register/options", headers={"X-CSRF-Token": csrf})).json()
    csrf = (await client.post("/api/v1/auth/passkeys/register/verify", headers={"X-CSRF-Token": csrf},
                              json={"challenge_id": o["challenge_id"], "credential": CRED})).json()["csrf_token"]
    monkeypatch.setattr(passkeys, "verify_authentication_response", _reject)
    h = {"X-CSRF-Token": csrf}
    for _ in range(api_settings.login_max_failures):
        o = (await client.post("/api/v1/auth/passkeys/stepup/options", headers=h)).json()
        r = await client.post("/api/v1/auth/passkeys/stepup/verify", headers=h,
                              json={"challenge_id": o["challenge_id"], "credential": CRED})
        assert r.status_code == 401 and r.json() == {"error": "passkey_failed"}
    o = (await client.post("/api/v1/auth/passkeys/stepup/options", headers=h)).json()
    r = await client.post("/api/v1/auth/passkeys/stepup/verify", headers=h,
                          json={"challenge_id": o["challenge_id"], "credential": CRED})
    assert r.status_code == 429 and r.json() == {"error": "locked"}
```

- [ ] **Step 5: Implement `apps/api/routes/passkeys.py`**

```python
# SPDX-License-Identifier: Apache-2.0
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.auth import passkeys, throttle
from dewpoint.core.auth.sessions import create_session, elevate, rotate, set_session_cookie
from dewpoint.core.config import Settings
from dewpoint.core.http import current_session, ensure_fresh_reauth, get_db, get_settings_dep
from dewpoint.core.models.identity import AuthSession, User

router = APIRouter(prefix="/api/v1/auth/passkeys", tags=["auth"])


class VerifyIn(BaseModel):
    challenge_id: uuid.UUID
    credential: dict[str, Any]
    name: str = Field(default="Passkey", max_length=100)


def _state(sess: AuthSession, *allowed: str) -> None:
    if sess.state not in allowed:
        raise HTTPException(409, detail={"error": "wrong_state", "state": sess.state})


async def _session_user(db: AsyncSession, sess: AuthSession) -> User:
    user = await db.get(User, sess.user_id)
    if user is None:  # deleted while signed in
        raise HTTPException(401, detail={"error": "unauthenticated"})
    return user


def _busy() -> HTTPException:
    return HTTPException(429, detail={"error": "rate_limited"})


def _fail() -> HTTPException:
    return HTTPException(401, detail={"error": "passkey_failed"})


async def _elevated(db: AsyncSession, sess: AuthSession, response: Response, settings: Settings) -> dict[str, str]:
    token = await elevate(db, sess, method="passkey", state="active")
    set_session_cookie(response, token, settings)
    return {"state": "active", "csrf_token": sess.csrf_token}


@router.post("/register/options")
async def register_options(
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, Any]:
    _state(sess, "enroll_required", "active")
    ensure_fresh_reauth(sess, settings)  # a stolen active session must not be able to plant a lasting factor
    user = await _session_user(db, sess)
    try:
        opts, cid = await passkeys.registration_options(db, user, settings)
    except passkeys.ChallengeCapacityError:
        raise _busy() from None
    return {"options": opts, "challenge_id": str(cid)}


@router.post("/register/verify")
async def register_verify(
    body: VerifyIn,
    response: Response,
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    _state(sess, "enroll_required", "active")
    ensure_fresh_reauth(sess, settings)  # re-checked here: the challenge can outlive the reauth window
    user = await _session_user(db, sess)
    try:
        await passkeys.finish_registration(db, user, body.challenge_id, body.credential, body.name, settings)
    except passkeys.PasskeyError:
        raise _fail() from None
    if sess.state == "enroll_required":
        return await _elevated(db, sess, response, settings)
    token = await rotate(db, sess)  # a factor was added: new session and CSRF tokens
    set_session_cookie(response, token, settings)
    return {"state": sess.state, "csrf_token": sess.csrf_token}


@router.post("/login/options")
async def login_options(
    request: Request, db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings_dep)
) -> dict[str, Any]:
    """Anonymous: every call stores a challenge, so issuance is limited per IP and capped platform-wide."""
    ip = request.client.host if request.client else "unknown"
    await throttle.purge_stale(db)
    if not await throttle.consume(db, "challenge_ip", ip, settings.passkey_options_per_ip):
        raise HTTPException(429, detail={"error": "rate_limited"})
    try:
        opts, cid = await passkeys.authentication_options(db, settings, None)
    except passkeys.ChallengeCapacityError:
        raise _busy() from None
    return {"options": opts, "challenge_id": str(cid)}


@router.post("/login/verify")
async def login_verify(
    body: VerifyIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    ip = request.client.host if request.client else "unknown"
    if await throttle.is_locked(db, "login_ip", ip):
        raise HTTPException(429, detail={"error": "locked"})
    try:
        user = await passkeys.finish_authentication(db, body.challenge_id, body.credential, settings)
    except passkeys.PasskeyError:
        await throttle.record_failure(db, "login_ip", ip, settings)
        await db.commit()
        raise _fail() from None
    sess, token = await create_session(
        db,
        user_id=user.id,
        state="active",
        methods=["passkey"],
        settings=settings,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
        reauth=True,  # a user-verified passkey is a second factor
    )
    set_session_cookie(response, token, settings)
    return {"state": "active", "csrf_token": sess.csrf_token}


async def _factor_options(sess: AuthSession, db: AsyncSession, settings: Settings) -> dict[str, Any]:
    try:
        opts, cid = await passkeys.authentication_options(db, settings, sess.user_id)
    except passkeys.ChallengeCapacityError:
        raise _busy() from None
    return {"options": opts, "challenge_id": str(cid)}


async def _factor_verify(
    body: VerifyIn, response: Response, sess: AuthSession, db: AsyncSession, settings: Settings
) -> dict[str, str]:
    key = str(sess.user_id)  # same "mfa_user" budget as TOTP and recovery codes
    if await throttle.is_locked(db, "mfa_user", key):
        raise HTTPException(429, detail={"error": "locked"})
    try:
        await passkeys.finish_authentication(
            db, body.challenge_id, body.credential, settings, expected_user_id=sess.user_id
        )
    except passkeys.PasskeyError:
        await throttle.record_failure(db, "mfa_user", key, settings)
        await db.commit()
        raise _fail() from None
    await throttle.reset(db, "mfa_user", key)
    return await _elevated(db, sess, response, settings)


@router.post("/mfa/options")
async def mfa_options(
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, Any]:
    _state(sess, "mfa_pending")
    return await _factor_options(sess, db, settings)


@router.post("/mfa/verify")
async def mfa_verify(
    body: VerifyIn,
    response: Response,
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    _state(sess, "mfa_pending")
    return await _factor_verify(body, response, sess, db, settings)


@router.post("/stepup/options")
async def stepup_options(
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, Any]:
    _state(sess, "active")
    return await _factor_options(sess, db, settings)


@router.post("/stepup/verify")
async def stepup_verify(
    body: VerifyIn,
    response: Response,
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    _state(sess, "active")
    return await _factor_verify(body, response, sess, db, settings)
```
Include the router in `create_app`.

- [ ] **Step 5b: Real-signature tests (no mocks)**

Add `tests/support/soft_authenticator.py`, a software ES256 authenticator with "none" attestation built on `cryptography` and `cbor2` (a webauthn dependency). Add `tests/core/auth/test_passkeys_real_crypto.py`, which covers:
- registration and authentication with real signatures, including sign-count progression;
- a wrong origin, a tampered signature and a replayed assertion, each rejected;
- a missing user-verification flag, rejected at registration.

The test directories get `__init__.py` files so that `tests.support` is importable.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/core/auth/test_passkeys.py tests/core/auth/test_passkeys_real_crypto.py tests/apps/api/test_passkey_routes.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat(auth): passkeys for enrollment, passwordless login, second factor and step-up

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Permissions, tenant context, tenants, members, platform user creation

**Files:**
- Create: `backend/src/dewpoint/core/authz/__init__.py`, `backend/src/dewpoint/core/authz/permissions.py`
- Create: `backend/src/dewpoint/core/tenancy/__init__.py`, `backend/src/dewpoint/core/tenancy/service.py`
- Modify: `backend/src/dewpoint/core/http.py` (add `TenantContext`, `require()`, `require_platform_admin`)
- Create: `backend/src/dewpoint/apps/api/routes/tenants.py`, `backend/src/dewpoint/apps/api/routes/members.py`, `backend/src/dewpoint/apps/api/routes/admin_users.py`
- Test: `backend/tests/core/authz/test_permissions.py`, `backend/tests/core/tenancy/test_owner_race.py`, `backend/tests/apps/api/test_tenant_matrix.py`

**Interfaces:**
- Consumes: `Tenant`, `Membership`, `ROLES`, `Role` (Task 4); `current_user`, `active_session`, `get_db` (Task 7); `create_user` (Task 6); `tenant_scope` (Task 3).
- Produces:
  - `class P(StrEnum)` with the values `tenant.view`, `tenant.manage`, `member.view`, `member.manage`, `connection.view`, `connection.use`, `connection.manage`, `audit.view`, `workflow.view`, `workflow.edit`, `workflow.publish`, `run.start`, `run.view`, `approval.decide`, `agent.grant`.
  - `ROLE_PERMISSIONS: dict[str, frozenset[P]]`.
  - `@dataclass TenantContext(tenant_id: UUID, user: User, role: str, session: AuthSession)`.
  - `require(p: P) -> Callable` (a dependency that returns `TenantContext`). Rules:
    - non-member → **404** `{"error":"not_found"}`, so tenant IDs can't be probed;
    - member without the permission → 403 `{"error":"forbidden"}`;
    - tenant with `require_passkey` and a session without `passkey` in its methods → 403 `{"error":"step_up_required"}`;
    - on success, calls `tenant_scope(db, tenant_id)`, which also clears the user-discovery scope used for the membership lookup.
  - `require_platform_admin` dependency.
  - The service functions `create_tenant(s, *, name, slug, owner_id) -> Tenant`, `list_user_tenants(s, user_id) -> list[tuple[Tenant, str]]`, `add_member(s, tenant_id, email, role, actor_role) -> Membership`, `change_role(s, tenant_id, user_id, role, actor_role) -> Membership`, `remove_member(s, tenant_id, user_id, actor_role) -> None`, and `LastOwnerError`, `OwnerGrantError`, `UnknownUserError`.
  - Platform admins get **no implicit tenant access**. They must be members like anyone else. (Cross-tenant operator tooling is post-v1, spec §4.1.)

- [ ] **Step 1: Write the failing tests**

`backend/tests/core/authz/test_permissions.py`:
```python
# SPDX-License-Identifier: Apache-2.0
from itertools import pairwise

from dewpoint.core.authz.permissions import ROLE_PERMISSIONS, P


def test_role_hierarchy_is_monotonic() -> None:
    order = ["viewer", "operator", "editor", "admin", "owner"]
    for lower, higher in pairwise(order):
        assert ROLE_PERMISSIONS[lower] <= ROLE_PERMISSIONS[higher], (lower, higher)


def test_key_grants() -> None:
    assert P.CONNECTION_USE in ROLE_PERMISSIONS["editor"]
    assert P.CONNECTION_MANAGE not in ROLE_PERMISSIONS["editor"]
    assert P.MEMBER_MANAGE in ROLE_PERMISSIONS["admin"]
    assert P.AGENT_GRANT in ROLE_PERMISSIONS["admin"]
    assert P.RUN_START in ROLE_PERMISSIONS["operator"] and P.WORKFLOW_EDIT not in ROLE_PERMISSIONS["operator"]
    assert ROLE_PERMISSIONS["viewer"] == {P.TENANT_VIEW, P.WORKFLOW_VIEW, P.RUN_VIEW, P.CONNECTION_VIEW, P.MEMBER_VIEW}
```

`backend/tests/apps/api/test_tenant_matrix.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import uuid

import pytest
from sqlalchemy import text

from tests.apps.api.helpers import session_client as _as

PW = "violet-otter-canyon-42"


CASES = [
    # (method, path, body, {role: expected_status})
    ("GET", "/api/v1/t/{t}", None, {"viewer": 200, "owner": 200, None: 404}),
    ("PATCH", "/api/v1/t/{t}", {"name": "New"}, {"viewer": 403, "editor": 403, "admin": 200, None: 404}),
    ("GET", "/api/v1/t/{t}/members", None, {"viewer": 200, None: 404}),
    (
        "POST",
        "/api/v1/t/{t}/members",
        {"email": "nobody@corp.test", "role": "viewer"},
        {"operator": 403, "admin": 404, None: 404},
    ),  # admin allowed; unknown user -> 404 user_not_found
]


@pytest.mark.parametrize("method,path,body,expect", CASES)
async def test_permission_matrix(app, owner_sessionmaker, api_settings, method, path, body, expect) -> None:
    for role, status in expect.items():
        c, tid = await _as(app, owner_sessionmaker, api_settings, role)
        async with c:
            r = await c.request(method, path.format(t=tid), json=body)
        assert r.status_code == status, (role, r.text)


async def test_enroll_required_session_blocked(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await _as(app, owner_sessionmaker, api_settings, "owner")
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update sessions set state='enroll_required'"))
    async with c:
        assert (await c.get("/api/v1/tenants")).status_code == 403
        assert (await c.get(f"/api/v1/t/{tid}")).status_code == 403


async def test_require_passkey_step_up(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await _as(app, owner_sessionmaker, api_settings, "owner", require_passkey=True)
    async with c:
        r = await c.get(f"/api/v1/t/{tid}")
    assert r.status_code == 403 and r.json() == {"error": "step_up_required"}
    c, tid = await _as(app, owner_sessionmaker, api_settings, "owner", methods=("passkey",), require_passkey=True)
    async with c:
        assert (await c.get(f"/api/v1/t/{tid}")).status_code == 200


async def test_platform_admin_creates_tenant_and_last_owner_protected(app, owner_sessionmaker, api_settings) -> None:
    c, _ = await _as(app, owner_sessionmaker, api_settings, None, platform_admin=True)
    async with c:
        r = await c.post("/api/v1/tenants", json={"name": "Acme Retail", "slug": "acme-retail"})
        assert r.status_code == 201
        tid = r.json()["id"]
        mine = (await c.get("/api/v1/tenants")).json()
        assert [(t["slug"], t["role"]) for t in mine] == [("acme-retail", "owner")]
        me = (await c.get("/api/v1/auth/session")).json()["user"]["id"]
        r = await c.patch(f"/api/v1/t/{tid}/members/{me}", json={"role": "admin"})
        assert r.status_code == 409 and r.json() == {"error": "last_owner"}


async def test_unfiltered_query_after_require_sees_only_current_tenant(app, owner_sessionmaker, api_settings) -> None:
    from fastapi import APIRouter, Depends
    from sqlalchemy import select

    from dewpoint.core.authz.permissions import P
    from dewpoint.core.http import get_db, require
    from dewpoint.core.models.tenancy import Membership, Tenant

    router = APIRouter()

    @router.get("/api/v1/t/{tenant_id}/_probe")
    async def probe(_=Depends(require(P.TENANT_VIEW)), db=Depends(get_db)) -> dict[str, int]:
        return {
            "memberships": len((await db.execute(select(Membership))).scalars().all()),  # deliberately unfiltered
            "tenants": len((await db.execute(select(Tenant))).scalars().all()),
        }

    app.include_router(router)
    c, tid = await _as(app, owner_sessionmaker, api_settings, "owner")
    other = uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():  # same user also owns a second tenant
        await s.execute(
            text("insert into tenants(id,name,slug) values (:o,'O',:slug)"), {"o": other, "slug": other.hex[:12]}
        )
        await s.execute(
            text(
                "insert into memberships(tenant_id,user_id,role) select :o, user_id, 'owner' "
                "from memberships where tenant_id=:t"
            ),
            {"o": other, "t": tid},
        )
    async with c:
        assert (await c.get(f"/api/v1/t/{tid}/_probe")).json() == {"memberships": 1, "tenants": 1}


async def test_non_admin_cannot_create_tenant(app, owner_sessionmaker, api_settings) -> None:
    c, _ = await _as(app, owner_sessionmaker, api_settings, "owner")
    async with c:
        assert (await c.post("/api/v1/tenants", json={"name": "X", "slug": "x-tenant"})).status_code == 403


async def test_platform_admin_creates_users(app, owner_sessionmaker, api_settings) -> None:
    admin, _ = await _as(app, owner_sessionmaker, api_settings, None, platform_admin=True)
    async with admin:
        r = await admin.post("/api/v1/admin/users", json={"email": "new@site.local", "password": PW})
        assert r.status_code == 201 and r.json()["email"] == "new@site.local"
        r = await admin.post("/api/v1/admin/users", json={"email": "NEW@site.local", "password": PW})
        assert r.status_code == 409 and r.json() == {"error": "email_taken"}
        r = await admin.post("/api/v1/admin/users", json={"email": "weak@site.local", "password": "short"})
        assert r.status_code == 422 and r.json()["error"] == "password_policy"
        assert "short" not in r.text
    owner, _ = await _as(app, owner_sessionmaker, api_settings, "owner")
    async with owner:
        r = await owner.post("/api/v1/admin/users", json={"email": "x@site.local", "password": PW})
        assert r.status_code == 403
```

`backend/tests/core/tenancy/test_owner_race.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import asyncio
import uuid

from sqlalchemy import select, text

from dewpoint.core.auth.users import create_user
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.tenancy import Membership
from dewpoint.core.tenancy import service


async def test_concurrent_owner_removals_leave_one_owner(owner_sessionmaker, api_sessionmaker) -> None:
    tid = uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        a = await create_user(s, email="o1@corp.test", password="violet-otter-canyon-42")
        b = await create_user(s, email="o2@corp.test", password="violet-otter-canyon-42")
        await s.execute(text("insert into tenants(id,name,slug) values (:t,'T','race')"), {"t": tid})
        await s.execute(text("insert into memberships(tenant_id,user_id,role) values (:t,:a,'owner'),(:t,:b,'owner')"),
                        {"t": tid, "a": a.id, "b": b.id})

    async def remove(uid: uuid.UUID) -> str:
        try:
            async with api_sessionmaker() as s, s.begin():
                await tenant_scope(s, tid)
                await service.remove_member(s, tid, uid, actor_role="owner")
                await asyncio.sleep(0.2)  # hold the transaction open to force overlap
            return "removed"
        except service.LastOwnerError:
            return "last_owner"

    results = sorted(await asyncio.gather(remove(a.id), remove(b.id)))
    assert results == ["last_owner", "removed"]
    async with owner_sessionmaker() as s:
        owners = (await s.execute(select(Membership).where(Membership.role == "owner"))).scalars().all()
    assert len(owners) == 1
```
(Add `tests/core/tenancy/__init__.py`.) Without `_lock_tenant()`, both transactions count two owners and both succeed, so this test is the regression guard.

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `uv run pytest tests/core/authz tests/core/tenancy tests/apps/api/test_tenant_matrix.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement the permissions**

`core/authz/permissions.py`:
```python
# SPDX-License-Identifier: Apache-2.0
from enum import StrEnum


class P(StrEnum):
    TENANT_VIEW = "tenant.view"
    TENANT_MANAGE = "tenant.manage"
    MEMBER_VIEW = "member.view"
    MEMBER_MANAGE = "member.manage"
    CONNECTION_VIEW = "connection.view"
    CONNECTION_USE = "connection.use"
    CONNECTION_MANAGE = "connection.manage"
    AUDIT_VIEW = "audit.view"
    WORKFLOW_VIEW = "workflow.view"
    WORKFLOW_EDIT = "workflow.edit"
    WORKFLOW_PUBLISH = "workflow.publish"
    RUN_START = "run.start"
    RUN_VIEW = "run.view"
    APPROVAL_DECIDE = "approval.decide"
    AGENT_GRANT = "agent.grant"


_VIEWER = frozenset({P.TENANT_VIEW, P.WORKFLOW_VIEW, P.RUN_VIEW, P.CONNECTION_VIEW, P.MEMBER_VIEW})
_OPERATOR = _VIEWER | {P.RUN_START, P.APPROVAL_DECIDE}
_EDITOR = _OPERATOR | {P.WORKFLOW_EDIT, P.WORKFLOW_PUBLISH, P.CONNECTION_USE}
_ADMIN = _EDITOR | {P.TENANT_MANAGE, P.MEMBER_MANAGE, P.CONNECTION_MANAGE, P.AUDIT_VIEW, P.AGENT_GRANT}

ROLE_PERMISSIONS: dict[str, frozenset[P]] = {
    "viewer": _VIEWER, "operator": _OPERATOR, "editor": _EDITOR, "admin": _ADMIN, "owner": _ADMIN,
}
```
The difference between owner and admin is enforced in the tenancy service: only an owner may grant or revoke `owner`, and the last owner is protected.

- [ ] **Step 4: Implement the tenancy service**

`core/tenancy/service.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.auth.users import Email, get_user_by_email
from dewpoint.core.db import tenant_scope, user_scope
from dewpoint.core.models.tenancy import Membership, Tenant


class LastOwnerError(Exception): ...
class OwnerGrantError(Exception): ...
class UnknownUserError(Exception): ...


async def create_tenant(s: AsyncSession, *, name: str, slug: str, owner_id: uuid.UUID) -> Tenant:
    tid = uuid.uuid4()
    await tenant_scope(s, tid)
    tenant = Tenant(id=tid, name=name, slug=slug)
    s.add(tenant)
    await s.flush()
    s.add(Membership(tenant_id=tid, user_id=owner_id, role="owner"))
    await s.flush()
    return tenant


async def list_user_tenants(s: AsyncSession, user_id: uuid.UUID) -> list[tuple[Tenant, str]]:
    await user_scope(s, user_id)
    rows = await s.execute(select(Tenant, Membership.role).join(Membership, Membership.tenant_id == Tenant.id)
                           .where(Membership.user_id == user_id).order_by(Tenant.name))
    return [(t, r) for t, r in rows.all()]


async def _owners(s: AsyncSession, tenant_id: uuid.UUID) -> int:
    return int((await s.execute(select(func.count()).select_from(Membership)
                                .where(Membership.tenant_id == tenant_id, Membership.role == "owner"))).scalar_one())


async def add_member(s: AsyncSession, tenant_id: uuid.UUID, email: str, role: str, actor_role: str) -> Membership:
    if role == "owner" and actor_role != "owner":
        raise OwnerGrantError()
    await _lock_tenant(s, tenant_id)
    user = await get_user_by_email(s, email)
    if user is None:
        raise UnknownUserError()
    m = Membership(tenant_id=tenant_id, user_id=user.id, role=role)
    s.add(m)
    await s.flush()
    return m


async def _lock_tenant(s: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Serialize every membership change of a tenant, so owner counts can't race."""
    await s.execute(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update())


async def _membership(s: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID) -> Membership:
    await _lock_tenant(s, tenant_id)
    m = (await s.execute(select(Membership).where(Membership.tenant_id == tenant_id, Membership.user_id == user_id)
                         .with_for_update())).scalar_one_or_none()
    if m is None:
        raise UnknownUserError()
    return m


async def change_role(s: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, role: str, actor_role: str) -> Membership:
    m = await _membership(s, tenant_id, user_id)
    if "owner" in (role, m.role) and actor_role != "owner":
        raise OwnerGrantError()
    if m.role == "owner" and role != "owner" and await _owners(s, tenant_id) <= 1:
        raise LastOwnerError()
    m.role = role
    await s.flush()
    return m


async def remove_member(s: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, actor_role: str) -> None:
    m = await _membership(s, tenant_id, user_id)
    if m.role == "owner":
        if actor_role != "owner":
            raise OwnerGrantError()
        if await _owners(s, tenant_id) <= 1:
            raise LastOwnerError()
    await s.delete(m)
    await s.flush()
```

- [ ] **Step 5: Add `require()` to `core/http.py`**

```python
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select

from dewpoint.core.authz.permissions import P, ROLE_PERMISSIONS
from dewpoint.core.db import tenant_scope, user_scope
from dewpoint.core.models.tenancy import Membership, Tenant


@dataclass(frozen=True)
class TenantContext:
    tenant_id: uuid.UUID
    user: User
    role: str
    session: AuthSession


def require(permission: P) -> Callable[..., Awaitable[TenantContext]]:
    async def _dep(tenant_id: uuid.UUID, user: User = Depends(current_user),
                   sess: AuthSession = Depends(active_session), db: AsyncSession = Depends(get_db)) -> TenantContext:
        await user_scope(db, user.id)  # authoritative lookup of the caller's own membership
        row = (await db.execute(select(Membership.role, Tenant.require_passkey)
                                .join(Tenant, Tenant.id == Membership.tenant_id)
                                .where(Membership.tenant_id == tenant_id, Membership.user_id == user.id))).first()
        if row is None:
            raise HTTPException(404, detail={"error": "not_found"})
        role, require_passkey = row
        if require_passkey and "passkey" not in sess.auth_methods:
            raise HTTPException(403, detail={"error": "step_up_required"})
        if permission not in ROLE_PERMISSIONS[role]:
            raise HTTPException(403, detail={"error": "forbidden"})
        await tenant_scope(db, tenant_id)  # clears user scope: no widening to the caller's other tenants
        return TenantContext(tenant_id=tenant_id, user=user, role=role, session=sess)

    return _dep


async def require_platform_admin(user: User = Depends(current_user)) -> User:
    if not user.is_platform_admin:
        raise HTTPException(403, detail={"error": "forbidden"})
    return user
```
`tenant_id` is resolved from the path parameter `{tenant_id}` by FastAPI, which is why every tenant route must be declared as `/api/v1/t/{tenant_id}/…`.

- [ ] **Step 6: Implement the routes**

`apps/api/routes/tenants.py`:
```python
# SPDX-License-Identifier: Apache-2.0
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit.service import record
from dewpoint.core.authz.permissions import P
from dewpoint.core.http import TenantContext, current_user, get_db, require, require_platform_admin
from dewpoint.core.models.identity import User
from dewpoint.core.models.tenancy import Tenant
from dewpoint.core.tenancy import service

router = APIRouter(prefix="/api/v1", tags=["tenants"])
SLUG = r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$"


class TenantIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=SLUG)


class TenantPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    require_passkey: bool | None = None


async def _tenant(db: AsyncSession, ctx: TenantContext) -> Tenant:
    t = await db.get(Tenant, ctx.tenant_id)
    if t is None:  # deleted after the membership check in this request
        raise HTTPException(404, detail={"error": "not_found"})
    return t


def _out(t: Tenant, role: str | None = None) -> dict[str, object]:
    d: dict[str, object] = {"id": str(t.id), "name": t.name, "slug": t.slug, "require_passkey": t.require_passkey}
    if role:
        d["role"] = role
    return d


@router.get("/tenants")
async def my_tenants(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> list[dict[str, object]]:
    return [_out(t, r) for t, r in await service.list_user_tenants(db, user.id)]


@router.post("/tenants", status_code=201)
async def create(
    body: TenantIn, admin: User = Depends(require_platform_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    try:
        t = await service.create_tenant(db, name=body.name, slug=body.slug, owner_id=admin.id)
    except IntegrityError:
        raise HTTPException(409, detail={"error": "slug_taken"}) from None
    await record(
        db,
        tenant_id=t.id,
        actor_id=admin.id,
        action="tenant.create",
        target_type="tenant",
        target_id=str(t.id),
        details={"slug": t.slug},
    )
    return _out(t, "owner")


@router.get("/t/{tenant_id}")
async def get_tenant(
    ctx: TenantContext = Depends(require(P.TENANT_VIEW)), db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    t = await _tenant(db, ctx)
    return _out(t, ctx.role)


@router.patch("/t/{tenant_id}")
async def patch_tenant(
    body: TenantPatch, ctx: TenantContext = Depends(require(P.TENANT_MANAGE)), db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    t = await _tenant(db, ctx)
    if body.name is not None:
        t.name = body.name
    if body.require_passkey is not None:
        t.require_passkey = body.require_passkey
    await db.flush()
    await record(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="tenant.update",
        target_type="tenant",
        target_id=str(t.id),
        details=body.model_dump(exclude_none=True),
    )
    return _out(t, ctx.role)
```

`apps/api/routes/members.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit.service import record
from dewpoint.core.auth.users import Email
from dewpoint.core.authz.permissions import P
from dewpoint.core.http import TenantContext, get_db, require
from dewpoint.core.models.identity import User
from dewpoint.core.models.tenancy import Membership
from dewpoint.core.tenancy import service

router = APIRouter(prefix="/api/v1/t/{tenant_id}/members", tags=["members"])
RoleIn = Literal["owner", "admin", "editor", "operator", "viewer"]


class AddIn(BaseModel):
    email: Email
    role: RoleIn


class RoleChange(BaseModel):
    role: RoleIn


async def _audit(db: AsyncSession, ctx: TenantContext, action: str, user_id: uuid.UUID, role: str | None) -> None:
    await record(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action=action,
        target_type="user",
        target_id=str(user_id),
        details={"role": role} if role else None,
    )


def _map(exc: Exception) -> HTTPException:
    if isinstance(exc, service.LastOwnerError):
        return HTTPException(409, detail={"error": "last_owner"})
    if isinstance(exc, service.OwnerGrantError):
        return HTTPException(403, detail={"error": "owner_only"})
    return HTTPException(404, detail={"error": "user_not_found"})


@router.get("")
async def list_members(
    ctx: TenantContext = Depends(require(P.MEMBER_VIEW)), db: AsyncSession = Depends(get_db)
) -> list[dict[str, str]]:
    rows = await db.execute(
        select(Membership, User.email)
        .join(User, User.id == Membership.user_id)
        .where(Membership.tenant_id == ctx.tenant_id)
        .order_by(User.email)
    )
    return [{"user_id": str(m.user_id), "email": e, "role": m.role} for m, e in rows.all()]


@router.post("", status_code=201)
async def add(
    body: AddIn, ctx: TenantContext = Depends(require(P.MEMBER_MANAGE)), db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    try:
        m = await service.add_member(db, ctx.tenant_id, body.email, body.role, ctx.role)
        await db.flush()
    except (service.OwnerGrantError, service.UnknownUserError) as e:
        raise _map(e) from None
    except IntegrityError:
        raise HTTPException(409, detail={"error": "already_member"}) from None
    await _audit(db, ctx, "member.add", m.user_id, m.role)
    return {"user_id": str(m.user_id), "role": m.role}


@router.patch("/{user_id}")
async def change(
    user_id: uuid.UUID,
    body: RoleChange,
    ctx: TenantContext = Depends(require(P.MEMBER_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    try:
        m = await service.change_role(db, ctx.tenant_id, user_id, body.role, ctx.role)
        await _audit(db, ctx, "member.role_change", user_id, m.role)
    except (service.LastOwnerError, service.OwnerGrantError, service.UnknownUserError) as e:
        raise _map(e) from None
    return {"user_id": str(m.user_id), "role": m.role}


@router.delete("/{user_id}", status_code=204)
async def remove(
    user_id: uuid.UUID, ctx: TenantContext = Depends(require(P.MEMBER_MANAGE)), db: AsyncSession = Depends(get_db)
) -> Response:
    try:
        await service.remove_member(db, ctx.tenant_id, user_id, ctx.role)
        await _audit(db, ctx, "member.remove", user_id, None)
    except (service.LastOwnerError, service.OwnerGrantError, service.UnknownUserError) as e:
        raise _map(e) from None
    return Response(status_code=204)
```

`apps/api/routes/admin_users.py` (a platform admin creates local accounts; each new user enrolls MFA at first sign-in; covered by `test_platform_admin_creates_users`):
```python
# SPDX-License-Identifier: Apache-2.0
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.auth.users import Email, EmailTakenError, PasswordPolicyError, create_user
from dewpoint.core.http import get_db, require_platform_admin
from dewpoint.core.models.identity import User

router = APIRouter(prefix="/api/v1/admin/users", tags=["admin"])


class UserIn(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=1024)


@router.post("", status_code=201)
async def create(
    body: UserIn, admin: User = Depends(require_platform_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    """Create a local account. The new user must enroll MFA at first sign-in."""
    try:
        user = await create_user(db, email=body.email, password=body.password)
    except PasswordPolicyError as e:
        raise HTTPException(422, detail={"error": "password_policy", "violations": e.violations}) from None
    except EmailTakenError:
        raise HTTPException(409, detail={"error": "email_taken"}) from None
    return {"id": str(user.id), "email": user.email}
```

Include all three routers in `create_app`.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/core/authz tests/apps/api -v`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat(authz): permissions, tenant context with step-up, tenants, members, platform user creation

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 11: Tamper-evident audit log with external anchoring

**Files:**
- Create: `backend/src/dewpoint/core/models/audit.py`, `backend/migrations/versions/0005_audit.py`
- Create: `backend/src/dewpoint/core/audit/__init__.py`, `service.py`, `anchor.py`
- Create: `backend/src/dewpoint/apps/api/routes/audit.py`
- Modify: `backend/src/dewpoint/apps/cli/main.py` (add the `audit anchor` and `audit verify` commands)
- Modify: `apps/api/routes/auth.py`, `mfa.py`, `passkeys.py`, `tenants.py`, `members.py`, `admin_users.py` (add `record()` calls, listed in Step 6)
- Test: `backend/tests/core/audit/test_chain.py`, `backend/tests/core/audit/test_anchor.py`, `backend/tests/apps/api/test_audit_routes.py`

**Interfaces:**
- Consumes: `tenant_scope`, the `app_tenant_id()` SQL function (Task 4); `TenantContext`/`require` (Task 10); `Settings.audit_signing_key_b64`, `Settings.audit_anchor_path` (Task 2).
- Produces:
  - The SQL function `audit_append(p_tenant uuid, p_actor uuid, p_action text, p_target_type text, p_target_id text, p_details jsonb) RETURNS bigint`.
  - `async record(s, *, tenant_id: UUID | None, actor_id: UUID | None, action: str, target_type: str = "", target_id: str = "", details: dict | None = None) -> int`. It raises `ValueError` if `details` contains a key matching `password|secret|token|code|credential` (case-insensitive).
  - `async verify_chain(s, scope: str) -> ChainReport(ok: bool, checked: int, first_bad_seq: int | None, head_seq: int | None, head_hash: bytes | None)`.
  - `class FileAnchorSink(path: Path, private_key: Ed25519PrivateKey)` with `.write(scope, seq, hash) -> str` and `.entries() -> list[dict]`.
  - `async anchor_all(s, sink) -> int`.
  - `async verify_anchors(s, sink_entries: list[dict], public_key: Ed25519PublicKey, *, max_lag: timedelta = timedelta(hours=1), now: datetime | None = None) -> list[str]` (the problems found; empty means OK). It **fails closed**:
    - no anchors at all is a problem;
    - every scope's rows older than `max_lag` must be covered by a signed anchor at or after their `seq`;
    - every scope in the database is chain-verified, not only the anchored ones.
  - Group role `dewpoint_auditor` and test fixture `auditor_sessionmaker`.
  - Endpoint `GET /api/v1/t/{tenant_id}/audit?before_seq=&limit=` (requires `audit.view`).
  - Action names used in this plan: `auth.login`, `auth.login_failed`, `auth.mfa`, `auth.password_changed`, `auth.passkey_registered`, `tenant.create`, `tenant.update`, `member.add`, `member.role_change`, `member.remove`, `user.create`, `connection.create`, `connection.update`, `connection.delete`, `connection.verify`.

**Dedicated auditor role:** anchoring and verification must read *every* scope, platform and all tenants, which no service role can do under RLS. Migration 0005 therefore creates a narrow group role `dewpoint_auditor`. Its only rights are:
- `SELECT` on `audit_log` through its own policy `audit_auditor_read … TO dewpoint_auditor USING (true)`;
- `SELECT, INSERT` on `audit_anchors`.

It has no access to any other table. The anchor and verify commands run as this role, and the tests below use it, not the superuser. Operators run `audit anchor` and `audit verify` with a `dewpoint_auditor` login.

**Documented RLS exception:** `audit_log` uses `ENABLE ROW LEVEL SECURITY` **without** `FORCE`. `audit_append()` is `SECURITY DEFINER`, owned by the table owner, and must read the previous hash across RLS. Service roles only get `SELECT` (RLS-filtered) and `EXECUTE` on the function: no `INSERT`, `UPDATE` or `DELETE`. Triggers also reject `UPDATE`, `DELETE` and `TRUNCATE` for everyone except in replication mode, which only superusers can set.

- [ ] **Step 1: Write the failing chain tests**

`backend/tests/core/audit/test_chain.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dewpoint.core.audit.service import record, verify_chain
from dewpoint.core.db import tenant_scope


async def test_append_and_verify(api_sessionmaker, owner_sessionmaker) -> None:
    t = uuid.uuid4()
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        for i in range(3):
            await record(s, tenant_id=t, actor_id=None, action="member.add", target_id=str(i), details={"role": "viewer"})
        await record(s, tenant_id=None, actor_id=None, action="auth.login")
    async with owner_sessionmaker() as s:
        rep = await verify_chain(s, str(t))
        assert rep.ok and rep.checked == 3 and rep.head_seq is not None
        assert (await verify_chain(s, "platform")).checked == 1


async def test_service_role_cannot_mutate_or_forge(api_sessionmaker) -> None:
    t = uuid.uuid4()
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        await record(s, tenant_id=t, actor_id=None, action="tenant.update")
    for stmt in ("update audit_log set action='x'", "delete from audit_log",
                 "insert into audit_log(scope,action,prev_hash,hash) values ('x','y','\\x00','\\x00')"):
        with pytest.raises(DBAPIError):
            async with api_sessionmaker() as s, s.begin():
                await tenant_scope(s, t)
                await s.execute(text(stmt))


async def test_cannot_append_for_other_tenant(api_sessionmaker) -> None:
    with pytest.raises(DBAPIError, match="audit tenant mismatch"):
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, uuid.uuid4())
            await record(s, tenant_id=uuid.uuid4(), actor_id=None, action="member.add")


async def test_tamper_detected(api_sessionmaker, owner_sessionmaker) -> None:
    t = uuid.uuid4()
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        for i in range(3):
            await record(s, tenant_id=t, actor_id=None, action="member.add", target_id=str(i))
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("SET LOCAL session_replication_role = replica"))  # superuser bypasses triggers
        await s.execute(text("update audit_log set target_id='evil' where target_id='1'"))
    async with owner_sessionmaker() as s:
        rep = await verify_chain(s, str(t))
    assert not rep.ok and rep.first_bad_seq is not None


def test_secret_keys_rejected() -> None:
    import asyncio
    with pytest.raises(ValueError):
        asyncio.run(record(None, tenant_id=None, actor_id=None, action="x", details={"api_token": "t"}))  # type: ignore[arg-type]
```

- [ ] **Step 2: Write the failing anchor test**

`backend/tests/core/audit/test_anchor.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import uuid
from datetime import timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import text

from dewpoint.core.audit.anchor import FileAnchorSink, anchor_all, verify_anchors
from dewpoint.core.audit.service import record, verify_chain
from dewpoint.core.db import tenant_scope


async def test_anchor_detects_full_chain_rewrite(
    tmp_path, api_sessionmaker, owner_sessionmaker, auditor_sessionmaker
) -> None:
    key, t = Ed25519PrivateKey.generate(), uuid.uuid4()
    sink = FileAnchorSink(tmp_path / "anchors.jsonl", key)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        await record(s, tenant_id=t, actor_id=None, action="member.add", target_id="a")
        await record(s, tenant_id=None, actor_id=None, action="auth.login")
    # anchoring runs as the narrow auditor role, exactly like production
    async with auditor_sessionmaker() as s, s.begin():
        assert await anchor_all(s, sink) == 2  # the tenant scope and the platform scope
        assert await anchor_all(s, sink) == 0  # idempotent: heads unchanged
    async with auditor_sessionmaker() as s:
        assert await verify_anchors(s, sink.entries(), key.public_key(), max_lag=timedelta(0)) == []
    # privileged rewrite: change the row AND correctly recompute its hash, so the chain itself verifies
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("SET LOCAL session_replication_role = replica"))
        await s.execute(text("update audit_log set target_id='z' where scope <> 'platform'"))
        await s.execute(
            text(
                "update audit_log set hash = sha256(prev_hash || convert_to(audit_canonical(seq, scope, actor_id,"
                " action, target_type, target_id, details, created_at), 'UTF8')) where scope <> 'platform'"
            )
        )
    async with auditor_sessionmaker() as s:
        assert (await verify_chain(s, str(t))).ok  # the in-database chain alone cannot detect this
        problems = await verify_anchors(s, sink.entries(), key.public_key())
    assert any("hash mismatch with external anchor" in p for p in problems)


async def test_verification_fails_closed(tmp_path, api_sessionmaker, auditor_sessionmaker) -> None:
    key, t = Ed25519PrivateKey.generate(), uuid.uuid4()
    sink = FileAnchorSink(tmp_path / "anchors.jsonl", key)
    async with auditor_sessionmaker() as s:
        assert "no external anchors found" in await verify_anchors(s, [], key.public_key())
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        await record(s, tenant_id=t, actor_id=None, action="member.add")
    async with auditor_sessionmaker() as s, s.begin():
        await anchor_all(s, sink)
    async with api_sessionmaker() as s, s.begin():  # a new row after the last anchor
        await tenant_scope(s, t)
        await record(s, tenant_id=t, actor_id=None, action="member.remove")
    async with auditor_sessionmaker() as s:
        assert await verify_anchors(s, sink.entries(), key.public_key()) == []  # within max_lag: fine
        lagging = await verify_anchors(s, sink.entries(), key.public_key(), max_lag=timedelta(0))
    assert any("not anchored" in p for p in lagging)


async def test_auditor_role_is_narrow(auditor_sessionmaker) -> None:
    import pytest
    from sqlalchemy.exc import DBAPIError

    for stmt in (
        "select 1 from users",
        "select 1 from connections",
        "select 1 from data_keys",
        "insert into audit_log(scope,action,prev_hash,hash,created_at) values ('x','y','\\x00','\\x00',now())",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with auditor_sessionmaker() as s, s.begin():
                await s.execute(text(stmt))


async def test_anchor_freshness_flags_unanchored_rows(tmp_path, api_sessionmaker, auditor_sessionmaker) -> None:
    from dewpoint.core.audit.anchor import anchor_freshness

    key, t = Ed25519PrivateKey.generate(), uuid.uuid4()
    sink = FileAnchorSink(tmp_path / "anchors.jsonl", key)
    async with auditor_sessionmaker() as s:
        assert await anchor_freshness(s, timedelta(0)) == []  # nothing to anchor yet
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        await record(s, tenant_id=t, actor_id=None, action="member.add")
    async with auditor_sessionmaker() as s:
        stale = await anchor_freshness(s, timedelta(0))
    assert len(stale) == 1 and stale[0].startswith(str(t))
    async with auditor_sessionmaker() as s, s.begin():
        await anchor_all(s, sink)
    async with auditor_sessionmaker() as s:
        assert await anchor_freshness(s, timedelta(0)) == []
    async with api_sessionmaker() as s, s.begin():  # a newer row is fine until it is older than max_age
        await tenant_scope(s, t)
        await record(s, tenant_id=t, actor_id=None, action="member.remove")
    async with auditor_sessionmaker() as s:
        assert await anchor_freshness(s, timedelta(hours=1)) == []
        assert len(await anchor_freshness(s, timedelta(0))) == 1
```

Add the fixture to `tests/conftest.py`:
```python
@pytest.fixture(scope="session")
async def auditor_sessionmaker(pg_url: str, _test_users: None) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = make_engine(_url_for(pg_url, "dewpoint_auditor"))
    yield make_sessionmaker(eng)
    await eng.dispose()
```
The `connections` table in `test_auditor_role_is_narrow` exists only from Task 12. Until then, use `tenants`, and switch it to `connections` in Task 12, Step 5.

- [ ] **Step 3: Run the tests to confirm they fail**

Run: `uv run pytest tests/core/audit -v`
Expected: FAIL (module not found)

- [ ] **Step 4: Write the migration and models**

`0005_audit.py` (`revision = "0005"`, `down_revision = "0004"`):
```python
# SPDX-License-Identifier: Apache-2.0
"""audit: append-only hash-chained log, anchors, dedicated auditor role"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# One statement per execute (asyncpg cannot run multi-statement strings).
UPGRADE = [
    r"""CREATE TABLE audit_log (
  seq bigserial PRIMARY KEY,
  scope text NOT NULL,
  tenant_id uuid,
  actor_id uuid,
  action text NOT NULL,
  target_type text NOT NULL DEFAULT '',
  target_id text NOT NULL DEFAULT '',
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL,
  prev_hash bytea NOT NULL,
  hash bytea NOT NULL
)""",
    r"""CREATE INDEX ix_audit_scope_seq ON audit_log(scope, seq DESC)""",
    r"""CREATE INDEX ix_audit_tenant_seq ON audit_log(tenant_id, seq DESC)""",
    r"""CREATE TABLE audit_anchors (
  id bigserial PRIMARY KEY,
  scope text NOT NULL,
  seq bigint NOT NULL,
  hash bytea NOT NULL,
  anchored_at timestamptz NOT NULL DEFAULT now(),
  sink text NOT NULL,
  sink_ref text NOT NULL,
  UNIQUE (scope, seq)
)""",
    r"""CREATE FUNCTION audit_canonical(p_seq bigint, p_scope text, p_actor uuid, p_action text, p_tt text, p_tid text,
                                p_details jsonb, p_ts timestamptz) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT concat_ws('|', p_seq, p_scope, COALESCE(p_actor::text, ''), p_action, p_tt, p_tid, p_details::text,
                   to_char(p_ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'))
$$""",
    r"""CREATE FUNCTION audit_append(p_tenant uuid, p_actor uuid, p_action text, p_target_type text, p_target_id text,
                             p_details jsonb) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_scope text := COALESCE(p_tenant::text, 'platform');
  v_prev bytea;
  v_seq bigint;
  v_ts timestamptz := date_trunc('microseconds', clock_timestamp());
  v_tt text := COALESCE(p_target_type, '');
  v_tid text := COALESCE(p_target_id, '');
  v_details jsonb := COALESCE(p_details, '{}'::jsonb);
BEGIN
  IF p_tenant IS NOT NULL AND p_tenant IS DISTINCT FROM app_tenant_id() THEN
    RAISE EXCEPTION 'audit tenant mismatch';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('audit:' || v_scope, 0));
  SELECT hash INTO v_prev FROM audit_log WHERE scope = v_scope ORDER BY seq DESC LIMIT 1;
  v_prev := COALESCE(v_prev, decode(repeat('00', 32), 'hex'));
  v_seq := nextval(pg_get_serial_sequence('audit_log', 'seq'));
  INSERT INTO audit_log(seq, scope, tenant_id, actor_id, action, target_type, target_id, details, created_at,
                        prev_hash, hash)
  VALUES (v_seq, v_scope, p_tenant, p_actor, p_action, v_tt, v_tid, v_details, v_ts, v_prev,
          sha256(v_prev || convert_to(audit_canonical(v_seq, v_scope, p_actor, p_action, v_tt, v_tid, v_details, v_ts), 'UTF8')));
  RETURN v_seq;
END $$""",
    r"""CREATE FUNCTION audit_reject() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'audit_log is append-only'; END $$""",
    r"""CREATE TRIGGER audit_no_update BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW EXECUTE FUNCTION audit_reject()""",
    r"""CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_log FOR EACH STATEMENT EXECUTE FUNCTION audit_reject()""",
    r"""ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY""",
    r"""-- deliberately not FORCE (see plan)
CREATE POLICY audit_tenant_read ON audit_log FOR SELECT USING (tenant_id = app_tenant_id())""",
    r"""DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dewpoint_auditor') THEN CREATE ROLE dewpoint_auditor NOLOGIN; END IF;
END $$""",
    r"""GRANT USAGE ON SCHEMA public TO dewpoint_auditor""",
    r"""CREATE POLICY audit_auditor_read ON audit_log FOR SELECT TO dewpoint_auditor USING (true)""",
    r"""REVOKE ALL ON audit_log, audit_anchors FROM PUBLIC""",
    r"""GRANT SELECT ON audit_log TO dewpoint_api, dewpoint_admin, dewpoint_auditor""",
    r"""GRANT SELECT, INSERT ON audit_anchors TO dewpoint_auditor""",
    r"""GRANT USAGE ON SEQUENCE audit_anchors_id_seq TO dewpoint_auditor""",
    r"""REVOKE EXECUTE ON FUNCTION audit_append(uuid, uuid, text, text, text, jsonb) FROM PUBLIC""",
    r"""GRANT EXECUTE ON FUNCTION audit_append(uuid, uuid, text, text, text, jsonb)
  TO dewpoint_api, dewpoint_worker, dewpoint_dispatch, dewpoint_ingress, dewpoint_admin""",
]

DOWNGRADE = [
    "DROP TABLE audit_anchors",
    "DROP TABLE audit_log",
    "DROP FUNCTION audit_append(uuid, uuid, text, text, text, jsonb)",
    "DROP FUNCTION audit_canonical(bigint, text, uuid, text, text, text, jsonb, timestamptz)",
    "DROP FUNCTION audit_reject()",
    "REVOKE ALL ON SCHEMA public FROM dewpoint_auditor",
    "DROP ROLE IF EXISTS dewpoint_auditor",
]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
```
**Test isolation note:** `clean_db` TRUNCATEs with `session_replication_role = replica`, which disables the truncate trigger for the superuser test owner. That matches the fixture from Task 3.

`core/models/audit.py` (read-only mappings; rows are written only by `audit_append()`):
```python
# SPDX-License-Identifier: Apache-2.0
"""Read-only mappings. Rows are written only by the audit_append() SQL function."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, LargeBinary, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base


class AuditEntry(Base):
    __tablename__ = "audit_log"
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scope: Mapped[str] = mapped_column(Text)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str] = mapped_column(Text)
    target_id: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    prev_hash: Mapped[bytes] = mapped_column(LargeBinary)
    hash: Mapped[bytes] = mapped_column(LargeBinary)


class AuditAnchor(Base):
    __tablename__ = "audit_anchors"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scope: Mapped[str] = mapped_column(Text)
    seq: Mapped[int] = mapped_column(BigInteger)
    hash: Mapped[bytes] = mapped_column(LargeBinary)
    anchored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sink: Mapped[str] = mapped_column(Text)
    sink_ref: Mapped[str] = mapped_column(Text)
```

- [ ] **Step 5: Implement the service and anchoring**

`core/audit/service.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import hashlib
import json
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_FORBIDDEN = re.compile(r"password|secret|token|code|credential", re.IGNORECASE)
ZERO = bytes(32)


def _check_details(d: object) -> None:
    if isinstance(d, dict):
        for k, v in d.items():
            if _FORBIDDEN.search(str(k)):
                raise ValueError(f"audit details must not contain secret-like key: {k}")
            _check_details(v)
    elif isinstance(d, list):
        for v in d:
            _check_details(v)


async def record(s: AsyncSession, *, tenant_id: uuid.UUID | None, actor_id: uuid.UUID | None, action: str,
                 target_type: str = "", target_id: str = "", details: dict[str, object] | None = None) -> int:
    _check_details(details or {})
    res = await s.execute(
        text("select audit_append(:t, :a, :act, :tt, :tid, cast(:d as jsonb))"),
        {"t": tenant_id, "a": actor_id, "act": action, "tt": target_type, "tid": target_id,
         "d": json.dumps(details or {})},
    )
    return int(res.scalar_one())


@dataclass(frozen=True)
class ChainReport:
    ok: bool
    checked: int
    first_bad_seq: int | None
    head_seq: int | None
    head_hash: bytes | None


_ROWS = text("""
select seq, audit_canonical(seq, scope, actor_id, action, target_type, target_id, details, created_at) as canon,
       prev_hash, hash
from audit_log where scope = :scope order by seq
""")


async def verify_chain(s: AsyncSession, scope: str) -> ChainReport:
    """Recompute every hash in Python. Uses the DB only to render the canonical text, not to judge it."""
    prev, checked, head_seq, head_hash = ZERO, 0, None, None
    for seq, canon, prev_hash, h in (await s.execute(_ROWS, {"scope": scope})).all():
        expected = hashlib.sha256(prev + canon.encode()).digest()
        if bytes(prev_hash) != prev or bytes(h) != expected:
            return ChainReport(False, checked, seq, head_seq, head_hash)
        prev, head_seq, head_hash, checked = expected, seq, expected, checked + 1
    return ChainReport(True, checked, None, head_seq, head_hash)
```
**Why the canonical text comes from SQL:** `details::text` and the timestamp format must be rendered exactly as they were when the row was hashed. The IMMUTABLE `audit_canonical()` is the single definition. An attacker able to replace that function could also rewrite rows, which is exactly the case external anchors catch (Step 2 test).

`core/audit/anchor.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit.service import verify_chain


def _message(scope: str, seq: int, hash_hex: str, at: str) -> bytes:
    return f"dewpoint-audit-anchor|{scope}|{seq}|{hash_hex}|{at}".encode()


class FileAnchorSink:
    """Append-only JSON-lines file, each line Ed25519-signed. Store it outside the database host
    (object storage with object lock, a SIEM, or a separate volume)."""

    name = "file"

    def __init__(self, path: Path, private_key: Ed25519PrivateKey) -> None:
        self.path, self._key = path, private_key

    def write(self, scope: str, seq: int, hash_: bytes) -> str:
        at = datetime.now(UTC).isoformat()
        hash_hex = hash_.hex()
        sig = self._key.sign(_message(scope, seq, hash_hex, at)).hex()
        entry = {"scope": scope, "seq": seq, "hash": hash_hex, "at": at, "sig": sig}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
        return f"{self.path.name}:{scope}:{seq}"

    def entries(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def anchor_all(s: AsyncSession, sink: FileAnchorSink) -> int:
    heads = (
        await s.execute(text("select distinct on (scope) scope, seq, hash from audit_log order by scope, seq desc"))
    ).all()
    written = 0
    for scope, seq, h in heads:
        exists = (
            await s.execute(text("select 1 from audit_anchors where scope=:s and seq=:q"), {"s": scope, "q": seq})
        ).first()
        if exists:
            continue
        ref = sink.write(scope, seq, bytes(h))
        await s.execute(
            text("insert into audit_anchors(scope, seq, hash, sink, sink_ref) values (:s,:q,:h,:k,:r)"),
            {"s": scope, "q": seq, "h": bytes(h), "k": sink.name, "r": ref},
        )
        written += 1
    return written


async def verify_anchors(
    s: AsyncSession,
    entries: list[dict[str, object]],
    public_key: Ed25519PublicKey,
    *,
    max_lag: timedelta = timedelta(hours=1),
    now: datetime | None = None,
) -> list[str]:
    """Fail closed: missing anchors, unanchored old rows, broken chains and mismatches are all problems."""
    problems: list[str] = []
    if not entries:
        problems.append("no external anchors found")
    db_scopes: set[str] = set((await s.execute(text("select distinct scope from audit_log"))).scalars())
    for sc in sorted(db_scopes | {str(e["scope"]) for e in entries}):
        rep = await verify_chain(s, sc)
        if not rep.ok:
            problems.append(f"{sc}: chain broken at seq {rep.first_bad_seq}")
    anchored: dict[str, int] = {}
    for e in entries:
        scope, seq, hash_hex, at = str(e["scope"]), int(e["seq"]), str(e["hash"]), str(e["at"])  # type: ignore[call-overload]
        try:
            public_key.verify(bytes.fromhex(str(e["sig"])), _message(scope, seq, hash_hex, at))
        except (InvalidSignature, ValueError):
            problems.append(f"{scope}:{seq}: bad anchor signature")
            continue
        row = (
            await s.execute(text("select hash from audit_log where scope=:s and seq=:q"), {"s": scope, "q": seq})
        ).first()
        if row is None:
            problems.append(f"{scope}:{seq}: anchored row missing")
        elif bytes(row[0]).hex() != hash_hex:
            problems.append(f"{scope}:{seq}: hash mismatch with external anchor")
        else:
            anchored[scope] = max(anchored.get(scope, 0), seq)
    cutoff = (now or datetime.now(UTC)) - max_lag
    old_rows = await s.execute(
        text("select scope, max(seq) from audit_log where created_at <= :c group by scope"), {"c": cutoff}
    )
    for scope, max_seq in old_rows.all():
        if anchored.get(scope, 0) < max_seq:
            problems.append(f"{scope}: rows up to seq {max_seq} older than {max_lag} are not anchored")
    return problems


async def anchor_freshness(s: AsyncSession, max_age: timedelta, now: datetime | None = None) -> list[str]:
    """Liveness, not integrity: scopes whose rows older than max_age have no anchor recorded at or after them.
    Reads the audit_anchors table the anchor job maintains; `audit verify` checks the signed external copy."""
    cutoff = (now or datetime.now(UTC)) - max_age
    rows = await s.execute(
        text(
            "select l.scope, max(l.seq) as due,"
            " (select max(a.seq) from audit_anchors a where a.scope = l.scope) as anchored"
            " from audit_log l where l.created_at <= :cutoff group by l.scope order by l.scope"
        ),
        {"cutoff": cutoff},
    )
    return [
        f"{scope}: rows up to seq {due} older than {max_age} have no anchor (latest anchored seq: {anchored or 'none'})"
        for scope, due, anchored in rows.all()
        if (anchored or 0) < due
    ]
```

CLI additions in `apps/cli/main.py` (the full module after this task; `audit verify` also requires `DEWPOINT_AUDIT_ANCHOR_PATH` rather than defaulting). Tested by `tests/apps/cli/test_audit_cli.py`, which runs as the auditor role: verify with no anchors exits 1, anchor succeeds, verify then exits 0, and a missing key or path exits 2:
```python
# SPDX-License-Identifier: Apache-2.0
import asyncio
import base64
import os
from pathlib import Path

import typer
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select

from dewpoint.core.audit.anchor import FileAnchorSink, anchor_all, verify_anchors
from dewpoint.core.auth.users import PasswordPolicyError, create_user
from dewpoint.core.config import get_settings
from dewpoint.core.db import make_engine, make_sessionmaker
from dewpoint.core.models.identity import User

app = typer.Typer(no_args_is_help=True)
admin = typer.Typer(no_args_is_help=True)
app.add_typer(admin, name="admin")
audit = typer.Typer(no_args_is_help=True)
app.add_typer(audit, name="audit")


async def _init(email: str, password: str) -> None:
    engine = make_engine(get_settings().database_url)
    try:
        async with make_sessionmaker(engine)() as s, s.begin():
            if (await s.execute(select(User.id).where(User.is_platform_admin.is_(True)).limit(1))).first():
                typer.echo("already initialized: a platform admin exists")
                raise typer.Exit(1)
            await create_user(s, email=email, password=password, platform_admin=True)
    finally:
        await engine.dispose()


@admin.command("init")
def admin_init(email: str = typer.Option(...)) -> None:
    """Create the first platform admin. Refuses if one already exists."""
    password = os.environ.get("DEWPOINT_INIT_PASSWORD") or typer.prompt(
        "Password", hide_input=True, confirmation_prompt=True
    )
    try:
        asyncio.run(_init(email, password))
    except PasswordPolicyError as e:
        typer.echo(f"password rejected: {', '.join(e.violations)}")
        raise typer.Exit(2) from None
    typer.echo(f"platform admin {email} created. Sign in to enroll MFA.")


def _signing_key() -> Ed25519PrivateKey:
    raw = get_settings().audit_signing_key_b64
    if not raw:
        typer.echo("DEWPOINT_AUDIT_SIGNING_KEY_B64 is not set")
        raise typer.Exit(2)
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(raw))


def _anchor_path() -> Path:
    path = get_settings().audit_anchor_path
    if not path:
        typer.echo("DEWPOINT_AUDIT_ANCHOR_PATH is not set")
        raise typer.Exit(2)
    return Path(path)


@audit.command("anchor")
def audit_anchor() -> None:
    """Write current chain heads to the external anchor sink. Run as a dewpoint_auditor login, e.g. every 15 min."""
    sink = FileAnchorSink(_anchor_path(), _signing_key())

    async def _run() -> int:
        engine = make_engine(get_settings().database_url)
        try:
            async with make_sessionmaker(engine)() as s, s.begin():
                return await anchor_all(s, sink)
        finally:
            await engine.dispose()

    typer.echo(f"anchored {asyncio.run(_run())} scope head(s)")


@audit.command("verify")
def audit_verify() -> None:
    """Recompute every chain and check it against the signed external anchors. Exit 1 on any problem,
    including when no anchors exist, so a broken anchor job can't look healthy."""
    key = _signing_key()
    sink = FileAnchorSink(_anchor_path(), key)

    async def _run() -> list[str]:
        engine = make_engine(get_settings().database_url)
        try:
            async with make_sessionmaker(engine)() as s:
                return await verify_anchors(s, sink.entries(), key.public_key())
        finally:
            await engine.dispose()

    problems = asyncio.run(_run())
    for problem in problems:
        typer.echo(problem)
    if problems:
        raise typer.Exit(1)
    typer.echo("audit chain verified against external anchors")
```
The anchor and verify commands connect as a `dewpoint_auditor` login (operators set `DEWPOINT_DATABASE_URL` to it). `audit verify` exits 1 on any problem, including when no anchors exist, so a misconfigured anchor job can't look healthy.

- [ ] **Step 6: Record audit events from the routes**

Add `from dewpoint.core.audit.service import record` to each route module and insert these calls. As built, the implementation also records `ip` on `auth.login` and `auth.login_failed`, and adds an `auth.totp_enrolled` event on successful `/totp/confirm`. Each runs inside the request transaction, before the response returns:

| Module / handler | Call |
|---|---|
| `auth.login`, success | `await record(db, tenant_id=None, actor_id=user.id, action="auth.login", details={"state": state})` |
| `auth.login`, failure (before `db.commit()`) | `await record(db, tenant_id=None, actor_id=user.id if user else None, action="auth.login_failed", details={"email": body.email.lower()})` |
| `auth.change_password` | `await record(db, tenant_id=None, actor_id=user.id, action="auth.password_changed")` |
| `mfa._complete` | `await record(db, tenant_id=None, actor_id=sess.user_id, action="auth.mfa", details={"method": method})` |
| `passkeys.register_verify`, success | `await record(db, tenant_id=None, actor_id=user.id, action="auth.passkey_registered", details={"name": body.name})` |
| `passkeys.login_verify`, success | `await record(db, tenant_id=None, actor_id=user.id, action="auth.login", details={"method": "passkey"})` |
| `tenants.create` | `await record(db, tenant_id=t.id, actor_id=admin.id, action="tenant.create", target_type="tenant", target_id=str(t.id), details={"slug": t.slug})` |
| `tenants.patch_tenant` | `await record(db, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, action="tenant.update", target_type="tenant", target_id=str(t.id), details=body.model_dump(exclude_none=True))` |
| `members.add` / `change` / `remove` | `action="member.add"` / `"member.role_change"` / `"member.remove"`, with `target_type="user"`, `target_id=str(<user_id>)`, and `details={"role": <role>}` (omit `details` for remove) |
| `admin_users` create | `await record(db, tenant_id=None, actor_id=admin.id, action="user.create", target_type="user", target_id=str(u.id))` |

`tenant_scope` is already set to the tenant by `require()` (or by `create_tenant()`), which satisfies the `audit tenant mismatch` guard.

- [ ] **Step 7: Add the audit read route**

`apps/api/routes/audit.py`:
```python
# SPDX-License-Identifier: Apache-2.0
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.authz.permissions import P
from dewpoint.core.http import TenantContext, get_db, require
from dewpoint.core.models.audit import AuditEntry

router = APIRouter(prefix="/api/v1/t/{tenant_id}/audit", tags=["audit"])


@router.get("")
async def list_audit(before_seq: int | None = None, limit: int = Query(50, ge=1, le=200),
                     ctx: TenantContext = Depends(require(P.AUDIT_VIEW)),
                     db: AsyncSession = Depends(get_db)) -> list[dict[str, object]]:
    q = select(AuditEntry).where(AuditEntry.tenant_id == ctx.tenant_id).order_by(AuditEntry.seq.desc()).limit(limit)
    if before_seq:
        q = q.where(AuditEntry.seq < before_seq)
    return [{"seq": e.seq, "at": e.created_at.isoformat(), "actor_id": str(e.actor_id) if e.actor_id else None,
             "action": e.action, "target_type": e.target_type, "target_id": e.target_id, "details": e.details}
            for e in (await db.execute(q)).scalars()]
```

Add empty `__init__.py` files (SPDX line only) to `backend/tests/`, `tests/apps/` and `tests/apps/api/` so helpers can be imported as `tests.apps.api.helpers`. Then `backend/tests/apps/api/test_audit_routes.py`: reuse the `_as` helper from `test_tenant_matrix.py` (move it into `tests/apps/api/helpers.py` as `session_client(...)`, and import it from both files). As an `admin`, `POST /members` for an existing user. Then `GET /audit` must return a first entry with `action == "member.add"` and `details == {"role": "viewer"}`, and a `viewer` must get 403 on `/audit`.

- [ ] **Step 8: Run the tests**

Run: `uv run pytest tests -q`
Expected: all PASS, including the earlier route tests, which now also write audit rows.

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "feat(audit): append-only hash-chained audit log, signed external anchors, verify CLI

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Generic connections with the Mist connection type

**Files:**
- Create: `backend/src/dewpoint/core/models/connections.py`, `backend/migrations/versions/0006_connections.py`
- Create: `backend/src/dewpoint/core/connections/__init__.py`, `types.py`, `mist_verify.py`, `service.py`
- Create: `backend/src/dewpoint/apps/api/routes/connections.py`
- Test: `backend/tests/core/connections/test_mist_verify.py`, `backend/tests/apps/api/test_connections.py`

**Interfaces:**
- Consumes: `Keyring` (Task 5), `require`/`TenantContext`/`P` (Task 10), `record` (Task 11), `session_client` test helper (Task 11).
- Produces:
  - `MIST_CLOUDS: dict[str, str]` (key → API host).
  - `MistConfig(cloud: MistCloud, org_id: UUID)`, `MistSecret(api_token: SecretStr)`.
  - `@dataclass ConnectionType(key, label, config_model, secret_model, verify)` and `CONNECTION_TYPES: dict[str, ConnectionType]`.
  - `VerifyResult(ok: bool, detail: str, privilege: str | None)`.
  - `async verify_mist(config: MistConfig, secret: MistSecret, http: httpx.AsyncClient) -> VerifyResult`.
  - Service: `create_connection(s, keyring, ctx, *, type_key, name, config: dict, secret: dict) -> Connection`, `update_connection(s, keyring, ctx, conn, *, name, config, secret) -> Connection`, `delete_connection(s, ctx, conn)`, `verify_connection(s, keyring, ctx, conn, http) -> Connection`, `load_secret(s, keyring, conn) -> BaseModel` (for workers later), `to_out(conn) -> dict`.
  - Endpoints:
    - `GET /api/v1/connection-types`;
    - `GET` / `POST /api/v1/t/{tenant_id}/connections`;
    - `GET` / `PATCH` / `DELETE /api/v1/t/{tenant_id}/connections/{connection_id}`;
    - `POST …/{connection_id}/verify`.
  - `app.state.http = httpx.AsyncClient(timeout=10, follow_redirects=False)`, created in `create_app` and closed on shutdown through the lifespan.

- [ ] **Step 1: Write the failing verify tests**

`backend/tests/core/connections/test_mist_verify.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import uuid

import httpx
import pytest
import respx
from pydantic import ValidationError

from dewpoint.core.connections.mist_verify import verify_mist
from dewpoint.core.connections.types import MistConfig, MistSecret

ORG = uuid.uuid4()


def _cfg() -> MistConfig:
    return MistConfig(cloud="emea_01", org_id=ORG)


@respx.mock
async def test_org_privilege_ok() -> None:
    route = respx.get("https://api.eu.mist.com/api/v1/self").respond(
        200, json={"privileges": [{"scope": "org", "org_id": str(ORG), "role": "write"}]}
    )
    async with httpx.AsyncClient() as http:
        r = await verify_mist(_cfg(), MistSecret(api_token="x" * 40), http)
    assert r.ok and r.privilege == "write"
    assert route.calls.last.request.headers["Authorization"] == "Token " + "x" * 40


@respx.mock
async def test_msp_access_confirmed_via_org_endpoint() -> None:
    respx.get("https://api.eu.mist.com/api/v1/self").respond(
        200, json={"privileges": [{"scope": "msp", "role": "admin"}]}
    )
    respx.get(f"https://api.eu.mist.com/api/v1/orgs/{ORG}").respond(200, json={"id": str(ORG)})
    async with httpx.AsyncClient() as http:
        r = await verify_mist(_cfg(), MistSecret(api_token="x" * 40), http)
    assert r.ok and r.privilege == "msp"


@respx.mock
async def test_bad_token_and_no_access() -> None:
    respx.get("https://api.eu.mist.com/api/v1/self").respond(401)
    async with httpx.AsyncClient() as http:
        r = await verify_mist(_cfg(), MistSecret(api_token="x" * 40), http)
    assert not r.ok and r.detail == "invalid_token"


def test_unknown_cloud_rejected() -> None:
    with pytest.raises(ValidationError):
        MistConfig(cloud="evil.example.com", org_id=ORG)  # type: ignore[arg-type]


def test_cloud_literal_matches_allowlist() -> None:
    from typing import get_args

    from dewpoint.core.connections.types import MIST_CLOUDS, MistCloud

    assert set(MIST_CLOUDS) == set(get_args(MistCloud))
```

- [ ] **Step 2: Implement the types and verification**

`core/connections/types.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

# Source: mistapi cloud list (verify against the current library when updating).
MIST_CLOUDS: dict[str, str] = {
    "global_01": "api.mist.com", "global_02": "api.gc1.mist.com", "global_03": "api.ac2.mist.com",
    "global_04": "api.gc2.mist.com", "global_05": "api.gc4.mist.com",
    "emea_01": "api.eu.mist.com", "emea_02": "api.gc3.mist.com", "emea_03": "api.ac6.mist.com",
    "emea_04": "api.gc6.mist.com",
    "apac_01": "api.ac5.mist.com", "apac_02": "api.gc5.mist.com", "apac_03": "api.gc7.mist.com",
}
MistCloud = Literal["global_01", "global_02", "global_03", "global_04", "global_05", "emea_01", "emea_02",
                    "emea_03", "emea_04", "apac_01", "apac_02", "apac_03"]


class MistConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cloud: MistCloud
    org_id: uuid.UUID


class MistSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_token: SecretStr = Field(min_length=20, max_length=200)


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    detail: str
    privilege: str | None = None


@dataclass(frozen=True)
class ConnectionType:
    key: str
    label: str
    config_model: type[BaseModel]
    secret_model: type[BaseModel]
    verify: Callable[[BaseModel, BaseModel, httpx.AsyncClient], Awaitable[VerifyResult]]


def _registry() -> dict[str, ConnectionType]:
    from dewpoint.core.connections.mist_verify import verify_mist
    return {"mist": ConnectionType("mist", "Juniper Mist", MistConfig, MistSecret, verify_mist)}  # type: ignore[arg-type]


CONNECTION_TYPES: dict[str, ConnectionType] = _registry()
```
In sub-project 2 this registry is populated from plugin manifests. `MistCloud` must stay in sync with `MIST_CLOUDS`; add the assertion test `set(MIST_CLOUDS) == set(get_args(MistCloud))` to `test_mist_verify.py`.

`core/connections/mist_verify.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import httpx

from dewpoint.core.connections.types import MIST_CLOUDS, MistConfig, MistSecret, VerifyResult


async def verify_mist(config: MistConfig, secret: MistSecret, http: httpx.AsyncClient) -> VerifyResult:
    base = f"https://{MIST_CLOUDS[config.cloud]}/api/v1"  # host from allowlist only
    headers = {"Authorization": f"Token {secret.api_token.get_secret_value()}", "Accept": "application/json"}
    try:
        r = await http.get(f"{base}/self", headers=headers, follow_redirects=False, timeout=10)
        if r.status_code in (401, 403):
            return VerifyResult(False, "invalid_token")
        if r.status_code != 200:
            return VerifyResult(False, "unexpected_status")
        privileges = r.json().get("privileges", [])
        for p in privileges:
            if p.get("scope") == "org" and p.get("org_id") == str(config.org_id):
                return VerifyResult(True, "ok", str(p.get("role")))
        if any(p.get("scope") == "msp" for p in privileges):
            o = await http.get(f"{base}/orgs/{config.org_id}", headers=headers, follow_redirects=False, timeout=10)
            if o.status_code == 200:
                return VerifyResult(True, "ok", "msp")
        return VerifyResult(False, "no_org_access")
    except (httpx.HTTPError, ValueError):
        return VerifyResult(False, "unreachable")
```

- [ ] **Step 3: Run the verify tests**

Run: `uv run pytest tests/core/connections -v`
Expected: all PASS

- [ ] **Step 4: Write the model and migration**

`core/models/connections.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base, Timestamps, UUIDPk


class Connection(UUIDPk, Timestamps, Base):
    __tablename__ = "connections"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    secret_ct: Mapped[bytes | None] = mapped_column(LargeBinary)
    revision: Mapped[int] = mapped_column(Integer, default=1)  # bumped on config/secret change
    status: Mapped[str] = mapped_column(String(20), default="unverified")  # unverified | ok | error
    status_detail: Mapped[str] = mapped_column(String(40), default="")
    privilege: Mapped[str | None] = mapped_column(String(40))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
```

`migrations/versions/0006_connections.py`:
```python
# SPDX-License-Identifier: Apache-2.0
"""connections: generic, typed, secrets encrypted with the tenant data key"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("config", pg.JSONB, nullable=False),
        sa.Column("secret_ct", sa.LargeBinary),
        # Increments whenever config or secret changes; a verification result applies only to the revision it read.
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="unverified"),
        sa.Column("status_detail", sa.String(40), nullable=False, server_default=""),
        sa.Column("privilege", sa.String(40)),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "name"),
    )
    for stmt in (
        "ALTER TABLE connections ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE connections FORCE ROW LEVEL SECURITY",
        "CREATE POLICY connections_scope ON connections "
        "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON connections TO dewpoint_api, dewpoint_admin",
        "GRANT SELECT ON connections TO dewpoint_worker",
    ):
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS connections_scope ON connections")
    op.drop_table("connections")
```

- [ ] **Step 5: Write the failing route tests**

In `tests/core/audit/test_anchor.py::test_auditor_role_is_narrow`, change `"select 1 from tenants"` to `"select 1 from connections"`.

`backend/tests/apps/api/test_connections.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import asyncio
import uuid

import httpx
import respx
from sqlalchemy import text

from tests.apps.api.helpers import session_client

ORG = str(uuid.uuid4())
BODY = {
    "type": "mist",
    "name": "Acme Prod",
    "config": {"cloud": "emea_01", "org_id": ORG},
    "secret": {"api_token": "tok_" + "a" * 36},
}


async def test_create_list_never_returns_secret(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        r = await c.post(f"/api/v1/t/{tid}/connections", json=BODY)
        assert r.status_code == 201, r.text
        out = r.json()
        assert out["secret_set"] is True and "secret" not in out and "secret_ct" not in out
        assert "tok_" not in (await c.get(f"/api/v1/t/{tid}/connections")).text
    async with owner_sessionmaker() as s:
        ct = (await s.execute(text("select secret_ct from connections"))).scalar_one()
    assert b"tok_" not in ct


async def test_editor_can_view_not_manage(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        assert (await c.post(f"/api/v1/t/{tid}/connections", json=BODY)).status_code == 403
        assert (await c.get(f"/api/v1/t/{tid}/connections")).status_code == 200


async def test_invalid_cloud_and_extra_fields_rejected(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        bad = {**BODY, "config": {"cloud": "evil.example.com", "org_id": ORG}}
        assert (await c.post(f"/api/v1/t/{tid}/connections", json=bad)).status_code == 422
        bad = {**BODY, "config": {**BODY["config"], "host": "evil.example.com"}}
        assert (await c.post(f"/api/v1/t/{tid}/connections", json=bad)).status_code == 422


@respx.mock
async def test_verify_updates_status_and_audits(app, owner_sessionmaker, api_settings) -> None:
    respx.get("https://api.eu.mist.com/api/v1/self").respond(
        200, json={"privileges": [{"scope": "org", "org_id": ORG, "role": "admin"}]}
    )
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        cid = (await c.post(f"/api/v1/t/{tid}/connections", json=BODY)).json()["id"]
        r = await c.post(f"/api/v1/t/{tid}/connections/{cid}/verify")
        assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["privilege"] == "admin"
        actions = [e["action"] for e in (await c.get(f"/api/v1/t/{tid}/audit")).json()]
    assert actions[:2] == ["connection.verify", "connection.create"]


async def test_patch_keeps_secret_when_omitted_and_ciphertext_is_bound(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        a = (await c.post(f"/api/v1/t/{tid}/connections", json=BODY)).json()["id"]
        b = (await c.post(f"/api/v1/t/{tid}/connections", json={**BODY, "name": "Other"})).json()["id"]
        r = await c.patch(f"/api/v1/t/{tid}/connections/{a}", json={"name": "Renamed"})
        assert r.status_code == 200 and r.json()["secret_set"] is True
        # swapping ciphertext between rows must not decrypt (AAD binds the connection id)
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(
                text("update connections set secret_ct=(select secret_ct from connections where id=:a) where id=:b"),
                {"a": a, "b": b},
            )
        r = await c.post(f"/api/v1/t/{tid}/connections/{b}/verify")
    assert r.status_code == 200
    assert r.json()["status"] == "error" and r.json()["status_detail"] == "secret_unreadable"


async def test_rename_to_existing_name_is_a_conflict(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        await c.post(f"/api/v1/t/{tid}/connections", json=BODY)
        other = (await c.post(f"/api/v1/t/{tid}/connections", json={**BODY, "name": "Other"})).json()["id"]
        r = await c.patch(f"/api/v1/t/{tid}/connections/{other}", json={"name": "Acme Prod"})
    assert r.status_code == 409 and r.json() == {"error": "name_taken"}


def _paused_mist(release: asyncio.Event, started: asyncio.Event) -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        started.set()
        await release.wait()  # hold the verification in flight
        return httpx.Response(200, json={"privileges": [{"scope": "org", "org_id": ORG, "role": "admin"}]})

    respx.get("https://api.eu.mist.com/api/v1/self").mock(side_effect=slow)


@respx.mock
async def test_verification_does_not_certify_credentials_edited_in_flight(
    app, owner_sessionmaker, api_settings
) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    started, release = asyncio.Event(), asyncio.Event()
    _paused_mist(release, started)
    async with c:
        cid = (await c.post(f"/api/v1/t/{tid}/connections", json=BODY)).json()["id"]
        verify = asyncio.create_task(c.post(f"/api/v1/t/{tid}/connections/{cid}/verify"))
        try:
            await asyncio.wait_for(started.wait(), 10)  # verification loaded revision 1 and is talking to "Mist"
            new_secret = {"secret": {"api_token": "tok_" + "b" * 36}}
            edited = await c.patch(f"/api/v1/t/{tid}/connections/{cid}", json=new_secret)
        finally:
            release.set()  # never leave the paused request (and its DB connection) hanging
            r = await asyncio.wait_for(verify, 10)
        assert edited.status_code == 200 and edited.json()["revision"] == 2
        assert r.status_code == 409 and r.json() == {"error": "changed_during_verification"}
        after = (await c.get(f"/api/v1/t/{tid}/connections/{cid}")).json()
        actions = [e["action"] for e in (await c.get(f"/api/v1/t/{tid}/audit")).json()]
    assert after["status"] == "unverified" and after["revision"] == 2  # the edit's state survives
    assert actions[0] == "connection.verify_discarded"


@respx.mock
async def test_rename_during_verification_keeps_the_result(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    started, release = asyncio.Event(), asyncio.Event()
    _paused_mist(release, started)
    async with c:
        cid = (await c.post(f"/api/v1/t/{tid}/connections", json=BODY)).json()["id"]
        verify = asyncio.create_task(c.post(f"/api/v1/t/{tid}/connections/{cid}/verify"))
        try:
            await asyncio.wait_for(started.wait(), 10)
            await c.patch(f"/api/v1/t/{tid}/connections/{cid}", json={"name": "Renamed"})  # not a credential change
        finally:
            release.set()
            r = await asyncio.wait_for(verify, 10)
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["name"] == "Renamed"
```

- [ ] **Step 6: Implement the service and routes**

`core/connections/service.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from cryptography.exceptions import InvalidTag
from pydantic import BaseModel, SecretStr
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit.service import record
from dewpoint.core.connections.types import CONNECTION_TYPES, ConnectionType
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.http import TenantContext
from dewpoint.core.models.connections import Connection

PURPOSE = "connection.secret"


class UnknownTypeError(ValueError): ...


def _type(key: str) -> ConnectionType:
    if key not in CONNECTION_TYPES:
        raise UnknownTypeError(key)
    return CONNECTION_TYPES[key]


def _secret_json(model: BaseModel) -> bytes:
    data = {k: (v.get_secret_value() if isinstance(v, SecretStr) else v) for k, v in model}
    return json.dumps(data).encode()


async def create_connection(
    s: AsyncSession,
    keyring: Keyring,
    ctx: TenantContext,
    *,
    type_key: str,
    name: str,
    config: dict[str, Any],
    secret: dict[str, Any],
) -> Connection:
    ct = _type(type_key)
    cfg, sec = ct.config_model.model_validate(config), ct.secret_model.model_validate(secret)
    conn = Connection(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        type=type_key,
        name=name,
        config=cfg.model_dump(mode="json"),
        created_by=ctx.user.id,
    )
    conn.secret_ct = await keyring.encrypt(
        s, tenant_id=ctx.tenant_id, purpose=PURPOSE, context=str(conn.id), plaintext=_secret_json(sec)
    )
    s.add(conn)
    await s.flush()
    await record(
        s,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="connection.create",
        target_type="connection",
        target_id=str(conn.id),
        details={"type": type_key, "name": name},
    )
    return conn


async def update_connection(
    s: AsyncSession,
    keyring: Keyring,
    ctx: TenantContext,
    conn: Connection,
    *,
    name: str | None,
    config: dict[str, Any] | None,
    secret: dict[str, Any] | None,
) -> Connection:
    ct = _type(conn.type)
    changed: list[str] = []
    if name is not None:
        conn.name = name
        changed.append("name")
    if config is not None:
        conn.config = ct.config_model.model_validate(config).model_dump(mode="json")
        changed.append("config")
    if secret is not None:
        conn.secret_ct = await keyring.encrypt(
            s,
            tenant_id=ctx.tenant_id,
            purpose=PURPOSE,
            context=str(conn.id),
            plaintext=_secret_json(ct.secret_model.model_validate(secret)),
        )
        changed.append("secret")
    if {"config", "secret"} & set(changed):
        conn.status, conn.status_detail, conn.privilege = "unverified", "", None
        conn.revision = Connection.revision + 1  # in SQL: concurrent edits can't collapse into one revision
    await s.flush()
    await s.refresh(conn)  # load the SQL-computed revision (no lazy loads in async code)
    await record(
        s,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="connection.update",
        target_type="connection",
        target_id=str(conn.id),
        details={"changed": changed},
    )
    return conn


async def delete_connection(s: AsyncSession, ctx: TenantContext, conn: Connection) -> None:
    await s.delete(conn)
    await record(
        s,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="connection.delete",
        target_type="connection",
        target_id=str(conn.id),
    )


async def load_secret(s: AsyncSession, keyring: Keyring, conn: Connection) -> BaseModel:
    raw = await keyring.decrypt(
        s, tenant_id=conn.tenant_id, purpose=PURPOSE, context=str(conn.id), blob=conn.secret_ct or b""
    )
    return _type(conn.type).secret_model.model_validate_json(raw)


class StaleVerificationError(Exception):
    """The connection's config or secret changed while it was being verified; the result was discarded."""


async def verify_connection(
    s: AsyncSession, keyring: Keyring, ctx: TenantContext, conn: Connection, http: httpx.AsyncClient
) -> Connection:
    """Verify the credentials as loaded, then record the result only if they are still the current revision.
    Raises StaleVerificationError (after auditing it) when an edit committed while the check was in flight."""
    ct, loaded_revision = _type(conn.type), conn.revision
    try:
        secret = await load_secret(s, keyring, conn)
    except (InvalidTag, ValueError):
        status, detail, privilege = "error", "secret_unreadable", None
    else:
        result = await ct.verify(ct.config_model.model_validate(conn.config), secret, http)
        status, detail, privilege = ("ok" if result.ok else "error"), result.detail, result.privilege
    applied = await s.execute(
        update(Connection)
        .where(Connection.id == conn.id, Connection.revision == loaded_revision)
        .values(status=status, status_detail=detail, privilege=privilege, last_verified_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    await s.refresh(conn)  # current row, including concurrent non-credential edits such as a rename
    stale = getattr(applied, "rowcount", 0) == 0
    await record(
        s,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="connection.verify_discarded" if stale else "connection.verify",
        target_type="connection",
        target_id=str(conn.id),
        details={"status": status, "verified_revision": loaded_revision},
    )
    if stale:
        raise StaleVerificationError()
    return conn


def to_out(conn: Connection) -> dict[str, object]:
    return {
        "id": str(conn.id),
        "type": conn.type,
        "name": conn.name,
        "revision": conn.revision,
        "config": conn.config,
        "secret_set": conn.secret_ct is not None,
        "status": conn.status,
        "status_detail": conn.status_detail,
        "privilege": conn.privilege,
        "last_verified_at": conn.last_verified_at.isoformat() if conn.last_verified_at else None,
    }
```
`core/connections/service.py` imports `TenantContext` from `dewpoint.core.http`. That's allowed by the import-linter contract, because `core.http` is the one module permitted to import FastAPI and `core.connections` doesn't import FastAPI itself.

`apps/api/routes/connections.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps.api.deps import get_keyring
from dewpoint.core.authz.permissions import P
from dewpoint.core.connections import service
from dewpoint.core.connections.types import CONNECTION_TYPES, MIST_CLOUDS
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.http import TenantContext, active_session, get_db, require
from dewpoint.core.models.connections import Connection

router = APIRouter(prefix="/api/v1", tags=["connections"])


class CreateIn(BaseModel):
    type: str
    name: str = Field(min_length=1, max_length=100)
    config: dict[str, Any]
    secret: dict[str, Any]


class PatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    config: dict[str, Any] | None = None
    secret: dict[str, Any] | None = None


def _http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http  # type: ignore[no-any-return]


def _invalid(exc: ValidationError) -> HTTPException:
    return HTTPException(
        422, detail={"error": "invalid", "fields": [".".join(map(str, e["loc"])) for e in exc.errors()]}
    )


async def _get(db: AsyncSession, ctx: TenantContext, connection_id: uuid.UUID) -> Connection:
    conn = (
        await db.execute(
            select(Connection).where(Connection.id == connection_id, Connection.tenant_id == ctx.tenant_id)
        )
    ).scalar_one_or_none()
    if conn is None:
        raise HTTPException(404, detail={"error": "not_found"})
    return conn


@router.get("/connection-types", dependencies=[Depends(active_session)])
async def connection_types() -> list[dict[str, object]]:
    return [
        {
            "key": t.key,
            "label": t.label,
            "config_schema": t.config_model.model_json_schema(),
            "secret_fields": list(t.secret_model.model_fields),
            **({"clouds": MIST_CLOUDS} if t.key == "mist" else {}),
        }
        for t in CONNECTION_TYPES.values()
    ]


@router.get("/t/{tenant_id}/connections")
async def list_connections(
    ctx: TenantContext = Depends(require(P.CONNECTION_VIEW)), db: AsyncSession = Depends(get_db)
) -> list[dict[str, object]]:
    rows = await db.execute(select(Connection).where(Connection.tenant_id == ctx.tenant_id).order_by(Connection.name))
    return [service.to_out(c) for c in rows.scalars()]


@router.post("/t/{tenant_id}/connections", status_code=201)
async def create(
    body: CreateIn,
    ctx: TenantContext = Depends(require(P.CONNECTION_MANAGE)),
    db: AsyncSession = Depends(get_db),
    keyring: Keyring = Depends(get_keyring),
) -> dict[str, object]:
    try:
        conn = await service.create_connection(
            db, keyring, ctx, type_key=body.type, name=body.name, config=body.config, secret=body.secret
        )
    except service.UnknownTypeError:
        raise HTTPException(422, detail={"error": "unknown_type"}) from None
    except ValidationError as e:
        raise _invalid(e) from None
    except IntegrityError:
        raise HTTPException(409, detail={"error": "name_taken"}) from None
    return service.to_out(conn)


@router.get("/t/{tenant_id}/connections/{connection_id}")
async def get_one(
    connection_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.CONNECTION_VIEW)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return service.to_out(await _get(db, ctx, connection_id))


@router.patch("/t/{tenant_id}/connections/{connection_id}")
async def patch(
    connection_id: uuid.UUID,
    body: PatchIn,
    ctx: TenantContext = Depends(require(P.CONNECTION_MANAGE)),
    db: AsyncSession = Depends(get_db),
    keyring: Keyring = Depends(get_keyring),
) -> dict[str, object]:
    conn = await _get(db, ctx, connection_id)
    try:
        conn = await service.update_connection(
            db, keyring, ctx, conn, name=body.name, config=body.config, secret=body.secret
        )
    except ValidationError as e:
        raise _invalid(e) from None
    except IntegrityError:
        raise HTTPException(409, detail={"error": "name_taken"}) from None
    return service.to_out(conn)


@router.delete("/t/{tenant_id}/connections/{connection_id}", status_code=204)
async def delete(
    connection_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.CONNECTION_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await service.delete_connection(db, ctx, await _get(db, ctx, connection_id))
    return Response(status_code=204)


@router.post("/t/{tenant_id}/connections/{connection_id}/verify")
async def verify(
    connection_id: uuid.UUID,
    request: Request,
    ctx: TenantContext = Depends(require(P.CONNECTION_MANAGE)),
    db: AsyncSession = Depends(get_db),
    keyring: Keyring = Depends(get_keyring),
) -> dict[str, object]:
    try:
        conn = await service.verify_connection(db, keyring, ctx, await _get(db, ctx, connection_id), _http(request))
    except service.StaleVerificationError:
        await db.commit()  # keep the verify_discarded audit entry
        raise HTTPException(409, detail={"error": "changed_during_verification"}) from None
    return service.to_out(conn)
```
In `create_app`, add a lifespan that creates `app.state.http = httpx.AsyncClient(timeout=10, follow_redirects=False)` and closes it on shutdown. Then include the router.

**Test-client note:** `ASGITransport` doesn't run the lifespan. So `create_app` also sets `app.state.http` eagerly, and the lifespan only closes it. The `app` fixture closes it with `await application.state.http.aclose()` after `engine.dispose()`.


- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests -q && uv run mypy src && uv run lint-imports`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat(connections): generic encrypted connections with Mist type, cloud allowlist and verification

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 13: Frontend shell: tokens, auth screens, tenant switcher, security page, connections

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`, `frontend/eslint.config.js`
- Create: `frontend/src/main.tsx`, `frontend/src/router.tsx`, `frontend/src/styles/tokens.css`, `frontend/src/styles/app.css`
- Create: `frontend/src/lib/api.ts`, `frontend/src/lib/session.ts`, `frontend/src/lib/webauthn.ts`
- Create: `frontend/src/components/Button.tsx`, `Field.tsx`, `Shell.tsx`, `TenantSwitcher.tsx`, `StatusBadge.tsx`
- Create: `frontend/src/routes/Login.tsx`, `Mfa.tsx`, `Enroll.tsx`, `Tenants.tsx`, `Security.tsx`, `Connections.tsx`
- Test: `frontend/src/lib/api.test.ts`, `frontend/src/routes/Login.test.tsx`

**Interfaces:**
- Consumes: the HTTP endpoints from Tasks 8–12, exactly as specified there.
- Produces:
  - `api<T>(method, path, body?) -> Promise<T>`, which throws `ApiError { status: number; code: string; body: unknown }`.
  - `setCsrf(token)`.
  - `useSession()` (a TanStack Query hook for `GET /api/v1/auth/session`), returning `{ user, state, auth_methods, csrf_token } | null`.
  - `registerPasskey(kind: "register", name?)` / `authenticatePasskey(kind: "login" | "mfa" | "stepup")`, which wrap `@simplewebauthn/browser` with our `/options` and `/verify` endpoints.
  - Routes: `/login`, `/mfa`, `/enroll`, `/tenants`, `/account/security`, `/t/$tenantId/connections`.
  - `data-testid`s used by Task 14's end-to-end tests: `login-email`, `login-password`, `login-submit`, `login-passkey`, `totp-secret`, `totp-code`, `totp-submit`, `recovery-codes`, `recovery-ack`, `tenant-name`, `tenant-slug`, `tenant-create`, `tenant-switcher`, `passkey-add`, `conn-add`, `conn-name`, `conn-cloud`, `conn-org`, `conn-token`, `conn-save`, `conn-row`.

**Design rules** (spec §10.1; the mockup palette lives in the tokens):
- IBM Plex Sans for UI and IBM Plex Mono for identifiers and IDs.
- A toned neutral background; teal `--accent` only for primary actions and focus.
- No gradients, shadows beyond a 1px border plus a subtle drop on overlays, emoji or sparkle icons.
- 44px minimum touch targets and visible focus rings.

- [ ] **Step 1: Scaffold and install**

`frontend/package.json`:
```json
{
  "name": "dewpoint-web",
  "private": true,
  "packageManager": "pnpm@12.6.0",
  "type": "module",
  "license": "Apache-2.0",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "lint": "eslint .",
    "typecheck": "tsc -b --noEmit",
    "test": "vitest run",
    "e2e": "playwright test"
  },
  "dependencies": {
    "@fontsource/ibm-plex-mono": "^5.1.0",
    "@fontsource/ibm-plex-sans": "^5.1.0",
    "@radix-ui/react-dialog": "^1.1.2",
    "@radix-ui/react-dropdown-menu": "^2.1.2",
    "@simplewebauthn/browser": "^11.0.0",
    "@tanstack/react-query": "^5.59.0",
    "@tanstack/react-router": "^1.79.0",
    "qrcode": "^1.5.4",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@playwright/test": "^1.48.0",
    "@tailwindcss/vite": "^4.0.0",
    "@testing-library/react": "^16.0.1",
    "@testing-library/user-event": "^14.5.2",
    "@types/qrcode": "^1.5.5",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.3",
    "eslint": "^9.14.0",
    "jsdom": "^25.0.1",
    "otpauth": "^9.3.4",
    "tailwindcss": "^4.0.0",
    "typescript": "^5.6.3",
    "typescript-eslint": "^8.13.0",
    "vite": "^6.0.0",
    "vitest": "^3.2.7"
  }
}
```
Run: `cd frontend && npx pnpm@12.6.0 install` (this creates `pnpm-lock.yaml`; commit it). **Don't install pnpm globally.** The shared development machine runs it through `npx` at the version pinned in `packageManager`, and CI uses `pnpm/action-setup`, which reads the same field.

`frontend/vite.config.ts`:
```ts
// SPDX-License-Identifier: Apache-2.0
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": "http://localhost:8000", "/health": "http://localhost:8000" } },
  build: { sourcemap: false },
  test: { environment: "jsdom", globals: false, include: ["src/**/*.test.{ts,tsx}"] },
});
```
Configure `tsconfig.json` with `strict: true`, `noUncheckedIndexedAccess: true`, `jsx: "react-jsx"` and `moduleResolution: "bundler"`. `eslint.config.js` uses `typescript-eslint` recommended-type-checked.

- [ ] **Step 2: Write the failing tests**

`frontend/src/lib/api.test.ts`:
```ts
// SPDX-License-Identifier: Apache-2.0
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, setCsrf } from "./api";

afterEach(() => vi.restoreAllMocks());

describe("api", () => {
  it("sends client header always and csrf on unsafe methods", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    setCsrf("tok123");
    await api("GET", "/api/v1/tenants");
    await api("POST", "/api/v1/tenants", { name: "A" });
    const [, getInit] = fetchMock.mock.calls[0]!;
    const [, postInit] = fetchMock.mock.calls[1]!;
    expect(new Headers(getInit!.headers).get("X-CSRF-Token")).toBeNull();
    expect(new Headers(postInit!.headers).get("X-CSRF-Token")).toBe("tok123");
    expect(new Headers(postInit!.headers).get("X-Dewpoint-Client")).toBe("web");
    expect(postInit!.credentials).toBe("same-origin");
  });

  it("maps error bodies to ApiError codes and learns csrf from responses", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: "invalid_credentials" }), { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ state: "active", csrf_token: "new" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(api("POST", "/api/v1/auth/login", {})).rejects.toMatchObject({ status: 401, code: "invalid_credentials" });
    await api("POST", "/api/v1/auth/mfa/totp", { code: "123456" });
    await api("POST", "/api/v1/auth/logout");
    const last = vi.mocked(globalThis.fetch).mock.calls[2]![1]!;
    expect(new Headers(last.headers).get("X-CSRF-Token")).toBe("new");
    expect(new ApiError(500, "x", null)).toBeInstanceOf(Error);
  });
});
```

`frontend/src/routes/Login.test.tsx`:
```tsx
// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { LoginForm } from "./Login";

it("shows a generic error and never echoes the password", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ error: "invalid_credentials" }), { status: 401 }),
  );
  const onDone = vi.fn();
  render(<LoginForm onDone={onDone} />);
  await userEvent.type(screen.getByTestId("login-email"), "a@corp.test");
  await userEvent.type(screen.getByTestId("login-password"), "hunter2-secret");
  await userEvent.click(screen.getByTestId("login-submit"));
  expect((await screen.findByRole("alert")).textContent).toBe("Email or password is incorrect.");
  expect(document.body.textContent).not.toContain("hunter2-secret");
  expect(onDone).not.toHaveBeenCalled();
});
```

Run: `npx pnpm@12.6.0 test`
Expected: FAIL (modules not found)

- [ ] **Step 3: Implement the API client and session**

`src/lib/api.ts`:
```ts
// SPDX-License-Identifier: Apache-2.0
export class ApiError extends Error {
  constructor(public status: number, public code: string, public body: unknown) {
    super(`${status} ${code}`);
  }
}

let csrf: string | null = null;
export function setCsrf(token: string | null): void {
  csrf = token;
}

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/** Like api(), but also returns the HTTP status, for callers whose contract depends on it. */
export async function request<T = unknown>(
  method: string,
  path: string,
  body?: unknown,
): Promise<{ status: number; data: T }> {
  const headers = new Headers({ "X-Dewpoint-Client": "web", Accept: "application/json" });
  if (body !== undefined) headers.set("Content-Type", "application/json");
  if (UNSAFE.has(method) && csrf) headers.set("X-CSRF-Token", csrf);
  const res = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data: unknown = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const code = (data as { error?: string } | null)?.error ?? "http_error";
    throw new ApiError(res.status, code, data);
  }
  const token = (data as { csrf_token?: string } | null)?.csrf_token;
  if (token) setCsrf(token);
  return { status: res.status, data: data as T };
}

export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  return (await request<T>(method, path, body)).data;
}
```

`src/lib/session.ts`:
```ts
// SPDX-License-Identifier: Apache-2.0
import { useQuery } from "@tanstack/react-query";
import { ApiError, api } from "./api";

export type SessionState = "mfa_pending" | "enroll_required" | "active";
export interface Session {
  user: { id: string; email: string; is_platform_admin: boolean };
  state: SessionState;
  auth_methods: string[];
  csrf_token: string;
}

export function useSession() {
  return useQuery({
    queryKey: ["session"],
    queryFn: async () => {
      try {
        return await api<Session>("GET", "/api/v1/auth/session");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 30_000,
  });
}
```

`src/lib/webauthn.ts`:
```ts
// SPDX-License-Identifier: Apache-2.0
import { startAuthentication, startRegistration } from "@simplewebauthn/browser";
import { api } from "./api";

type CreationOptions = Parameters<typeof startRegistration>[0]["optionsJSON"];
type RequestOptions = Parameters<typeof startAuthentication>[0]["optionsJSON"];
const BASE = "/api/v1/auth/passkeys";
interface Challenge<T> {
  options: T;
  challenge_id: string;
}
interface Verified {
  state: string;
  csrf_token: string;
}

export async function registerPasskey(name = "Passkey"): Promise<Verified> {
  const o = await api<Challenge<CreationOptions>>("POST", `${BASE}/register/options`);
  const credential = await startRegistration({ optionsJSON: o.options });
  return api<Verified>("POST", `${BASE}/register/verify`, { challenge_id: o.challenge_id, credential, name });
}

export async function authenticatePasskey(kind: "login" | "mfa" | "stepup"): Promise<Verified> {
  const o = await api<Challenge<RequestOptions>>("POST", `${BASE}/${kind}/options`);
  const credential = await startAuthentication({ optionsJSON: o.options });
  return api<Verified>("POST", `${BASE}/${kind}/verify`, { challenge_id: o.challenge_id, credential });
}
```

- [ ] **Step 4: Tokens and base styles**

`src/styles/tokens.css`:
```css
/* SPDX-License-Identifier: Apache-2.0 */
:root {
  --ground: #f4f5f2;
  --surface: #ffffff;
  --surface-2: #f8f9f7;
  --ink: #15181c;
  --muted: #545b64;
  --line: #dde1dc;
  --line-strong: #cbd0ca;
  --accent: #0e6874;
  --accent-ink: #0a4f58;
  --accent-soft: #e3f0f1;
  --warn-bg: #fff3dc;
  --warn-line: #e5a93c;
  --warn-ink: #7a4a00;
  --danger: #b42318;
  --danger-bg: #fdecea;
  --ok: #1c6b3a;
  --ok-bg: #e5f3ea;
  --live: #b54708;
  --live-bg: #fef0e6;
  --radius: 8px;
  --font-sans: "IBM Plex Sans", system-ui, sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ground: #111315; --surface: #1a1d20; --surface-2: #202428; --ink: #e8eae6; --muted: #a3aab2;
    --line: #2c3136; --line-strong: #3a4046; --accent: #3fa7b4; --accent-ink: #8fd3dc; --accent-soft: #15333a;
    --warn-bg: #3a2a0c; --warn-line: #a8741b; --warn-ink: #f3c878; --danger: #f07a70; --danger-bg: #3a1714;
    --ok: #6fcf97; --ok-bg: #12301f; --live: #f59e5b; --live-bg: #3a2210;
  }
}
:root[data-theme="dark"] {
  --ground: #111315; --surface: #1a1d20; --surface-2: #202428; --ink: #e8eae6; --muted: #a3aab2;
  --line: #2c3136; --line-strong: #3a4046; --accent: #3fa7b4; --accent-ink: #8fd3dc; --accent-soft: #15333a;
  --warn-bg: #3a2a0c; --warn-line: #a8741b; --warn-ink: #f3c878; --danger: #f07a70; --danger-bg: #3a1714;
  --ok: #6fcf97; --ok-bg: #12301f; --live: #f59e5b; --live-bg: #3a2210;
}
```

`src/styles/app.css`:
```css
/* SPDX-License-Identifier: Apache-2.0 */
@import "tailwindcss";
@import "./tokens.css";
@theme inline {
  --color-ground: var(--ground); --color-surface: var(--surface); --color-surface-2: var(--surface-2);
  --color-ink: var(--ink); --color-muted: var(--muted); --color-line: var(--line); --color-line-strong: var(--line-strong);
  --color-accent: var(--accent); --color-accent-ink: var(--accent-ink); --color-accent-soft: var(--accent-soft);
  --color-danger: var(--danger); --color-ok: var(--ok); --color-live: var(--live);
  --font-sans: var(--font-sans); --font-mono: var(--font-mono);
}
html, body { background: var(--ground); color: var(--ink); font-family: var(--font-sans); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
```

`src/main.tsx` imports `@fontsource/ibm-plex-sans/400.css`, `/500.css`, `/600.css`, `@fontsource/ibm-plex-mono/400.css` and `./styles/app.css`, then renders `<QueryClientProvider><RouterProvider router={router} /></QueryClientProvider>`.

- [ ] **Step 5: Components**

`src/components/Button.tsx`:
```tsx
// SPDX-License-Identifier: Apache-2.0
import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "danger";
const styles: Record<Variant, string> = {
  primary: "bg-accent text-white border-accent hover:bg-accent-ink",
  secondary: "bg-surface text-ink border-line-strong hover:bg-surface-2",
  danger: "bg-surface text-danger border-danger hover:bg-surface-2",
};

export function Button({ variant = "secondary", className = "", ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      {...rest}
      className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-4 text-sm font-medium disabled:opacity-50 ${styles[variant]} ${className}`}
    />
  );
}
```

`src/components/Field.tsx`:
```tsx
// SPDX-License-Identifier: Apache-2.0
import { useId, type InputHTMLAttributes, type ReactNode } from "react";

export function Field({ label, hint, error, ...input }:
  InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: ReactNode; error?: string }) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-semibold">{label}</label>
      <input id={id} {...input} aria-invalid={!!error} aria-describedby={error ? `${id}-err` : undefined}
        className="min-h-11 rounded-lg border border-line-strong bg-surface px-3 text-[15px]" />
      {hint && <p className="text-[13px] text-muted">{hint}</p>}
      {error && <p id={`${id}-err`} className="text-[13px] text-danger">{error}</p>}
    </div>
  );
}
```

`src/components/StatusBadge.tsx` renders `ok` → "Verified" (ok colours), `error` → "Failed: {detail}" (danger), and `unverified` → "Not verified" (muted), as a small bordered pill with text, not colour alone.

`src/components/Shell.tsx`: a 56px top bar with the wordmark "Dewpoint" (a 20px drop-outline SVG and text, no gradient), `TenantSwitcher`, a link to `/account/security` and a Sign out button (`POST /api/v1/auth/logout`, then clear the query cache and navigate to `/login`), plus a left rail with the links "Connections" and "Tenants". It renders `<Outlet />`.

`src/components/TenantSwitcher.tsx`: a Radix `DropdownMenu` listing `GET /api/v1/tenants` as `name · role`; choosing one navigates to `/t/{id}/connections`. Trigger `data-testid="tenant-switcher"`.

- [ ] **Step 6: Screens**

`src/routes/Login.tsx`:
```tsx
// SPDX-License-Identifier: Apache-2.0
import { useState, type FormEvent } from "react";
import { Button } from "../components/Button";
import { Field } from "../components/Field";
import { ApiError, api } from "../lib/api";
import { authenticatePasskey } from "../lib/webauthn";

const MESSAGES: Record<string, string> = {
  invalid_credentials: "Email or password is incorrect.",
  locked: "Too many attempts. Try again in a few minutes.",
  passkey_failed: "That passkey could not be verified.",
};

export function LoginForm({ onDone }: { onDone: (state: string) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<{ state: string }>) {
    setBusy(true);
    setError(null);
    try {
      onDone((await fn()).state);
    } catch (e) {
      setError(MESSAGES[e instanceof ApiError ? e.code : ""] ?? "Sign-in failed. Try again.");
    } finally {
      setBusy(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    void run(() => api("POST", "/api/v1/auth/login", { email, password }));
  }

  return (
    <form onSubmit={submit} className="flex w-full max-w-sm flex-col gap-4">
      <Field label="Email" type="email" autoComplete="username webauthn" required value={email}
        onChange={(e) => setEmail(e.target.value)} data-testid="login-email" />
      <Field label="Password" type="password" autoComplete="current-password" required value={password}
        onChange={(e) => setPassword(e.target.value)} data-testid="login-password" />
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <Button variant="primary" type="submit" disabled={busy} data-testid="login-submit">Sign in</Button>
      <Button type="button" disabled={busy} onClick={() => void run(() => authenticatePasskey("login"))}
        data-testid="login-passkey">Sign in with a passkey</Button>
    </form>
  );
}

export function LoginPage({ navigateByState }: { navigateByState: (s: string) => void }) {
  return (
    <main className="grid min-h-screen place-items-center px-4">
      <div className="flex w-full max-w-sm flex-col gap-6">
        <h1 className="text-2xl font-semibold">Sign in to Dewpoint</h1>
        <LoginForm onDone={navigateByState} />
      </div>
    </main>
  );
}
```
In `router.tsx`, define `navigateByState(state)`, mapping `mfa_pending` → `/mfa`, `enroll_required` → `/enroll`, and `active` → `/tenants`. It invalidates the `["session"]` query before navigating.

`src/routes/Mfa.tsx`: a code field (`data-testid="totp-code"`, `inputMode="numeric"`, `autoComplete="one-time-code"`) posting to `/api/v1/auth/mfa/totp`, with submit `totp-submit`. There's a "Use a passkey instead" button calling `authenticatePasskey("mfa")`, and a "Use a recovery code" toggle that switches the POST path to `/api/v1/auth/mfa/recovery`. Errors map `invalid_code` → "That code didn't work." and `locked` → the lockout message.

`src/routes/Enroll.tsx`, in two steps:
1. Choose a method: **Passkey (recommended)** calls `registerPasskey("This device")` and then `navigateByState`. **Authenticator app** calls `POST /api/v1/auth/mfa/totp/enroll`, renders the QR code with `QRCode.toDataURL(uri)` in an `<img alt="QR code for authenticator app">`, and shows the secret for manual entry in mono (`data-testid="totp-secret"`, parsed from the URI's `secret` query parameter). A code field (`totp-code`) and a confirm button (`totp-submit`) post to `/confirm`.
2. On success, show the 10 recovery codes in a mono grid (`data-testid="recovery-codes"`), with "Download .txt" (a Blob download) and a required checkbox "I saved these codes" (`recovery-ack`). "Continue" is enabled only once it's checked.

`src/routes/Tenants.tsx`: lists `GET /api/v1/tenants` as rows with name, slug (mono) and role. For platform admins, it adds a "Create tenant" form (`tenant-name`, `tenant-slug`, `tenant-create`) posting to `/api/v1/tenants`, and shows server errors (`slug_taken` → "That slug is already used.").

`src/routes/Security.tsx`: when an action returns 403 `reauth_required`, it prompts for a TOTP code (`POST /api/v1/auth/mfa/totp/reauth`) or a passkey (`authenticatePasskey("stepup")`), then retries. The change-password response carries the new `csrf_token`, which `api()` picks up automatically. The page shows the auth methods in use for this session, an "Add a passkey" button (`passkey-add`, name prompt defaulting to "Passkey") calling `registerPasskey`, "Set up authenticator app" (reusing the Enroll step-1 TOTP subcomponent, exported from `Enroll.tsx` as `TotpSetup`), and a change-password form posting `/api/v1/auth/password`.

`src/routes/Connections.tsx`:
```tsx
// SPDX-License-Identifier: Apache-2.0
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "../components/Button";
import { Field } from "../components/Field";
import { StatusBadge } from "../components/StatusBadge";
import { ApiError, api } from "../lib/api";

interface Conn {
  id: string; type: string; name: string; revision: number; config: { cloud: string; org_id: string };
  secret_set: boolean; status: "ok" | "error" | "unverified"; status_detail: string; privilege: string | null;
}
interface ConnType { key: string; label: string; clouds?: Record<string, string> }

export function ConnectionsPage({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const base = `/api/v1/t/${tenantId}/connections`;
  const list = useQuery({ queryKey: ["connections", tenantId], queryFn: () => api<Conn[]>("GET", base) });
  const types = useQuery({ queryKey: ["connection-types"], queryFn: () => api<ConnType[]>("GET", "/api/v1/connection-types") });
  const clouds = types.data?.find((t) => t.key === "mist")?.clouds ?? {};
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", cloud: "global_01", org_id: "", api_token: "" });
  const [error, setError] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["connections", tenantId] });

  const create = useMutation({
    mutationFn: () => api<Conn>("POST", base, {
      type: "mist", name: form.name, config: { cloud: form.cloud, org_id: form.org_id },
      secret: { api_token: form.api_token },
    }),
    onSuccess: async () => {
      setOpen(false);
      setForm({ name: "", cloud: "global_01", org_id: "", api_token: "" });
      await refresh();
    },
    onError: (e) => setError(e instanceof ApiError && e.code === "name_taken" ? "A connection with this name exists."
      : e instanceof ApiError && e.status === 403 ? "You don't have permission to manage connections."
      : "Check the fields and try again."),
  });
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const verify = useMutation({
    mutationFn: (id: string) => api<Conn>("POST", `${base}/${id}/verify`),
    onMutate: () => setVerifyError(null),
    onSuccess: refresh,
    onError: async (e) => {
      setVerifyError(
        e instanceof ApiError && e.code === "changed_during_verification"
          ? "The connection was edited while it was being verified. The result was discarded; verify again."
          : "Verification could not be completed.",
      );
      await refresh();
    },
  });

  return (
    <section className="flex flex-col gap-4 p-6">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Connections</h1>
        <Button variant="primary" onClick={() => setOpen(true)} data-testid="conn-add">Add Mist connection</Button>
      </header>
      {verifyError && <p role="alert" className="text-sm text-danger">{verifyError}</p>}
      <table className="w-full border-collapse rounded-lg border border-line bg-surface text-sm">
        <thead className="bg-surface-2 text-left text-muted">
          <tr><th className="p-3">Name</th><th className="p-3">Cloud</th><th className="p-3">Org ID</th>
            <th className="p-3">Status</th><th className="p-3"><span className="sr-only">Actions</span></th></tr>
        </thead>
        <tbody>
          {list.data?.map((c) => (
            <tr key={c.id} className="border-t border-line" data-testid="conn-row">
              <td className="p-3 font-medium">{c.name}</td>
              <td className="p-3 font-mono text-[13px]">{clouds[c.config.cloud] ?? c.config.cloud}</td>
              <td className="p-3 font-mono text-[13px]">{c.config.org_id}</td>
              <td className="p-3"><StatusBadge status={c.status} detail={c.status_detail} privilege={c.privilege} /></td>
              <td className="p-3 text-right">
                <Button onClick={() => verify.mutate(c.id)} disabled={verify.isPending}>Verify</Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {open && (
        <form role="dialog" aria-label="Add Mist connection" className="flex max-w-lg flex-col gap-4 rounded-lg border border-line bg-surface p-5"
          onSubmit={(e) => { e.preventDefault(); setError(null); create.mutate(); }}>
          <Field label="Name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="conn-name" />
          <div className="flex flex-col gap-1.5">
            <label htmlFor="cloud" className="text-sm font-semibold">Mist cloud</label>
            <select id="cloud" className="min-h-11 rounded-lg border border-line-strong bg-surface px-3" value={form.cloud}
              onChange={(e) => setForm({ ...form, cloud: e.target.value })} data-testid="conn-cloud">
              {Object.entries(clouds).map(([k, host]) => <option key={k} value={k}>{host}</option>)}
            </select>
          </div>
          <Field label="Organization ID" required pattern="[0-9a-fA-F-]{36}" value={form.org_id}
            onChange={(e) => setForm({ ...form, org_id: e.target.value })} data-testid="conn-org" />
          <Field label="API token" type="password" autoComplete="off" required value={form.api_token}
            hint="Stored encrypted. It is never shown again." onChange={(e) => setForm({ ...form, api_token: e.target.value })}
            data-testid="conn-token" />
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          <div className="flex gap-2">
            <Button variant="primary" type="submit" disabled={create.isPending} data-testid="conn-save">Save</Button>
            <Button type="button" onClick={() => setOpen(false)}>Cancel</Button>
          </div>
        </form>
      )}
    </section>
  );
}
```

`src/router.tsx`: code-based TanStack Router routes. The root layout checks `useSession()`:
- no session → `/login`;
- `mfa_pending` → `/mfa`;
- `enroll_required` → `/enroll`.

Authenticated routes render inside `Shell`. `/t/$tenantId/connections` passes `tenantId` to `ConnectionsPage`. On 403 `step_up_required` (from any query), it shows an inline banner, "This tenant requires a passkey," with a button calling `authenticatePasskey("stepup")` and then invalidating all queries.

**Sign-out:** `lib/signOut.ts` (tested in `signOut.test.ts`) reports success only on exactly 204, checked through `request()`, which returns the status; any other 2xx counts as a failure. A 401 also counts as signed out, because the session is already invalid. It refreshes a stale CSRF token from `/auth/session` once and retries. On any other failure, including a network error, the shell keeps the user on the page and shows an error, because the server session may still be valid.

**As built:** the screens described in prose above are implemented in `frontend/src/`:
- `components/{StatusBadge,TenantSwitcher,Shell}.tsx`
- `routes/{Mfa,Enroll,Tenants,Security}.tsx`
- `router.tsx`, `main.tsx`
- `lib/{events,reauth,useAfterAuth}.ts`: the step-up signal, the `reauth_required` check, and routing by session state

`TotpSetup` takes an `onReauth(retry)` callback, and Security's `ReauthPrompt` re-proves a factor and then retries the action. Tooling changes found during implementation:
- `vitest ^3.2.7`, because vitest 2 pins Vite 5 and clashes with Vite 6 types;
- `pnpm-workspace.yaml` with `allowBuilds: { esbuild: true }`, since pnpm 12 blocks dependency build scripts unless they are approved one package at a time;
- the ESLint config allows its own JS file and disables type-aware rules for `*.js`;
- the Login test asserts `textContent` rather than adding `@testing-library/jest-dom`.

The backend `GET /api/v1/auth/passkeys` (moved here from Task 14, because the Security page needs it) returns `[{id,name,created_at,last_used_at}]` for the active session. It's tested in `test_passkey_routes.py::test_list_own_passkeys_without_key_material`.

- [ ] **Step 7: Run the checks**

Run: `cd frontend && P='npx pnpm@12.6.0' && $P lint && $P typecheck && $P test && $P build`
Expected: all pass. `dist/` builds.

- [ ] **Step 8: Add CI for the frontend**

Append this to `.github/workflows/ci.yml`:
```yaml
  frontend:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: frontend } }
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@b906affcce14559ad1aafd4ab0e942779e9f58b1 # v4  (version comes from package.json "packageManager")
        with: { package_json_file: frontend/package.json }
      - uses: actions/setup-node@v4
        with: { node-version: 22, cache: pnpm, cache-dependency-path: frontend/pnpm-lock.yaml }
      - run: pnpm install --frozen-lockfile
      - run: pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "feat(web): shell with tokens, sign-in, MFA, enrollment, passkeys, tenants and connections

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 14: Readiness probe, container images, Docker Compose, end-to-end tests, signed releases

**Files:**
- Modify: `backend/src/dewpoint/apps/api/routes/health.py` (add `/health/ready`)
- Create: `deploy/docker/app.Dockerfile`, `deploy/docker/web.Dockerfile`, `deploy/docker/nginx.conf`
- Create: `deploy/compose/docker-compose.yml`, `deploy/compose/.env.example`, `deploy/compose/initdb/10-roles.sh`
- Create: `frontend/playwright.config.ts`, `frontend/e2e/foundations.spec.ts`
- Create: `.github/workflows/release.yml`
- Modify: `.github/workflows/ci.yml` (add the `e2e` job)
- Modify: `README.md` (quick start)
- Test: `backend/tests/apps/api/test_ready.py`, `frontend/e2e/foundations.spec.ts`

**Interfaces:**
- Consumes: everything in Tasks 1–13.
- Produces:
  - `GET /health/ready` → `200 {"status":"ready"}`, or `503 {"status":"unavailable"}` when the DB is unreachable.
  - The images `ghcr.io/<org>/dewpoint-app` and `ghcr.io/<org>/dewpoint-web`.
  - A Compose stack reachable at `http://localhost:8080`.

**Base image note:** the spec asks for distroless, non-root images. At the time of writing, no distroless image ships Python 3.12+ on a supported Debian release, so `app` uses `python:3.12-slim-bookworm`: non-root UID 10001, no build tools, run with a read-only filesystem. Revisit this when a distroless 3.12+ image is available. `web` uses `nginxinc/nginx-unprivileged`.

- [ ] **Step 1: Readiness test and route**

`backend/tests/apps/api/test_ready.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import httpx

from dewpoint.apps.api.main import create_app
from dewpoint.core.config import Settings


async def test_ready_ok(client) -> None:
    r = await client.get("/health/ready")
    assert r.status_code == 200 and r.json() == {"status": "ready"}


async def test_ready_unavailable() -> None:
    app = create_app(Settings(database_url="postgresql+asyncpg://u:p@127.0.0.1:1/x", kek_b64="A" * 43 + "=",
                              public_origin="https://testserver"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as c:
        r = await c.get("/health/ready")
    assert r.status_code == 503 and r.json() == {"status": "unavailable"}
```
Add to `routes/health.py`:
```python
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import text


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    try:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("select 1"))
    except Exception:  # noqa: BLE001 - any failure means not ready; never leak details
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ready"})
```
Run: `uv run pytest tests/apps/api/test_ready.py -v`
Expected: PASS

- [ ] **Step 2: Images**

`deploy/docker/app.Dockerfile`:
```dockerfile
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
```
`--forwarded-allow-ips "*"` is acceptable **only** because `api` is not published and is reachable solely through `web` on the internal network. The Helm chart (sub-project 4) sets the exact proxy CIDRs. Put this sentence in a comment above the CMD.

`deploy/docker/nginx.conf`:
```nginx
server {
  listen 8080;
  server_tokens off;
  root /usr/share/nginx/html;
  client_max_body_size 6m;
  # Re-resolve the api service through Docker's DNS: a static upstream keeps a dead container IP after the api
  # is restarted or redeployed (502 until web restarts). A variable in proxy_pass forces per-TTL resolution.
  resolver 127.0.0.11 valid=10s ipv6=off;
  set $api http://api:8000;

  location /api/ {
    proxy_pass $api;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;   # overwrite, never append client-supplied values
    proxy_set_header X-Forwarded-Proto $scheme;
  }
  location /health/ { proxy_pass $api; }
  location /assets/ {
    include /etc/nginx/snippets/security-headers.conf;
    add_header Cache-Control "public, immutable" always;
    expires 1y;
    try_files $uri =404;
  }
  location / {
    include /etc/nginx/snippets/security-headers.conf;
    add_header Cache-Control "no-store" always;
    try_files $uri /index.html;
  }
}
```

`deploy/docker/security-headers.conf` (included by the static locations; nginx ignores server-level `add_header` in any location that sets its own):
```nginx
# Included by every static location. nginx drops server-level add_header in any location that
# declares its own add_header, so these can't live at server level. /api responses carry the
# same headers from the API itself.
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'" always;
add_header X-Content-Type-Options nosniff always;
add_header Referrer-Policy no-referrer always;
add_header X-Frame-Options DENY always;
```

`deploy/docker/web.Dockerfile`:
```dockerfile
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

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY deploy/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/docker/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 8080
```

- [ ] **Step 3: Compose**

`deploy/compose/initdb/10-roles.sh` (runs once when the DB volume is created; group roles are idempotent with migration 0001):
```bash
#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v api_pw="$DEWPOINT_API_DB_PASSWORD" -v admin_pw="$DEWPOINT_ADMIN_DB_PASSWORD" \
  -v auditor_pw="$DEWPOINT_AUDITOR_DB_PASSWORD" <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_api') THEN CREATE ROLE dewpoint_api NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_admin') THEN CREATE ROLE dewpoint_admin NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_auditor') THEN CREATE ROLE dewpoint_auditor NOLOGIN; END IF;
END $$;
CREATE ROLE dewpoint_api_login LOGIN PASSWORD :'api_pw' IN ROLE dewpoint_api;
CREATE ROLE dewpoint_admin_login LOGIN PASSWORD :'admin_pw' IN ROLE dewpoint_admin;
CREATE ROLE dewpoint_auditor_login LOGIN PASSWORD :'auditor_pw' IN ROLE dewpoint_auditor;
SQL
```

`deploy/compose/docker-compose.yml`:
```yaml
# SPDX-License-Identifier: Apache-2.0
name: dewpoint
x-app: &app
  image: ${DEWPOINT_APP_IMAGE:-dewpoint-app:dev}
  build: { context: ../.., dockerfile: deploy/docker/app.Dockerfile }
  read_only: true
  tmpfs: [/tmp]
  security_opt: ["no-new-privileges:true"]
  cap_drop: [ALL]
  environment: &appenv
    DEWPOINT_KEK_B64: ${DEWPOINT_KEK_B64:?set in .env}
    DEWPOINT_KEK_ID: ${DEWPOINT_KEK_ID:-env-1}
    # Set only during a KEK rollout: docs/operations/key-rotation.md
    DEWPOINT_KEK_PREVIOUS_B64: ${DEWPOINT_KEK_PREVIOUS_B64:-}
    DEWPOINT_KEK_PREVIOUS_ID: ${DEWPOINT_KEK_PREVIOUS_ID:-}
    DEWPOINT_PUBLIC_ORIGIN: ${DEWPOINT_PUBLIC_ORIGIN:-http://localhost:8080}
    DEWPOINT_RP_ID: ${DEWPOINT_RP_ID:-localhost}

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: dewpoint
      POSTGRES_USER: dewpoint_owner
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set in .env}
      DEWPOINT_API_DB_PASSWORD: ${DEWPOINT_API_DB_PASSWORD:?set in .env}
      DEWPOINT_ADMIN_DB_PASSWORD: ${DEWPOINT_ADMIN_DB_PASSWORD:?set in .env}
      DEWPOINT_AUDITOR_DB_PASSWORD: ${DEWPOINT_AUDITOR_DB_PASSWORD:?set in .env}
    volumes: [pgdata:/var/lib/postgresql/data, ./initdb:/docker-entrypoint-initdb.d:ro]
    healthcheck: { test: ["CMD-SHELL", "pg_isready -U dewpoint_owner -d dewpoint"], interval: 5s, retries: 20 }

  migrate:
    <<: *app
    command: ["alembic", "upgrade", "head"]
    environment:
      <<: *appenv
      DEWPOINT_DATABASE_URL: postgresql+asyncpg://dewpoint_owner:${POSTGRES_PASSWORD}@postgres/dewpoint
    depends_on: { postgres: { condition: service_healthy } }
    restart: "no"

  api:
    <<: *app
    environment:
      <<: *appenv
      DEWPOINT_DATABASE_URL: postgresql+asyncpg://dewpoint_api_login:${DEWPOINT_API_DB_PASSWORD}@postgres/dewpoint
    depends_on: { migrate: { condition: service_completed_successfully } }
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready').status==200 else 1)"]
      interval: 5s
      retries: 20

  audit-anchor:
    <<: *app
    # Anchors belong OFF this host in production (object lock / SIEM). This volume is for evaluation only.
    # set -e: a failed anchor run ends the container with a nonzero exit (visible in `docker compose ps -a`),
    # instead of looping silently without producing anchors.
    command: ["sh", "-c", "set -e; while true; do dewpoint audit anchor; sleep 900; done"]
    restart: "no"
    # Unhealthy when audit rows older than 30 minutes have no anchor (job stuck, failing, or anchors stale).
    # Alert on this in your monitoring as well.
    healthcheck:
      test: ["CMD", "dewpoint", "audit", "freshness", "--max-age-minutes", "30"]
      interval: 5m
      timeout: 30s
      start_period: 1m
      start_interval: 5s
      retries: 1
    environment:
      <<: *appenv
      DEWPOINT_DATABASE_URL: postgresql+asyncpg://dewpoint_auditor_login:${DEWPOINT_AUDITOR_DB_PASSWORD}@postgres/dewpoint
      DEWPOINT_AUDIT_SIGNING_KEY_B64: ${DEWPOINT_AUDIT_SIGNING_KEY_B64:?set in .env}
      DEWPOINT_AUDIT_ANCHOR_PATH: /anchors/anchors.jsonl
    volumes: [anchors:/anchors]
    depends_on: { migrate: { condition: service_completed_successfully } }

  web:
    image: ${DEWPOINT_WEB_IMAGE:-dewpoint-web:dev}
    build: { context: ../.., dockerfile: deploy/docker/web.Dockerfile }
    read_only: true
    tmpfs: [/tmp, /var/cache/nginx]
    cap_drop: [ALL]
    ports: ["127.0.0.1:8080:8080"]
    depends_on: { api: { condition: service_healthy } }

volumes: { pgdata: {}, anchors: {} }
```
The `anchors` volume must be writable by UID 10001. The app image creates `/anchors` owned by 10001, and a new named volume inherits that ownership, so no manual `chown` is needed.

`deploy/compose/.env.example`:
```bash
# Generate each secret; never commit the filled .env.
POSTGRES_PASSWORD=            # openssl rand -base64 24
DEWPOINT_API_DB_PASSWORD=     # openssl rand -base64 24
DEWPOINT_ADMIN_DB_PASSWORD=   # openssl rand -base64 24  (key-management CLI: dewpoint keys …)
DEWPOINT_AUDITOR_DB_PASSWORD= # openssl rand -base64 24  (audit anchor/verify only)
DEWPOINT_KEK_B64=             # openssl rand -base64 32
DEWPOINT_AUDIT_SIGNING_KEY_B64=  # python -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"
DEWPOINT_PUBLIC_ORIGIN=http://localhost:8080
DEWPOINT_RP_ID=localhost
```
**Non-localhost deployments:** `__Host-` cookies and WebAuthn require HTTPS outside `localhost`. Terminate TLS in front of `web` and set `DEWPOINT_PUBLIC_ORIGIN=https://…` and `DEWPOINT_RP_ID` to the hostname. Write this in the README quick start.

- [ ] **Step 4: Bring up the stack locally**

```bash
cd deploy/compose && cp .env.example .env   # fill values
set -a; . ./.env; set +a
docker compose up -d --build --wait
docker compose run --rm -e DEWPOINT_INIT_PASSWORD='violet-otter-canyon-42' \
  -e DEWPOINT_DATABASE_URL="postgresql+asyncpg://dewpoint_api_login:${DEWPOINT_API_DB_PASSWORD}@postgres/dewpoint" \
  api dewpoint admin init --email admin@example.com
curl -fsS http://localhost:8080/health/ready
```
Expected: `{"status":"ready"}`, and the admin init prints `platform admin admin@example.com created`.

- [ ] **Step 5: Write the end-to-end tests**

`frontend/playwright.config.ts`:
```ts
// SPDX-License-Identifier: Apache-2.0
import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "e2e",
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
```

`frontend/e2e/foundations.spec.ts`:
```ts
// SPDX-License-Identifier: Apache-2.0
import { expect, test, type Page } from "@playwright/test";
import * as OTPAuth from "otpauth";

const EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@example.com";
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "violet-otter-canyon-42";
let totpSecret = "";

function code(secret: string, offsetSeconds = 0): string {
  return new OTPAuth.TOTP({ secret: OTPAuth.Secret.fromBase32(secret) }).generate({ timestamp: Date.now() + offsetSeconds * 1000 });
}

async function passwordLogin(page: Page) {
  await page.goto("/login");
  await page.getByTestId("login-email").fill(EMAIL);
  await page.getByTestId("login-password").fill(PASSWORD);
  await page.getByTestId("login-submit").click();
}

test.describe.serial("foundations", () => {
  test("first login enrolls TOTP, creates a tenant and a Mist connection", async ({ page }) => {
    await passwordLogin(page);
    await expect(page).toHaveURL(/\/enroll/);
    await page.getByRole("button", { name: "Authenticator app" }).click();
    totpSecret = (await page.getByTestId("totp-secret").textContent())!.replace(/\s/g, "");
    await page.getByTestId("totp-code").fill(code(totpSecret));
    await page.getByTestId("totp-submit").click();
    await expect(page.getByTestId("recovery-codes")).toBeVisible();
    await page.getByTestId("recovery-ack").check();
    await page.getByRole("button", { name: "Continue" }).click();

    await expect(page).toHaveURL(/\/tenants/);
    await page.getByTestId("tenant-name").fill("Acme Retail");
    await page.getByTestId("tenant-slug").fill("acme-retail");
    await page.getByTestId("tenant-create").click();
    await page.getByTestId("tenant-switcher").click();
    await page.getByRole("menuitem", { name: /Acme Retail/ }).click();

    await page.getByTestId("conn-add").click();
    await page.getByTestId("conn-name").fill("Acme Prod");
    await page.getByTestId("conn-cloud").selectOption("emea_01");
    await page.getByTestId("conn-org").fill("6a1f6c34-6e8e-4b35-9a4c-1f0b8f1f2c11");
    await page.getByTestId("conn-token").fill("tok_" + "a".repeat(36));
    await page.getByTestId("conn-save").click();
    const row = page.getByTestId("conn-row").filter({ hasText: "Acme Prod" });
    await expect(row).toContainText("api.eu.mist.com");
    await expect(row).toContainText("Not verified");
    await expect(page.locator("body")).not.toContainText("tok_");
  });

  test("passkey added with a virtual authenticator signs in without a password", async ({ page }) => {
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("WebAuthn.enable");
    await cdp.send("WebAuthn.addVirtualAuthenticator", {
      options: { protocol: "ctap2", transport: "internal", hasResidentKey: true, hasUserVerification: true,
                 isUserVerified: true },
    });
    await passwordLogin(page);
    await expect(page).toHaveURL(/\/mfa/);
    await page.getByTestId("totp-code").fill(code(totpSecret, 30)); // next step: the current one was consumed
    await page.getByTestId("totp-submit").click();
    await expect(page).toHaveURL(/\/tenants/); // wait: the MFA response rotates the session cookie
    await page.goto("/account/security");
    page.once("dialog", (d) => void d.accept("E2E key"));
    await page.getByTestId("passkey-add").click();
    await expect(page.getByText("E2E key")).toBeVisible();
    await page.getByRole("button", { name: "Sign out" }).click();

    await page.goto("/login");
    await page.getByTestId("login-passkey").click();
    await expect(page).toHaveURL(/\/tenants/);
  });
});
```
`Security.tsx` lists the user's passkeys by name, which the `E2E key` assertion relies on. The backend `GET /api/v1/auth/passkeys` was built in Task 13.

- [ ] **Step 6: Run the end-to-end tests locally**

Run: `cd frontend && npx pnpm@12.6.0 exec playwright install chromium && npx pnpm@12.6.0 e2e`
Expected: 2 passed. (Reset the stack with `docker compose down -v` before re-running, because enrollment happens once per fresh admin.)

- [ ] **Step 7: CI end-to-end job and signed releases**

Append to `.github/workflows/ci.yml`:
```yaml
  e2e:
    runs-on: ubuntu-latest
    needs: [backend, frontend]
    steps:
      - uses: actions/checkout@v4
      - name: Write CI env
        working-directory: deploy/compose
        run: |
          {
            echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)"
            echo "DEWPOINT_API_DB_PASSWORD=$(openssl rand -hex 16)"
            echo "DEWPOINT_ADMIN_DB_PASSWORD=$(openssl rand -hex 16)"
            echo "DEWPOINT_AUDITOR_DB_PASSWORD=$(openssl rand -hex 16)"
            echo "DEWPOINT_KEK_B64=$(openssl rand -base64 32)"
            echo "DEWPOINT_AUDIT_SIGNING_KEY_B64=$(openssl rand -base64 32)"
          } > .env
      - working-directory: deploy/compose
        run: |
          docker compose up -d --build --wait
          set -a; . ./.env; set +a
          docker compose run --rm -e DEWPOINT_INIT_PASSWORD=violet-otter-canyon-42 \
            -e DEWPOINT_DATABASE_URL="postgresql+asyncpg://dewpoint_api_login:${DEWPOINT_API_DB_PASSWORD}@postgres/dewpoint" \
            api dewpoint admin init --email admin@example.com
      - uses: pnpm/action-setup@b906affcce14559ad1aafd4ab0e942779e9f58b1 # v4  (version comes from package.json "packageManager")
        with: { package_json_file: frontend/package.json }
      - uses: actions/setup-node@v4
        with: { node-version: 22, cache: pnpm, cache-dependency-path: frontend/pnpm-lock.yaml }
      - working-directory: frontend
        run: pnpm install --frozen-lockfile && pnpm exec playwright install --with-deps chromium && pnpm e2e
      - if: failure()
        working-directory: deploy/compose
        run: docker compose logs --no-color > compose.log
      - if: failure()
        uses: actions/upload-artifact@v4
        with: { name: e2e-debug, path: "frontend/playwright-report\ndeploy/compose/compose.log" }
```

`.github/workflows/release.yml` (on tags `v*`; a dry run on PRs that touch the release path: build, load and scan locally, with no push or signing; image references lowercased because registries reject an uppercase owner):
```yaml
name: release
on:
  push: { tags: ["v*"] }
  # Dry run on changes to the release path: build + scan locally, no login/push/sign.
  pull_request: { paths: [".github/workflows/release.yml", "deploy/docker/**"] }
permissions: { contents: read, packages: write, id-token: write, attestations: write }
jobs:
  images:
    runs-on: ubuntu-latest
    strategy: { matrix: { image: [app, web] } }
    env:
      RELEASE: ${{ github.event_name == 'push' }}
    steps:
      - uses: actions/checkout@v4
      # Registry repository names must be lowercase; the owner (e.g. "tmunzer-AIDE") may not be.
      - id: image
        run: |
          owner="$(printf '%s' "${GITHUB_REPOSITORY_OWNER}" | tr '[:upper:]' '[:lower:]')"
          echo "ref=ghcr.io/${owner}/dewpoint-${{ matrix.image }}" >> "$GITHUB_OUTPUT"
          echo "tag=${{ github.event_name == 'push' && github.ref_name || 'dryrun' }}" >> "$GITHUB_OUTPUT"
      - uses: docker/setup-buildx-action@8d2750c68a42422c14e847fe6c8ac0403b4cbd6f # v3
      - if: env.RELEASE == 'true'
        uses: docker/login-action@c94ce9fb468520275223c153574b00df6fe4bcc9 # v3
        with: { registry: ghcr.io, username: "${{ github.actor }}", password: "${{ secrets.GITHUB_TOKEN }}" }
      - id: build
        uses: docker/build-push-action@10e90e3645eae34f1e60eeb005ba3a3d33f178e8 # v6
        with:
          context: .
          file: deploy/docker/${{ matrix.image }}.Dockerfile
          tags: ${{ steps.image.outputs.ref }}:${{ steps.image.outputs.tag }}
          push: ${{ env.RELEASE == 'true' }}
          load: ${{ env.RELEASE != 'true' }}
          # Attestations need a registry push; the local docker exporter can't store them.
          provenance: ${{ env.RELEASE == 'true' && 'mode=max' || 'false' }}
          sbom: ${{ env.RELEASE == 'true' }}
      - if: env.RELEASE == 'true'
        uses: anchore/sbom-action@e22c389904149dbc22b58101806040fa8d37a610 # v0
        with:
          image: ${{ steps.image.outputs.ref }}@${{ steps.build.outputs.digest }}
          format: cyclonedx-json
          output-file: sbom-${{ matrix.image }}.cdx.json
      - if: env.RELEASE == 'true'
        uses: sigstore/cosign-installer@398d4b0eeef1380460a10c8013a76f728fb906ac # v3
      - if: env.RELEASE == 'true'
        run: cosign sign --yes "${{ steps.image.outputs.ref }}@${{ steps.build.outputs.digest }}"
      - if: env.RELEASE == 'true'
        run: >-
          cosign attest --yes --type cyclonedx --predicate "sbom-${{ matrix.image }}.cdx.json"
          "${{ steps.image.outputs.ref }}@${{ steps.build.outputs.digest }}"
      - uses: aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25 # v0.36.0
        with:
          image-ref: >-
            ${{ env.RELEASE == 'true'
              && format('{0}@{1}', steps.image.outputs.ref, steps.build.outputs.digest)
              || format('{0}:{1}', steps.image.outputs.ref, steps.image.outputs.tag) }}
          severity: HIGH,CRITICAL
          ignore-unfixed: true  # fail on vulnerabilities that have a fix available
          exit-code: "1"
```

- [ ] **Step 8: README quick start**

Add to `README.md`:
- what Dewpoint is (one paragraph);
- a status line ("Foundations: sign-in, tenants, Mist connections. Workflows arrive in the next milestone.");
- the quick start from Step 4;
- the HTTPS requirement for non-localhost deployments;
- key generation;
- `dewpoint audit verify` usage, and the reminder to keep anchors off-host;
- links to `SECURITY.md` and `CONTRIBUTING.md`.

- [ ] **Step 9: Final verification and commit**

Run:
```bash
cd backend && uv run ruff check . && uv run mypy src && uv run lint-imports && uv run pytest -q
cd ../frontend && npx pnpm@12.6.0 lint && npx pnpm@12.6.0 typecheck && npx pnpm@12.6.0 test
```
Expected: all green. The end-to-end run from Step 6 has passed.

```bash
git add -A && git commit -m "feat(deploy): readiness probe, hardened images, compose stack, e2e with virtual passkey, signed releases

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Key-management commands and the KEK rollout runbook

**Files:**
- Modify: `backend/src/dewpoint/apps/cli/main.py` (add the `keys` command group)
- Create: `docs/operations/key-rotation.md`
- Test: `backend/tests/apps/cli/test_keys.py`

**Interfaces:**
- Consumes: `KekSet`, `Keyring.rewrap_batch`, `Keyring.kek_usage`, `Keyring.rotate` (Task 5); `get_settings` (Task 2).
- Produces:
  - `dewpoint keys status`: prints `kek_id=count` per line. Exit code 3 if any data key uses a KEK id that isn't in the configured `KekSet` (that process couldn't decrypt it).
  - `dewpoint keys rewrap [--batch-size 100]`: commits after **each** batch so locks stay short, and prints the total. It refuses (exit 2) unless a previous KEK is configured *and* the current KEK differs from it.
  - `dewpoint keys rotate-dek (--tenant UUID | --platform)`: data-key rotation. Old versions stay readable, and new encryptions use the new version.
  - Commands run as a `dewpoint_admin` login.

- [ ] **Step 1: Write the failing tests**

`backend/tests/apps/cli/test_keys.py`:
```python
# SPDX-License-Identifier: Apache-2.0
import base64
import os
import uuid

from typer.testing import CliRunner

from dewpoint.apps.cli.main import app
from dewpoint.core.config import get_settings

OLD, NEW = base64.b64encode(os.urandom(32)).decode(), base64.b64encode(os.urandom(32)).decode()


def _env(monkeypatch, pg_url: str, **kek: str) -> None:
    for k, v in {"DEWPOINT_DATABASE_URL": pg_url, "DEWPOINT_PUBLIC_ORIGIN": "https://dewpoint.test", **kek}.items():
        monkeypatch.setenv(k, v)
    for k in ("DEWPOINT_KEK_PREVIOUS_B64", "DEWPOINT_KEK_PREVIOUS_ID"):
        if k not in kek:
            monkeypatch.delenv(k, raising=False)
    get_settings.cache_clear()


def test_status_rewrap_and_rotate(pg_url, monkeypatch) -> None:
    r = CliRunner()
    _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=OLD, DEWPOINT_KEK_ID="old")
    t = str(uuid.uuid4())
    assert r.invoke(app, ["keys", "rotate-dek", "--tenant", t]).exit_code == 0  # creates v1 then v2 under "old"
    assert "old=2" in r.invoke(app, ["keys", "status"]).output
    assert r.invoke(app, ["keys", "rewrap"]).exit_code == 2  # no previous key configured: refuse

    _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=NEW, DEWPOINT_KEK_ID="new")  # misconfigured: old key dropped too early
    assert r.invoke(app, ["keys", "status"]).exit_code == 3

    _env(
        monkeypatch,
        pg_url,
        DEWPOINT_KEK_B64=NEW,
        DEWPOINT_KEK_ID="new",
        DEWPOINT_KEK_PREVIOUS_B64=OLD,
        DEWPOINT_KEK_PREVIOUS_ID="old",
    )
    out = r.invoke(app, ["keys", "rewrap", "--batch-size", "1"])
    assert out.exit_code == 0 and "rewrapped 2" in out.output
    status = r.invoke(app, ["keys", "status"])
    assert status.exit_code == 0 and "new=2" in status.output and "old=" not in status.output


def test_key_commands_work_as_the_admin_role(pg_url, _test_users, monkeypatch) -> None:
    """Production runs these as dewpoint_admin: RLS key-admin policy on data_keys + grants on platform_keys."""
    from tests.conftest import _url_for

    admin = _url_for(pg_url, "dewpoint_admin")
    r = CliRunner()
    _env(monkeypatch, admin, DEWPOINT_KEK_B64=OLD, DEWPOINT_KEK_ID="old")
    t1, t2 = str(uuid.uuid4()), str(uuid.uuid4())
    for args in (["--tenant", t1], ["--tenant", t2], ["--platform"]):
        out = r.invoke(app, ["keys", "rotate-dek", *args])
        assert out.exit_code == 0 and "version: 2" in out.output, out.output
    assert "old=6" in r.invoke(app, ["keys", "status"]).output  # tenant keys from two tenants + platform

    _env(
        monkeypatch,
        admin,
        DEWPOINT_KEK_B64=NEW,
        DEWPOINT_KEK_ID="new",
        DEWPOINT_KEK_PREVIOUS_B64=OLD,
        DEWPOINT_KEK_PREVIOUS_ID="old",
    )
    assert "rewrapped 6" in r.invoke(app, ["keys", "rewrap", "--batch-size", "4"]).output
    assert r.invoke(app, ["keys", "status"]).output.strip() == "new=6"
    assert r.invoke(app, ["keys", "rotate-dek", "--tenant", "not-a-uuid"]).exit_code == 2
```
`rotate-dek` on a scope with no key yet creates version 1 through `_active()` and then rotates to 2. That's intended, and the test relies on it.

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `uv run pytest tests/apps/cli/test_keys.py -v`
Expected: FAIL (`No such command 'keys'`)

- [ ] **Step 3: Implement the commands**

The full `apps/cli/main.py` after this task (module-level imports, and a typed `_in_session` helper instead of the draft's inline imports). It is also tested as the `dewpoint_admin` role in `test_key_commands_work_as_the_admin_role`: tenant and platform keys, batched rewrap, and a rejected invalid tenant id:
```python
# SPDX-License-Identifier: Apache-2.0
import asyncio
import base64
import os
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

import typer
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit.anchor import FileAnchorSink, anchor_all, verify_anchors
from dewpoint.core.auth.users import PasswordPolicyError, create_user
from dewpoint.core.config import get_settings
from dewpoint.core.crypto.kek import KekSet, UnknownKekError
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import make_engine, make_sessionmaker
from dewpoint.core.models.identity import User

app = typer.Typer(no_args_is_help=True)
admin = typer.Typer(no_args_is_help=True)
app.add_typer(admin, name="admin")
audit = typer.Typer(no_args_is_help=True)
app.add_typer(audit, name="audit")
keys = typer.Typer(no_args_is_help=True)
app.add_typer(keys, name="keys")


async def _init(email: str, password: str) -> None:
    engine = make_engine(get_settings().database_url)
    try:
        async with make_sessionmaker(engine)() as s, s.begin():
            if (await s.execute(select(User.id).where(User.is_platform_admin.is_(True)).limit(1))).first():
                typer.echo("already initialized: a platform admin exists")
                raise typer.Exit(1)
            await create_user(s, email=email, password=password, platform_admin=True)
    finally:
        await engine.dispose()


@admin.command("init")
def admin_init(email: str = typer.Option(...)) -> None:
    """Create the first platform admin. Refuses if one already exists."""
    password = os.environ.get("DEWPOINT_INIT_PASSWORD") or typer.prompt(
        "Password", hide_input=True, confirmation_prompt=True
    )
    try:
        asyncio.run(_init(email, password))
    except PasswordPolicyError as e:
        typer.echo(f"password rejected: {', '.join(e.violations)}")
        raise typer.Exit(2) from None
    typer.echo(f"platform admin {email} created. Sign in to enroll MFA.")


def _signing_key() -> Ed25519PrivateKey:
    raw = get_settings().audit_signing_key_b64
    if not raw:
        typer.echo("DEWPOINT_AUDIT_SIGNING_KEY_B64 is not set")
        raise typer.Exit(2)
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(raw))


def _anchor_path() -> Path:
    path = get_settings().audit_anchor_path
    if not path:
        typer.echo("DEWPOINT_AUDIT_ANCHOR_PATH is not set")
        raise typer.Exit(2)
    return Path(path)


@audit.command("anchor")
def audit_anchor() -> None:
    """Write current chain heads to the external anchor sink. Run as a dewpoint_auditor login, e.g. every 15 min."""
    sink = FileAnchorSink(_anchor_path(), _signing_key())

    async def _run() -> int:
        engine = make_engine(get_settings().database_url)
        try:
            async with make_sessionmaker(engine)() as s, s.begin():
                return await anchor_all(s, sink)
        finally:
            await engine.dispose()

    typer.echo(f"anchored {asyncio.run(_run())} scope head(s)")


@audit.command("verify")
def audit_verify() -> None:
    """Recompute every chain and check it against the signed external anchors. Exit 1 on any problem,
    including when no anchors exist, so a broken anchor job can't look healthy."""
    key = _signing_key()
    sink = FileAnchorSink(_anchor_path(), key)

    async def _run() -> list[str]:
        engine = make_engine(get_settings().database_url)
        try:
            async with make_sessionmaker(engine)() as s:
                return await verify_anchors(s, sink.entries(), key.public_key())
        finally:
            await engine.dispose()

    problems = asyncio.run(_run())
    for problem in problems:
        typer.echo(problem)
    if problems:
        raise typer.Exit(1)
    typer.echo("audit chain verified against external anchors")


async def _in_session[T](fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
    engine = make_engine(get_settings().database_url)
    try:
        async with make_sessionmaker(engine)() as s:
            return await fn(s)
    finally:
        await engine.dispose()


@keys.command("status")
def keys_status() -> None:
    """Data keys per KEK id. Exit 3 if any are wrapped by a KEK this configuration lacks. Run as dewpoint_admin."""
    keks = KekSet.from_settings(get_settings())
    usage = asyncio.run(_in_session(Keyring(keks).kek_usage))
    missing = []
    for kek_id, n in sorted(usage.items()):
        typer.echo(f"{kek_id}={n}")
        try:
            keks.get(kek_id)
        except UnknownKekError:
            missing.append(kek_id)
    if missing:
        typer.echo(f"ERROR: no configured key for: {', '.join(missing)}. Do not remove a KEK before rewrap completes.")
        raise typer.Exit(3)


@keys.command("rewrap")
def keys_rewrap(batch_size: int = typer.Option(100, min=1, max=1000)) -> None:
    """Phase C of docs/operations/key-rotation.md: move every data key to the current KEK, in committed batches."""
    st = get_settings()
    if not st.kek_previous_b64 or st.kek_previous_id == st.kek_id:
        typer.echo("refusing: configure the new KEK as current and the old one as previous first (phase B)")
        raise typer.Exit(2)
    keyring = Keyring(KekSet.from_settings(st))

    async def _run(s: AsyncSession) -> int:
        total = 0
        while True:
            async with s.begin():
                n = await keyring.rewrap_batch(s, batch_size)
            total += n
            if n == 0:
                return total

    typer.echo(f"rewrapped {asyncio.run(_in_session(_run))} data key(s)")


@keys.command("rotate-dek")
def keys_rotate_dek(tenant: str | None = typer.Option(None), platform: bool = typer.Option(False)) -> None:
    """Rotate one scope's data key. Existing ciphertext stays readable; new writes use the new version."""
    if bool(tenant) == platform:
        typer.echo("pass exactly one of --tenant or --platform")
        raise typer.Exit(2)
    try:
        tenant_id = None if platform else uuid.UUID(tenant)
    except ValueError:
        typer.echo("--tenant must be a UUID")
        raise typer.Exit(2) from None
    keyring = Keyring(KekSet.from_settings(get_settings()))

    async def _run(s: AsyncSession) -> int:
        async with s.begin():
            return await keyring.rotate(s, tenant_id)

    typer.echo(f"active data key version: {asyncio.run(_in_session(_run))}")
```

- [ ] **Step 4: Write the runbook**

`docs/operations/key-rotation.md` must contain these four phases verbatim. **No phase may start before the previous one is fully rolled out to every process that reads secrets (`api`, workers, CLI hosts).**

| Phase | Configuration on every process | Why |
|---|---|---|
| A. Distribute | `KEK=old` (current), `KEK_PREVIOUS=new` | Every process can *read* data wrapped by the new key before anyone *writes* with it. |
| B. Switch | `KEK=new` (current), `KEK_PREVIOUS=old` | New data keys are wrapped with `new`; old rows stay readable. |
| C. Rewrap | unchanged from B; run `dewpoint keys rewrap` | Moves every data key to `new`, in short committed batches. Re-run until it prints `rewrapped 0`. |
| D. Retire | `KEK=new` only | Only after `dewpoint keys status` shows no `old=` line **and** exits 0. |

The runbook also covers:
- **Rollback:** during A or B, revert the configuration. After C, rollback means running phases A–C in reverse.
- **Data-key rotation:** `keys rotate-dek` rotates one tenant's key, or the platform's. It's independent of KEK rotation.
- **Key generation:** `openssl rand -base64 32`. KEK ids must be unique and never reused.
- **Backups:** a database backup is only restorable with the KEKs that wrapped its rows at backup time. Keep retired KEKs in escrow for the backup retention period.

**Live rehearsal (done at this checkpoint):**
- On the Compose stack, run phases A–D with the rollout variables that Compose now passes through (`DEWPOINT_KEK_ID`, `DEWPOINT_KEK_PREVIOUS_B64`, `DEWPOINT_KEK_PREVIOUS_ID`), restarting `api` for each phase.
- A probe running as `dewpoint_admin` decrypts every stored secret. It finds tenants through `data_keys` and then sets `tenant_scope`, because `connections` stays RLS-scoped even for the admin role. It prints only a fingerprint.
- The fingerprint must be identical before, during and after rotation, and `keys status` must exit 3 when configured with the retired key alone.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/apps/cli -v && uv run pytest tests/core/crypto -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(keys): key status, batched dual-KEK rewrap, data-key rotation CLI and rollout runbook

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Spec coverage (Foundations scope, spec §14 item 1)

| Spec requirement | Task |
|---|---|
| Monorepo, import rules, CI and security pipeline, Apache-2.0, DCO, SECURITY.md (§3.2, §11) | 1, 13, 14 |
| Local auth: argon2id, TOTP, passkeys, recovery codes, MFA policy (§4.2) | 6, 8, 9 |
| Server-side sessions, CSRF, idle/absolute timeouts, revoke on password change, lockout (§4.2) | 7, 8 |
| Step-up for tenants requiring passkeys (§4.2) | 9, 10 |
| Flat tenants and memberships; platform admin without implicit tenant access (§4.1) | 4, 10 |
| Roles as permission bundles; editors use but can't manage connections (§4.3) | 10 |
| Authority from membership check; RLS as defence in depth; missing and mismatched tenant-context tests (§4.4) | 4, 10, 11, 12 |
| Envelope encryption, tenant data keys, key-encryption-key rotation with a dual-key rollout (§5, §11) | 5, 15 |
| Generic connections with encrypted secrets, `secret_set` only, Mist type with verify (§5) | 12 |
| Audit log: append-only hash chain, external anchoring by a narrow auditor role, fail-closed verification (§11) | 11 |
| Security headers, strict CSP, sanitized errors (§11) | 2, 14 |
| Minimal React shell under the no-AI-slop visual rules (§10.1) | 13 |
| Compose, bootstrap CLI, hardened images, SBOM, cosign, provenance (§13) | 6, 14 |

**Deliberately deferred** (other sub-projects):
- The Helm chart (sub-project 4).
- The `ingress`/`dispatcher`/`worker` processes and their DB login roles, and `resolve_webhook_endpoint()` (sub-project 2). The group roles already exist from migration 0001.
- Egress allowlist and SSRF guard for user-supplied hosts (sub-project 2). Foundations only calls allowlisted Mist hosts.
- The OpenTelemetry setup (sub-project 2, together with the workers).
