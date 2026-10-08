import os
import tempfile
from datetime import date
from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.config import settings

_FONT_NAME = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_TTF_REGISTERED = False


def _font_candidates() -> list[str]:
    here = Path(__file__).resolve()
    bundled = here.parent.parent / "assets" / "fonts" / "DejaVuSans.ttf"
    bundled_bold = here.parent.parent / "assets" / "fonts" / "DejaVuSans-Bold.ttf"
    return [
        str(bundled),
        str(bundled_bold),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/DejaVuSans.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\DejaVuSans.ttf",
    ]


def _ensure_fonts() -> tuple[str, str]:
    global _FONT_NAME, _FONT_BOLD, _TTF_REGISTERED
    if _TTF_REGISTERED:
        return _FONT_NAME, _FONT_BOLD
    for path in _font_candidates():
        if path and os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("BundledSans", path))
                bold_path = path.replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf").replace(
                    "arial.ttf", "arialbd.ttf"
                )
                if os.path.exists(bold_path):
                    pdfmetrics.registerFont(TTFont("BundledSans-Bold", bold_path))
                    _FONT_BOLD = "BundledSans-Bold"
                else:
                    _FONT_BOLD = "BundledSans"
                _FONT_NAME = "BundledSans"
                _TTF_REGISTERED = True
                break
            except Exception:
                continue
    return _FONT_NAME, _FONT_BOLD


def cert_output_path(job_id: str, cert_id: str) -> str:
    return os.path.join(settings.CERT_DIR, job_id, f"{cert_id}.pdf")


def generate_certificate_pdf(
    *,
    name: str,
    title: str,
    issuer: str,
    issued_on: date | str,
    cert_id: str,
    output_path: str,
) -> str:
    font, bold = _ensure_fonts()
    if isinstance(issued_on, date):
        issued_str = issued_on.isoformat()
    else:
        issued_str = str(issued_on)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(os.path.abspath(output_path)), suffix=".tmp"
    )
    os.close(fd)
    try:
        width, height = landscape(A4)
        c = canvas.Canvas(tmp_path, pagesize=landscape(A4))
        c.setTitle(f"Certificate - {name}")
        c.setAuthor(issuer or "Bulk Certificate Generator")

        # Border
        margin = 30
        c.setLineWidth(3)
        c.rect(margin, margin, width - 2 * margin, height - 2 * margin)
        c.setLineWidth(1)
        c.rect(margin + 8, margin + 8, width - 2 * (margin + 8), height - 2 * (margin + 8))

        # Title
        c.setFont(bold, 28)
        c.drawCentredString(width / 2, height - 140, title or "Certificate")

        c.setFont(font, 14)
        c.drawCentredString(width / 2, height - 175, "awarded to")

        # Recipient name (must be extractable text for tests)
        c.setFont(bold, 32)
        display_name = name.strip() or "Recipient"
        # Truncate extremely long names so they stay on one line.
        if len(display_name) > 80:
            display_name = display_name[:80]
        c.drawCentredString(width / 2, height - 225, display_name)

        c.setFont(font, 13)
        issuer_line = f"Issued by {issuer}" if issuer else "Bulk Certificate Generator"
        c.drawCentredString(width / 2, height - 265, issuer_line)
        c.drawCentredString(width / 2, height - 290, f"Issued on {issued_str}")

        c.setFont(font, 9)
        c.drawCentredString(width / 2, margin + 30, f"Certificate ID: {cert_id}")

        c.showPage()
        c.save()
        os.replace(tmp_path, output_path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
    return output_path
