import io
import zipfile


def _make_job(client, db_session, recipients=None):
    from app.services.jobs import process_job

    recips = recipients or [
        {"name": "Asha Rao", "email": "asha@example.com"},
        {"name": "Boris Lee", "email": "boris@example.com"},
    ]
    r = client.post(
        "/api/v1/jobs",
        json={
            "title": "Intro to Python",
            "issued_on": "2026-10-01",
            "issuer": "Example Academy",
            "recipients": recips,
        },
    )
    assert r.status_code == 202
    job_id = r.json()["id"]
    process_job(db_session, job_id)
    return job_id


def test_download_single_pdf(client, db_session):
    job_id = _make_job(client, db_session)
    r = client.get(f"/api/v1/jobs/{job_id}")
    cert_id = r.json()["certificates"][0]["id"]

    r = client.get(f"/api/v1/jobs/{job_id}/certificates/{cert_id}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"


def test_download_zip(client, db_session):
    job_id = _make_job(client, db_session)
    r = client.get(f"/api/v1/jobs/{job_id}/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert len(zf.namelist()) == 2
    for name in zf.namelist():
        assert name.endswith(".pdf")
        assert zf.read(name)[:5] == b"%PDF-"


def test_download_404_unknown(client):
    r = client.get("/api/v1/jobs/nope/certificates/nope")
    assert r.status_code == 404
    r = client.get("/api/v1/jobs/nope/download")
    assert r.status_code == 404


def test_download_409_failed_cert(client, db_session):
    job_id = _make_job(
        client,
        db_session,
        recipients=[
            {"name": "Good", "email": "good@example.com"},
            {"name": "", "email": "bad@example.com"},
        ],
    )
    r = client.get(f"/api/v1/jobs/{job_id}")
    certs = {c["recipient_email"]: c for c in r.json()["certificates"]}
    failed_id = certs["bad@example.com"]["id"]
    r = client.get(f"/api/v1/jobs/{job_id}/certificates/{failed_id}")
    assert r.status_code == 409
