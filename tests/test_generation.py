from datetime import date


def test_generate_pdf_exists_and_valid(tmp_path):
    from pypdf import PdfReader

    from app.services.certificates import generate_certificate_pdf

    out = str(tmp_path / "cert.pdf")
    generate_certificate_pdf(
        name="Asha Rao",
        title="Intro to Python",
        issuer="Example Academy",
        issued_on=date(2026, 10, 1),
        cert_id="test-cert-id-123",
        output_path=out,
    )
    import os

    assert os.path.exists(out)
    with open(out, "rb") as f:
        assert f.read(5) == b"%PDF-"

    reader = PdfReader(out)
    assert len(reader.pages) >= 1
    text = reader.pages[0].extract_text() or ""
    assert "Asha Rao" in text
    assert "Intro to Python" in text


def test_generate_pdf_non_latin_name(tmp_path):
    from pypdf import PdfReader

    from app.services.certificates import generate_certificate_pdf

    out = str(tmp_path / "cert2.pdf")
    generate_certificate_pdf(
        name="\u092a\u094d\u0930\u093f\u092f\u093e \u0936\u0930\u094d\u092e\u093e",
        title="Course",
        issuer="Academy",
        issued_on="2026-10-01",
        cert_id="cert-2",
        output_path=out,
    )
    reader = PdfReader(out)
    assert len(reader.pages) >= 1
