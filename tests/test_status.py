def test_status_counts_and_pagination(client, db_session):
    from app.services.jobs import process_job

    recips = [
        {"name": f"Person {i}", "email": f"p{i}@example.com"} for i in range(5)
    ]
    r = client.post(
        "/api/v1/jobs",
        json={
            "title": "Course",
            "issued_on": "2026-10-01",
            "issuer": "Academy",
            "recipients": recips,
        },
    )
    assert r.status_code == 202
    job_id = r.json()["id"]

    # Before processing: all pending.
    r = client.get(f"/api/v1/jobs/{job_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert body["pending"] == 5
    assert len(body["certificates"]) == 5

    process_job(db_session, job_id)

    r = client.get(f"/api/v1/jobs/{job_id}")
    body = r.json()
    assert body["status"] == "completed"
    assert body["succeeded"] == 5
    assert body["failed"] == 0
    assert body["pending"] == 0

    # Pagination: page 2 of size 2 -> 2 items.
    r = client.get(f"/api/v1/jobs/{job_id}?page=2&page_size=2")
    assert r.status_code == 200
    body = r.json()
    assert body["page"] == 2
    assert body["page_size"] == 2
    assert len(body["certificates"]) == 2
    # Full counts still reflect the whole job, not the page.
    assert body["succeeded"] == 5
    assert body["total"] == 5


def test_status_404(client):
    r = client.get("/api/v1/jobs/does-not-exist")
    assert r.status_code == 404


def test_status_shows_failed_rows(client, db_session):
    from app.services.jobs import process_job

    r = client.post(
        "/api/v1/jobs",
        json={
            "title": "Course",
            "issued_on": "2026-10-01",
            "issuer": "Academy",
            "recipients": [
                {"name": "Good", "email": "good@example.com"},
                {"name": "", "email": "bad@example.com"},
            ],
        },
    )
    job_id = r.json()["id"]
    process_job(db_session, job_id)
    r = client.get(f"/api/v1/jobs/{job_id}")
    body = r.json()
    assert body["succeeded"] == 1
    assert body["failed"] == 1
    by_email = {c["recipient_email"]: c for c in body["certificates"]}
    assert by_email["bad@example.com"]["status"] == "failed"
    assert by_email["bad@example.com"]["error"]
