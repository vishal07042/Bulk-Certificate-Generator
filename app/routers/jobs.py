import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Certificate, Job
from app.schemas import CertificateOut, JobCreate, JobOut

router = APIRouter()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def sanitize_name(name: str) -> str:
    cleaned = name.strip()
    # Strip control characters (Cc) but keep all printable unicode (non-Latin names).
    cleaned = "".join(ch for ch in cleaned if ch >= " " or ch in ("\t",))
    cleaned = "".join(ch for ch in cleaned if ord(ch) != 127)
    return cleaned.strip()


def validate_row(name: str, email: str) -> tuple[str, str, str | None]:
    clean_name = sanitize_name(name or "")
    clean_email = (email or "").strip()
    if not clean_name:
        return clean_name, clean_email, "name must not be empty"
    if len(clean_name) > 300:
        return clean_name, clean_email, "name too long"
    if not clean_email or len(clean_email) > 320 or not EMAIL_RE.match(clean_email):
        return clean_name, clean_email, "invalid email"
    return clean_name, clean_email, None


def certificate_to_out(job_id: str, cert: Certificate) -> CertificateOut:
    url = (
        f"/api/v1/jobs/{job_id}/certificates/{cert.id}"
        if cert.status == "succeeded"
        else None
    )
    return CertificateOut(
        id=cert.id,
        recipient_name=cert.recipient_name,
        recipient_email=cert.recipient_email,
        status=cert.status,
        error=cert.error,
        download_url=url,
    )


def build_job_out(
    job: Job, certs: list[Certificate], page: int = 1, page_size: int = 50
) -> JobOut:
    succeeded = sum(1 for c in certs_all(job, certs) if c.status == "succeeded")
    failed = sum(1 for c in certs_all(job, certs) if c.status == "failed")
    # counts are computed over ALL certs of the job; `certs` here may be a page,
    # so callers that pass a page must also pass full counts. To keep one helper,
    # we accept full list; pagination slices afterwards.
    return JobOut(
        id=job.id,
        status=job.status,
        title=job.title,
        issued_on=job.issued_on,
        issuer=job.issuer or "",
        total=job.total,
        succeeded=succeeded,
        failed=failed,
        pending=job.total - succeeded - failed,
        page=page,
        page_size=page_size,
        certificates=[certificate_to_out(job.id, c) for c in certs],
    )


def certs_all(job: Job, certs: list[Certificate]) -> list[Certificate]:
    return certs


@router.post("/jobs", status_code=202, response_model=JobOut)
def create_job(payload: JobCreate, db: Session = Depends(get_db)):
    if len(payload.recipients) == 0:
        raise HTTPException(status_code=422, detail="recipients must not be empty")
    if len(payload.recipients) > settings.MAX_RECIPIENTS:
        raise HTTPException(
            status_code=422,
            detail=f"too many recipients (max {settings.MAX_RECIPIENTS})",
        )

    job_id = str(uuid.uuid4())
    now = datetime.utcnow()
    job = Job(
        id=job_id,
        status="pending",
        title=payload.title.strip(),
        issued_on=payload.issued_on,
        issuer=(payload.issuer or "").strip(),
        total=len(payload.recipients),
        created_at=now,
    )
    db.add(job)

    cert_rows: list[Certificate] = []
    for r in payload.recipients:
        clean_name, clean_email, error = validate_row(r.name, r.email)
        if error is not None:
            cert = Certificate(
                id=str(uuid.uuid4()),
                job_id=job_id,
                recipient_name=clean_name,
                recipient_email=clean_email,
                status="failed",
                error=error,
                finished_at=now,
            )
        else:
            cert = Certificate(
                id=str(uuid.uuid4()),
                job_id=job_id,
                recipient_name=clean_name,
                recipient_email=clean_email,
                status="pending",
            )
        db.add(cert)
        cert_rows.append(cert)

    db.commit()
    for c in cert_rows:
        db.refresh(c)
    db.refresh(job)

    return build_job_out(job, cert_rows, page=1, page_size=len(cert_rows))
