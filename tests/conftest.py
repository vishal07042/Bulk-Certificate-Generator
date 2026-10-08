import os

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
    parsed = make_url(url)
    db_name = parsed.database
    if not db_name:
        raise ValueError("TEST_DATABASE_URL must include a database name")
    import psycopg2

    admin_conn = psycopg2.connect(
        host=parsed.host or "localhost",
        port=parsed.port or 5432,
        user=parsed.username or "postgres",
        password=parsed.password or "",
        dbname="postgres",
    )
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        admin_conn.close()


@pytest.fixture(scope="session")
def test_engine():
    _ensure_test_database(TEST_DATABASE_URL)
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(test_engine):
    TestingSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.rollback()
        session.execute(text("TRUNCATE certificates, jobs CASCADE"))
        session.commit()
        session.close()


@pytest.fixture()
def client(db_session, tmp_path, monkeypatch):
    import app.database as db_module
    import app.services.jobs as jobs_module
    from app import config

    cert_dir = tmp_path / "certs"
    cert_dir.mkdir()
    monkeypatch.setattr(config.settings, "CERT_DIR", str(cert_dir))
    # Tests drive processing explicitly via process_job(db_session, job_id);
    # never let HTTP-layer background work or lifespan touch the real DB.
    monkeypatch.setattr(db_module, "init_db", lambda: None)
    monkeypatch.setattr(
        jobs_module,
        "recover_stale_jobs",
        lambda db=None: {"recovered_certificates": 0, "recovered_jobs": 0},
    )
    monkeypatch.setattr(jobs_module, "process_job_sync", lambda job_id: None)

    app = create_app()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
