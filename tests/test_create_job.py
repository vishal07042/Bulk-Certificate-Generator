def _payload(**overrides):
    base = {
        "title": "Intro to Python",
        "issued_on": "2026-10-01",
        "issuer": "Example Academy",
        "recipients": [
            {"name": "Asha Rao", "email": "asha@example.com"},
            {"name": "Boris Lee", "email": "boris@example.com"},
        ],
    }
    base.update(overrides)
    return base


def test_create_job_202_and_rows_persisted(client, db_session):
    from app.models import Certificate, Job

    r = client.post("/api/v1/jobs", json=_payload())
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["total"] == 2
    assert body["status"] == "pending"

    jobs = db_session.query(Job).all()
    assert len(jobs) == 1
    assert jobs[0].total == 2
    certs = db_session.query(Certificate).all()
    assert len(certs) == 2


def test_request_level_validation_422(client):
    # empty recipients
    r = client.post("/api/v1/jobs", json=_payload(recipients=[]))
    assert r.status_code == 422, r.text

    # missing title
    bad = _payload()
    del bad["title"]
    r = client.post("/api/v1/jobs", json=bad)
    assert r.status_code == 422

    # too many recipients
    from app import config

    many = [{"name": f"Name {i}", "email": f"u{i}@example.com"} for i in range(5)]
    old_max = config.settings.MAX_RECIPIENTS
    config.settings.MAX_RECIPIENTS = 2
    try:
        r = client.post("/api/v1/jobs", json=_payload(recipients=many))
        assert r.status_code == 422
    finally:
        config.settings.MAX_RECIPIENTS = old_max

    # over-long title
    r = client.post("/api/v1/jobs", json=_payload(title="x" * 500))
    assert r.status_code == 422


def test_row_level_validation_marks_failed(client):
    payload = _payload(
        recipients=[
            {"name": "Good One", "email": "good@example.com"},
            {"name": "   ", "email": "bad@example.com"},
            {"name": "Bad Email", "email": "not-an-email"},
        ]
    )
    r = client.post("/api/v1/jobs", json=payload)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["total"] == 3
    assert body["failed"] == 2
    assert body["pending"] == 1
    statuses = {c["recipient_email"]: c for c in body["certificates"]}
    assert statuses["good@example.com"]["status"] == "pending"
    assert statuses["bad@example.com"]["status"] == "failed"
    assert "name" in statuses["bad@example.com"]["error"]
    assert statuses["not-an-email"]["status"] == "failed"
