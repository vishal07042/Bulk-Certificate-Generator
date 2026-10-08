def test_startup_recovery_marks_stale_failed(client, db_session):
    from app.models import Certificate, Job
    from app.services.jobs import recover_stale_jobs

    r = client.post(
        "/api/v1/jobs",
        json={
            "title": "Course",
            "issued_on": "2026-10-01",
            "issuer": "Academy",
            "recipients": [
                {"name": "A", "email": "a@example.com"},
                {"name": "B", "email": "b@example.com"},
            ],
        },
    )
    job_id = r.json()["id"]

    # Simulate a crash: rows stuck in pending/processing, job stuck in processing.
    job = db_session.get(Job, job_id)
    job.status = "processing"
    db_session.add(job)
    certs = db_session.query(Certificate).filter_by(job_id=job_id).all()
    certs[0].status = "processing"
    db_session.add(certs[0])
    db_session.commit()

    result = recover_stale_jobs(db_session)
    assert result["recovered_certificates"] == 2

    db_session.expire_all()
    certs = db_session.query(Certificate).filter_by(job_id=job_id).all()
    assert all(c.status == "failed" for c in certs)
    assert all(c.error == "interrupted by restart" for c in certs)
    job = db_session.get(Job, job_id)
    assert job.status == "failed"
    assert job.finished_at is not None
