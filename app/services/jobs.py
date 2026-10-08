"""Background processing and recovery."""

from datetime import datetime

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Certificate, Job
from app.services.certificates import cert_output_path, generate_certificate_pdf


def _utcnow():
    return datetime.utcnow()


def finalize_job(db, job: Job) -> Job:
    certs = db.scalars(select(Certificate).where(Certificate.job_id == job.id)).all()
    succeeded = sum(1 for c in certs if c.status == "succeeded")
    failed = sum(1 for c in certs if c.status == "failed")
    total = job.total or len(certs)
    if succeeded == total and total > 0:
        job.status = "completed"
    elif succeeded > 0:
        job.status = "completed_with_errors"
    elif failed > 0:
        job.status = "failed"
    else:
        job.status = "processing"
    if job.status in ("completed", "completed_with_errors", "failed"):
        if job.finished_at is None:
            job.finished_at = _utcnow()
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def process_job(db, job_id: str) -> Job | None:
    """Process all pending certificates for a job. Callable directly from tests."""
    job = db.get(Job, job_id)
    if job is None:
        return None
    try:
        job.status = "processing"
        db.add(job)
        db.commit()

        certs = db.scalars(
            select(Certificate)
            .where(Certificate.job_id == job_id, Certificate.status == "pending")
            .order_by(Certificate.created_at)
        ).all()

        for cert in certs:
            try:
                cert.status = "processing"
                db.add(cert)
                db.commit()

                # Re-read job fields for the template (title/issuer/date).
                db.refresh(job)
                output_path = cert_output_path(job.id, cert.id)
                generate_certificate_pdf(
                    name=cert.recipient_name,
                    title=job.title,
                    issuer=job.issuer or "",
                    issued_on=job.issued_on,
                    cert_id=cert.id,
                    output_path=output_path,
                )
                cert.status = "succeeded"
                cert.file_path = output_path
                cert.error = None
                cert.finished_at = _utcnow()
                db.add(cert)
                db.commit()
            except Exception as exc:  # one failure must not block the others
                db.rollback()
                cert = db.get(Certificate, cert.id)
                if cert is not None:
                    cert.status = "failed"
                    cert.error = str(exc)[:1000] or "generation failed"
                    cert.finished_at = _utcnow()
                    db.add(cert)
                    db.commit()
    finally:
        # Finalization must run even if something unexpected blows up.
        try:
            job = db.get(Job, job_id)
            if job is not None:
                finalize_job(db, job)
        except Exception:
            db.rollback()
    return db.get(Job, job_id)


def process_job_sync(job_id: str) -> None:
    """BackgroundTasks entrypoint: plain def so it runs in the threadpool."""
    db = SessionLocal()
    try:
        process_job(db, job_id)
    finally:
        db.close()


def recover_stale_jobs() -> dict:
    """Startup recovery: stale pending/processing rows can never be left hanging."""
    db = SessionLocal()
    try:
        stale = db.scalars(
            select(Certificate).where(Certificate.status.in_(["pending", "processing"]))
        ).all()
        affected_jobs: set[str] = set()
        for cert in stale:
            cert.status = "failed"
            cert.error = "interrupted by restart"
            cert.finished_at = _utcnow()
            db.add(cert)
            affected_jobs.add(cert.job_id)
        db.commit()
        recovered_jobs = 0
        for job_id in affected_jobs:
            job = db.get(Job, job_id)
            if job is not None and job.status in ("pending", "processing"):
                finalize_job(db, job)
                recovered_jobs += 1
        return {
            "recovered_certificates": len(stale),
            "recovered_jobs": recovered_jobs,
        }
    finally:
        db.close()
