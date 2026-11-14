"""Deliver node: email the EPUB to the Kindle address, only when SEND=1.

Pure transport: a script. Gmail SMTP with an app password (see CLAUDE.md, J0).
"""

import os
import smtplib
import ssl
import time
from email.message import EmailMessage
from pathlib import Path

from digest.state import DigestState, NodeMetrics, SourceError

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587  # STARTTLS


def build_message(epub_path: Path, sender: str, recipient: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = epub_path.stem
    message.set_content("Journal du jour en pièce jointe.")
    message.add_attachment(
        epub_path.read_bytes(), maintype="application", subtype="epub+zip",
        filename=epub_path.name,
    )
    return message


def deliver(state: DigestState) -> dict:
    start = time.perf_counter()
    enabled = os.environ.get("SEND") == "1"  # off by default: no accidental email in dev
    sent, errors = 0, []

    if enabled:
        # Broad except on purpose: a failed email is recorded, and the run report
        # is still written. Only the error type is kept: never a credential in the logs.
        try:
            sender = os.environ["SMTP_USER"]
            message = build_message(Path(state["epub_path"]), sender, os.environ["KINDLE_EMAIL"])
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
                # Explicit context: smtplib's default one does not check the certificate.
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
                # AUTH LOGIN rather than login()'s first choice (PLAIN): on bad credentials,
                # Gmail hangs up on PLAIN (observed 2026-11-14) but answers LOGIN with a "535".
                smtp.user, smtp.password = sender, os.environ["SMTP_APP_PASSWORD"]
                smtp.auth("LOGIN", smtp.auth_login)
                smtp.send_message(message)
            sent = 1
        except smtplib.SMTPResponseException as e:
            # The SMTP code (e.g. 535: credentials refused) says what went wrong.
            errors.append(SourceError("deliver", f"{type(e).__name__} {e.smtp_code}"))
        except Exception as e:  # noqa: BLE001
            errors.append(SourceError("deliver", type(e).__name__))

    metrics = NodeMetrics(
        "deliver", round(time.perf_counter() - start, 3), {"enabled": int(enabled), "sent": sent}
    )
    return {"errors": errors, "metrics": [metrics]}
