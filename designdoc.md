# Design Doc: Bulk Certificate Generator

## 1. Goal
Backend API that accepts one request containing many recipients, validates them, generates a PDF certificate per valid recipient from a single predefined template, tracks per-certificate and per-job status, and lets the client retrieve the results.

Source requirements: submit, validate, generate, track status, check progress, retrieve; bulk (not one request per certificate); one failing certificate must not block the others; document the sync/async choice; tests for the six listed areas; README. Everything else in this doc is a deliberate extra, labelled as such.

## 2. Stack (final)
| Concern | Choice | Why |
|---|---|---|
| Language / framework | Python 3.12, FastAPI | Pydantic validation, auto OpenAPI docs |
| DB | PostgreSQL 16 (Docker Compose); SQLite for local tests | Real constraints and transactions; `DATABASE_URL` env var switches engines |
| ORM | SQLAlchemy 2.0 | Standard, engine-agnostic |
| Schema management | `create_all` on startup | Alembic is overkill here; listed under "next steps" |
| PDF | ReportLab + bundled TTF font | No system deps; TTF for non-Latin names |
| Processing | FastAPI `BackgroundTasks` | See section 5 |
| Tests | pytest + httpx `TestClient` | |
| Lint | ruff | |
| API docs | Swagger UI at `/docs`, ReDoc at `/redoc` (FastAPI defaults) | No extra work |
| CI | GitHub Actions | Section 9 |
| Container | Docker + Compose (`db`, `api`) | Section 10 |

## 3. API
All routes under `/api/v1`.

| Method | Path | Purpose | Success |
|---|---|---|---|
| POST | `/jobs` | Submit a bulk request | 202 + job |
| GET | `/jobs/{job_id}` | Status, counts, paginated per-certificate results | 200 |
| GET | `/jobs/{job_id}/certificates/{cert_id}` | Download one PDF | 200 `application/pdf` |
| GET | `/jobs/{job_id}/download` | ZIP of all successful PDFs (extra) | 200 `application/zip` |
| GET | `/health` | Liveness | 200 |

### Request (assumed shape; the assignment leaves fields open)
```json
{
  "title": "Intro to Python",
  "issued_on": "2026-10-01",
  "issuer": "Example Academy",
  "recipients": [
    {"name": "Asha Rao", "email": "asha@example.com"}
  ]
}
```

### Status response
```json
{
  "id": "…",
  "status": "completed_with_errors",
  "total": 3, "succeeded": 2, "failed": 1, "pending": 0,
  "certificates": [
    {"id": "…", "recipient_name": "Asha Rao", "status": "succeeded", "download_url": "…"},
    {"id": "…", "recipient_name": "", "status": "failed", "error": "name must not be empty"}
  ]
}
```

### Status codes
- 202 accepted, 404 unknown job/cert, 409 downloading a cert that is not `succeeded`, 422 request-level validation failure.

## 4. Data model
**jobs**: `id (uuid)`, `status`, `title`, `issued_on`, `issuer`, `total`, `created_at`, `finished_at`

**certificates**: `id (uuid)`, `job_id (fk, indexed)`, `recipient_name`, `recipient_email`, `status`, `file_path`, `error`, `created_at`, `finished_at`

States:
- certificate: `pending → processing → succeeded | failed`
- job: `pending → processing → completed | completed_with_errors | failed`
  - `completed`: all succeeded. `completed_with_errors`: some failed. `failed`: none succeeded.

Progress counts are computed from certificate rows (`GROUP BY status`), never stored, so they cannot drift.

## 5. Processing model: BackgroundTasks (decision and reasoning)
`POST /jobs` validates, writes the job and all certificate rows in one transaction, schedules a background task, and returns 202 immediately.

**Why not synchronous:** a request with hundreds of recipients would hold the HTTP connection for the whole run, risk client/proxy timeouts, and make "progress" meaningless.
**Why not Celery/Redis:** allowed, but adds a broker, a worker service, and more setup and tests than the problem needs. Fewer moving parts means a codebase that is easy to explain and modify.
**Trade-off accepted:** `BackgroundTasks` runs in the API process and is not durable. If the process dies mid-job, in-flight work is lost.

Mitigations (required so the status API never lies):
1. Per-certificate `try/except`: one failure marks only that row `failed` with the error.
2. Job finalization in a `finally` block so an unexpected exception cannot leave the job stuck.
3. Startup recovery: on app start, any certificate in `pending`/`processing` from a previous run is marked `failed` with `interrupted by restart`, and affected jobs are finalized.
4. Documented in the README, with the production answer: move to a durable queue (Celery or similar) and horizontal workers.

Implementation notes:
- The task is a plain `def` (runs in the threadpool), since PDF rendering is CPU-bound and must not block the event loop.
- The task opens its own DB session; the request session is closed by then.
- Generation logic lives in a service function callable directly from tests, with no threads involved.

## 6. Validation
Two levels:
- **Request level (reject whole request, 422):** malformed body, missing `title`/`issued_on`, empty recipient list, more than `MAX_RECIPIENTS` (default 1000), over-long fields.
- **Row level (accept job, mark row failed immediately):** empty or whitespace name, invalid email format. The row is stored as `failed` with a reason so the client sees exactly which rows were rejected, and valid rows still proceed. This follows the requirement that one bad row must not block the rest.

Names are length-capped and control characters stripped. Filenames never use user input; they use the certificate id.

## 7. Retries and file safety
Deterministic output path (`{job_id}/{cert_id}.pdf`), written to a temp file then atomically renamed, so a retry overwrites rather than duplicates and a crash never leaves a half-written file.

Not done: de-duplicating identical recipients within one request. Each row is its own certificate. Documented.

## 8. Certificate generation
- Single ReportLab landscape A4 template: title, "awarded to {name}", issuer, issue date, certificate id (UUID) as a verifiable reference.
- Bundled TTF font so non-Latin names render.
- Storage: `CERT_DIR` (a Docker volume). DB holds the path. Production answer: object storage such as S3.

## 9. Testing and CI
Tests cover the six required areas plus the extras:
1. Create job: 202, rows persisted, `total` correct
2. Input validation: request-level 422s, row-level failed rows
3. Generation: PDF exists, valid PDF header, contains recipient name
4. Status/progress: counts and per-row results, pagination
5. Individual failure: monkeypatch the generator to raise for one recipient; others succeed, job ends `completed_with_errors`
6. Retrieval: single PDF, ZIP, 404 for unknown, 409 for failed cert
7. Startup recovery: stale `processing` rows get marked `failed`

Tests default to SQLite in-memory via dependency override. CI runs the same suite against a Postgres service container.

**CI (GitHub Actions), on push and PR:** checkout, set up Python, install deps, `ruff check`, `pytest` (Postgres service), `docker build`.

## 10. Docker
- `Dockerfile`: slim Python image, non-root user, installs requirements, runs `uvicorn`.
- `docker-compose.yml`: `db` (Postgres with healthcheck, named volume), `api` (depends on healthy db, env from `.env`, volume for certificates, port 8000).
- Reviewer run path: `docker compose up --build`, then open `/docs` or `/redoc`.

## 11. Configuration
Env vars via pydantic-settings, with `.env.example`: `DATABASE_URL`, `CERT_DIR`, `MAX_RECIPIENTS`, `LOG_LEVEL`.

## 12. Out of scope
Auth, multiple templates or template editor, email delivery, durable queue, rate limiting, migrations, object storage. Each can be named in the interview with how it would be added.

## 13. Limitations and what changes at scale
- Not durable across restarts (section 5). Next: Celery/queue with `acks_late` and idempotent tasks.
- Local volume storage. Next: S3 with pre-signed URLs.
- Single API process does the work. Next: separate worker deployment, horizontal scaling.
- `create_all`. Next: Alembic migrations.

## 14. Build order and git checkpoints
Each checkpoint leaves the repo runnable, tests green, one commit.

| # | Commit | Contents |
|---|---|---|
| 1 | `chore: project scaffold` | Layout, `requirements.txt`, ruff config, `.gitignore`, `.env.example`, empty README |
| 2 | `feat: config and db setup` | Settings, engine/session, models, `create_all`, `/health`, first test |
| 3 | `feat: docker and compose` | Dockerfile, compose with db, app boots in container |
| 4 | `ci: github actions` | Lint, test with Postgres service, docker build |
| 5 | `feat: create job endpoint` | Schemas, validation (both levels), `POST /jobs`, tests |
| 6 | `feat: certificate generation` | ReportLab template, service function, tests |
| 7 | `feat: background processing` | BackgroundTasks task, per-item failure handling, finalization, failure test |
| 8 | `feat: status endpoint` | `GET /jobs/{id}`, counts, pagination, tests |
| 9 | `feat: retrieval endpoints` | Single PDF, ZIP, 404/409 cases, tests |
| 10 | `feat: startup recovery` | Stale-row recovery hook, test |
| 11 | `docs: readme` | Setup, run, test, submit, retrieve, design decisions |
