"""Email the finished PDF to the user (SMTP settings come from the environment)."""
import os
import re
import smtplib
from email.message import EmailMessage

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_ATTACHMENT_MB = 20  # most mail providers refuse more


def configured():
    return bool(os.environ.get("SMTP_HOST"))


def send_pdf(to, pdf_path, filename):
    """Send the PDF as an attachment, or a note to download it in the app if it is too big."""
    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER", "")
    msg["To"] = to
    msg["Subject"] = f"Your bilingual book: {filename}"
    size_mb = os.path.getsize(pdf_path) / (1 << 20)
    if size_mb <= MAX_ATTACHMENT_MB:
        msg.set_content("Your translated bilingual PDF is attached.")
        with open(pdf_path, "rb") as f:
            msg.add_attachment(f.read(), maintype="application", subtype="pdf", filename=filename)
    else:
        msg.set_content(f"Your translation is ready, but the PDF ({size_mb:.0f} MB) is too large "
                        "to attach. Open the mini program to download it.")
    host, port = os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "465"))
    user, password = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD")
    smtp_cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
    with smtp_cls(host, port, timeout=30) as s:
        if port != 465:
            s.starttls()
        if user:
            s.login(user, password or "")
        s.send_message(msg)
