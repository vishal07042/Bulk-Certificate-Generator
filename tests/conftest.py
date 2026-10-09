import os
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import create_app

TEST_DATABASE_URL = (
    os.getenv("TEST_DATABASE_URL")
    or "postgresql+psycopg2://postgres:postgres@localhost:5432/certs_test"
)


def _ensure_test_database(url: str) -> None:
    """Create the test database if it does not exist (Postgres only)."""
    import time

    import psycopg2

    parsed = make_url(url)
    db_name = parsed.database
    if not db_name:
        raise ValueError("TEST_DATABASE_URL must include a database name")

    kwargs = {
        "host": parsed.host or "localhost",
        "port": parsed.port or 5432,
        "user": parsed.username or "postgres",
        "password": parsed.password or "",
        "dbname": "postgres",
    }
    # In CI the Postgres service can still be accepting connections when the
    # test session starts; wait for it instead of failing every test at once.
    last_exc: Exception | None = None
    for _ in range(30):
        try:
            admin_conn = psycopg2.connect(**kwargs)
            break
        except psycopg2.OperationalError as exc:
            last_exc = exc
            time.sleep(1)
    else:
        raise last_exc  # type: ignore[misc]
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        admin_conn.close()


@asynccontextmanager
async def _noop_lifespan(app):
    yield


@pytest.fixture(scope="session")
def test_engine():
    _ensure_test_database(TEST_DATABASE_URL)
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables(test_engine):
    """Truncate after every test: with a shared Postgres DB, cleanup must not
    depend on which fixtures a test requests."""
    yield
    session = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)()
    try:
        session.execute(text("TRUNCATE certificates, jobs CASCADE"))
        session.commit()
    finally:
        session.close()


@pytest.fixture()
def session_factory(test_engine):
    return sessionmaker(bind=test_engine, autoflush=False, autocommit=False)


@pytest.fixture()
def db_session(session_factory):
    """Private session for direct service calls and assertions (test thread)."""
    session = session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def client(session_factory, tmp_path, monkeypatch):
    import app.services.jobs as jobs_module
    from app import config

    cert_dir = tmp_path / "certs"
    cert_dir.mkdir()
    monkeypatch.setattr(config.settings, "CERT_DIR", str(cert_dir))
    # Tests drive processing explicitly via process_job(db_session, job_id);
    # never let HTTP-layer background work touch the real DB, and never run
    # lifespan (init_db/recovery) against it either.
    monkeypatch.setattr(jobs_module, "process_job_sync", lambda job_id: None)

    app = create_app()
    app.router.lifespan_context = _noop_lifespan

    def override_get_db():
        # Fresh session per request: the TestClient serves requests from a
        # different thread, so sharing one Session is not thread-safe.
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
