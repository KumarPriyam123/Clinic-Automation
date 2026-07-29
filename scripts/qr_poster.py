"""QR poster — A4 PDF a clinic prints and laminates at the desk.

Big QR to wa.me/<number>?text=Namaste, a Hindi headline, a 3-step how-to, small
ClinicQ footer. Calm clinical look (deep teal), matches the panel.

Deps (pilot-only, not required to run the app): qrcode + reportlab.
    pip install ".[pilot]"        # from backend/, or: pip install qrcode reportlab

    python scripts/qr_poster.py --number 919876543210 --clinic "Sharma Clinic" \
        --out sharma_poster.pdf
"""

from __future__ import annotations

import argparse
import sys

try:
    import qrcode
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
except ModuleNotFoundError:  # pragma: no cover - env-dependent
    print(
        "Missing deps. Install the pilot extras:\n"
        '    pip install ".[pilot]"      # from backend/\n'
        "    # or: pip install qrcode reportlab",
        file=sys.stderr,
    )
    raise SystemExit(2) from None

TEAL = (0.059, 0.463, 0.431)  # #0f766e
INK = (0.086, 0.188, 0.173)


def _qr_image(data: str):
    qr = qrcode.QRCode(version=None, box_size=10, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.make_image(fill_color="#0f766e", back_color="white")


def build(number: str, clinic: str, out: str) -> None:
    digits = "".join(c for c in number if c.isdigit())
    link = f"https://wa.me/{digits}?text=Namaste"

    c = canvas.Canvas(out, pagesize=A4)
    w, h = A4

    # header band
    c.setFillColorRGB(*TEAL)
    c.rect(0, h - 45 * mm, w, 45 * mm, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(w / 2, h - 24 * mm, clinic)
    c.setFont("Helvetica", 15)
    c.drawCentredString(
        w / 2, h - 36 * mm, "WhatsApp par apna number lein — line mein na lagein"
    )

    # QR (centered)
    img = _qr_image(link)
    qr_reader = _to_reader(img)
    qr_size = 95 * mm
    c.drawImage(
        qr_reader,
        (w - qr_size) / 2,
        h - 45 * mm - qr_size - 12 * mm,
        qr_size,
        qr_size,
        preserveAspectRatio=True,
        mask="auto",
    )

    # Hindi headline under QR
    c.setFillColorRGB(*INK)
    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(w / 2, h - 45 * mm - qr_size - 26 * mm, "Yahan scan karein")

    # 3-step how-to
    steps = [
        "1.  QR scan karein ya WhatsApp kholein",
        "2.  'Namaste' bhejein — apna token milega",
        "3.  Position aur time WhatsApp par dekhein",
    ]
    y = h - 45 * mm - qr_size - 44 * mm
    c.setFont("Helvetica", 16)
    for line in steps:
        c.drawCentredString(w / 2, y, line)
        y -= 11 * mm

    # footer
    c.setFillColorRGB(*TEAL)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(w / 2, 16 * mm, "Powered by ClinicQ")
    c.setFillColorRGB(0.4, 0.45, 0.43)
    c.setFont("Helvetica", 9)
    c.drawCentredString(w / 2, 10 * mm, link)

    c.showPage()
    c.save()
    print(f"Wrote {out}  ->  {link}")


def _to_reader(pil_img):
    """Wrap a PIL image for reportlab.drawImage without a temp file."""
    from io import BytesIO

    from reportlab.lib.utils import ImageReader

    buf = BytesIO()
    pil_img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def main() -> None:
    ap = argparse.ArgumentParser(description="ClinicQ QR poster (A4 PDF)")
    ap.add_argument(
        "--number", required=True, help="WhatsApp number, digits only (e.g. 91987...)"
    )
    ap.add_argument("--clinic", required=True)
    ap.add_argument("--out", default="clinic_qr_poster.pdf")
    args = ap.parse_args()
    build(args.number, args.clinic, args.out)


if __name__ == "__main__":
    main()
