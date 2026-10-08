# Bulk Certificate Generator

Backend API that accepts **one request with many recipients**, validates them,
generates a PDF certificate per valid recipient from a single predefined
template, tracks per-certificate and per-job status, and lets the client
retrieve the results.

One failing certificate never blocks the others.

## Stack

- Python 3.12, FastAPI (auto Swagger at `/docs`, ReDoc at `/redoc`)
- PostgreSQL 16 only (Docker Compose for dev/review, same engine for tests)
- SQLAlchemy 2.0, `create_all` on startup (Alembic listed as next step)
- ReportLab + TTF font for PDFs (no system deps beyond `fonts-dejavu-core` in Docker)
- `BackgroundTasks` for processing (see design decision below)
- pytest + httpx `TestClient`, ruff, GitHub Actions, Docker + Compose

Full rationale: see `designdoc.md`.

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate | Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit DATABASE_URL / CERT_DIR if needed
```

`.env.example`:

```
DATABASE_URL=postgresql+psycopg2://postgres:postgres@db:5432/certs
CERT_DIR=./data/certificates
MAX_RECIPIENTS=1000
LOG_LEVEL=INFO
```

Postgres is required. Start it with Compose (`docker compose up db`) or point
`DATABASE_URL` at your own Postgres 16. SQLite URLs are rejected.

## Run the application

Local:

```bash
uvicorn app.main:app --reload --port 8000
# open http://localhost:8000/docs
```

Docker (reviewer path):

```bash
docker compose up --build
# open http://localhost:8000/docs
```

- `db`: Postgres 16 with healthcheck, named volume `pgdata`
- `api`: waits for healthy db, serves on `:8000`, certificates in volume `certdata`

Health:

```
GET /health
GET /api/v1/health
```

## Run tests

```bash
python -m pytest -q
python -m ruff check app tests
```

Tests run against PostgreSQL (`TEST_DATABASE_URL`, default
`postgresql+psycopg2://postgres:postgres@localhost:5432/certs_test`; the test
database is auto-created). CI runs the same suite against a Postgres service
container, then `ruff` and `docker build`.

Coverage (required + extras):

1. Create job: 202, rows persisted, `total` correct
2. Input validation: request-level 422s, row-level failed rows
3. Generation: PDF exists, `%PDF-` header, recipient name extractable
4. Status/progress: counts + per-row results + pagination
5. Individual failure: monkeypatched generator raises for one recipient
6. Retrieval: single PDF, ZIP, 404 unknown, 409 failed cert
7. Startup recovery: stale `processing` rows marked `failed`

## Submit a certificate generation request

All API routes under `/api/v1`.

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Intro to Python",
    "issued_on": "2026-10-01",
    "issuer": "Example Academy",
    "recipients": [
      {"name": "Asha Rao", "email": "asha@example.com"},
      {"name": "Boris Lee", "email": "boris@example.com"}
    ]
  }'
```

Success: `202 Accepted` with the new job.

```json
{
  "id": "...",
  "status": "pending",
  "total": 2, "succeeded": 0, "failed": 0, "pending": 2,
  "certificates": [...]
}
```

Validation, two levels:

- **Request level (reject whole request, 422):** malformed body, missing
  `title`/`issued_on`, empty recipient list, more than `MAX_RECIPIENTS`
  (default 1000), over-long fields.
- **Row level (accept job, mark row `failed` immediately):** empty/whitespace
  name, invalid email. Valid rows still proceed.

## Check progress / retrieve

```bash
# Status, counts (computed via GROUP BY, never stored), paginated certs
curl "http://localhost:8000/api/v1/jobs/<job_id>?page=1&page_size=50"

# Download one PDF (only if succeeded)
curl -O "http://localhost:8000/api/v1/jobs/<job_id>/certificates/<cert_id>"

# ZIP of all succeeded PDFs
curl -O "http://localhost:8000/api/v1/jobs/<job_id>/download"
```

Status codes: `202` accepted, `404` unknown job/cert, `409` downloading a
certificate that is not `succeeded`, `422` request-level validation failure.

Job states: `pending → processing → completed | completed_with_errors | failed`
(`completed` = all succeeded, `completed_with_errors` = some failed,
`failed` = none succeeded).
Certificate states: `pending → processing → succeeded | failed`.

## Important design decisions

- **BackgroundTasks, not sync, not Celery:** a request with hundreds of
  recipients would hold the HTTP connection, risk timeouts, and make
  "progress" meaningless — so not sync. Celery/Redis would add a broker,
  worker service, and setup/tests beyond what the problem needs — so
  `BackgroundTasks` in the API process. Trade-off: not durable across
  restarts. Mitigations: per-certificate `try/except`, job finalization in
  `finally`, startup recovery marking stale `pending`/`processing` rows
  `failed` with `interrupted by restart`, atomic temp-file-then-rename writes
  to deterministic `{job_id}/{cert_id}.pdf` paths. Production answer: move to
  Celery/durable queue + S3 + separate workers (documented in `designdoc.md`).
- **Task is plain `def`** (threadpool): PDF rendering is CPU-bound and must
  not block the event loop; it opens its own DB session.
- **Single ReportLab landscape-A4 template:** title, `awarded to {name}`,
  issuer, issue date, certificate UUID as verifiable reference. Filenames use
  the certificate id only, never user input; names are length-capped and
  control characters stripped.
- **Storage:** `CERT_DIR` volume, DB holds the path. Production: S3
  pre-signed URLs.

Out of scope (by design): auth, multiple templates/editor, email delivery,
durable queue, rate limiting, migrations, object storage.
