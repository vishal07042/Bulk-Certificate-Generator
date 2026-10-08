def _payload():
    return {
        "title": "Intro to Python",
        "issued_on": "2026-10-01",
        "issuer": "Example Academy",
        "recipients": [{"name": "Asha Rao", "email": "asha@example.com"}],
    }


def test_idempotent_replay_returns_same_job(client, db_session):
    from app.models import Job

    r1 = client.post(
        "/api/v1/jobs", json=_payload(), headers={"Idempotency-Key": "key-123"}
    )
    assert r1.status_code == 202, r1.text
    job_id = r1.json()["id"]

    r2 = client.post(
        "/api/v1/jobs", json=_payload(), headers={"Idempotency-Key": "key-123"}
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["id"] == job_id

    assert db_session.query(Job).count() == 1


def test_idempotency_key_mismatch_returns_409(client):
    r1 = client.post(
        "/api/v1/jobs", json=_payload(), headers={"Idempotency-Key": "dup-key"}
    )
    assert r1.status_code == 202

    other = _payload()
    other["title"] = "Different Course"
    r2 = client.post(
        "/api/v1/jobs", json=other, headers={"Idempotency-Key": "dup-key"}
    )
    assert r2.status_code == 409


def test_no_key_creates_new_job_each_time(client, db_session):
    from app.models import Job

    r1 = client.post("/api/v1/jobs", json=_payload())
    r2 = client.post("/api/v1/jobs", json=_payload())
    assert r1.status_code == 202
    assert r2.status_code == 202
    assert r1.json()["id"] != r2.json()["id"]
    assert db_session.query(Job).count() == 2
