from datetime import date

from pydantic import BaseModel, Field


class RecipientIn(BaseModel):
    name: str = Field(max_length=300)
    email: str = Field(max_length=320)


class JobCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    issued_on: date
    issuer: str | None = Field(default="", max_length=300)
    recipients: list[RecipientIn] = Field(min_length=1)


class CertificateOut(BaseModel):
    id: str
    recipient_name: str
    recipient_email: str
    status: str
    error: str | None = None
    download_url: str | None = None


class JobOut(BaseModel):
    id: str
    status: str
    title: str
    issued_on: date
    issuer: str
    total: int
    succeeded: int
    failed: int
    pending: int
    page: int = 1
    page_size: int = 50
    certificates: list[CertificateOut] = []
