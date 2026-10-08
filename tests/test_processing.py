def _payload(names):
    recips = [
        {"name": n, "email": f"{n.lower().replace(' ', '')}@example.com"}
        for n in names
    ]
    return {
        "title": "Intro to Python",
        "issued_on": "2026-10-01",
        "issuer": "Example Academy",
        "recipients": recips,
    }


def test_background_processes_all_and_finalizes(client, db_session):
    from app.models import Certificate, Job
    from app.services.jobs import process_job

    r = client.post("/api/v1/jobs", json=_payload(["Asha Rao", "Boris Lee"]))
    assert r.status_code == 202
    job_id = r.json()["id"]

    job = process_job(db_session, job_id)
    assert job is not None
    assert job.status == "completed"

    certs = db_session.query(Certificate).filter_by(job_id=job_id).all()
    assert len(certs) == 2
    assert all(c.status == "succeeded" for c in certs)

    jobs = db_session.query(Job).all()
    assert jobs[0].status == "completed"


def test_individual_failure_does_not_block_others(client, db_session, monkeypatch):
    import app.services.jobs as jobs_service
    from app.services.jobs import process_job

    real_generate = jobs_service.generate_certificate_pdf

    def flaky(*, name, **kwargs):
        if name == "Bad Luck":
            raise RuntimeError("boom for one cert")
        return real_generate(name=name, **kwargs)

    monkeypatch.setattr(jobs_service, "generate_certificate_pdf", flaky)

    r = client.post("/api/v1/jobs", json=_payload(["Good One", "Bad Luck", "Good Two"]))
    assert r.status_code == 202
    job_id = r.json()["id"]

    job = process_job(db_session, job_id)
    assert job.status == "completed_with_errors"

    from app.models import Certificate

    certs = {
        c.recipient_name: c
        for c in db_session.query(Certificate).filter_by(job_id=job_id).all()
    }
    assert certs["Good One"].status == "succeeded"
    assert certs["Good Two"].status == "succeeded"
    assert certs["Bad Luck"].status == "failed"
    assert "boom" in (certs["Bad Luck"].error or "")
