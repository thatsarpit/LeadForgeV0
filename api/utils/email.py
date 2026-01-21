import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional


def _format_from_address(address: str, name: Optional[str] = None) -> str:
    if not name:
        return address
    return f"{name} <{address}>"


def send_bulk_email(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    from_address: str,
    from_name: Optional[str],
    recipients: list[str],
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
):
    if not smtp_host or not smtp_port:
        raise ValueError("SMTP host/port missing")
    if not from_address:
        raise ValueError("From address missing")
    if not recipients:
        raise ValueError("No recipients provided")

    context = ssl.create_default_context()
    sent = []
    failed = []

    with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
        server.starttls(context=context)
        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)

        for recipient in recipients:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = _format_from_address(from_address, from_name)
            msg["To"] = recipient
            msg.set_content(body_text)
            if body_html:
                msg.add_alternative(body_html, subtype="html")

            try:
                server.send_message(msg)
                sent.append(recipient)
            except Exception:
                failed.append(recipient)

    return {"sent": sent, "failed": failed}
