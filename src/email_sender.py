from __future__ import annotations

import os
import re
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Mapping


@dataclass(frozen=True)
class EmailSettings:
    host: str
    port: int
    username: str
    password: str = field(repr=False)
    sender: str = ""
    recipients: tuple[str, ...] = ()
    security: str = "ssl"
    timeout_seconds: int = 30


def settings_from_env(env: Mapping[str, str] | None = None) -> EmailSettings:
    values = os.environ if env is None else env
    host = values.get("SMTP_HOST", "").strip()
    username = values.get("SMTP_USERNAME", "").strip()
    password = values.get("SMTP_PASSWORD", "").strip()
    sender = values.get("EMAIL_FROM", "").strip() or username
    recipients = tuple(
        address.strip()
        for address in re.split(r"[,;]", values.get("EMAIL_TO", ""))
        if address.strip()
    )

    missing = [
        name
        for name, value in (
            ("SMTP_HOST", host),
            ("SMTP_USERNAME", username),
            ("SMTP_PASSWORD", password),
            ("EMAIL_FROM", sender),
            ("EMAIL_TO", recipients),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing email environment variables: {', '.join(missing)}")

    try:
        port = int(values.get("SMTP_PORT", "465"))
        timeout_seconds = int(values.get("SMTP_TIMEOUT_SECONDS", "30"))
    except ValueError as exc:
        raise RuntimeError("SMTP_PORT and SMTP_TIMEOUT_SECONDS must be integers.") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("SMTP_PORT must be between 1 and 65535.")
    if timeout_seconds <= 0:
        raise RuntimeError("SMTP_TIMEOUT_SECONDS must be greater than zero.")

    security = values.get("SMTP_SECURITY", "ssl").strip().casefold()
    if security not in {"ssl", "starttls"}:
        raise RuntimeError("SMTP_SECURITY must be 'ssl' or 'starttls'.")

    for header_value in (sender, *recipients):
        if "\r" in header_value or "\n" in header_value:
            raise RuntimeError("Email addresses must not contain line breaks.")

    return EmailSettings(
        host=host,
        port=port,
        username=username,
        password=password,
        sender=sender,
        recipients=recipients,
        security=security,
        timeout_seconds=timeout_seconds,
    )


def send_html_email(
    html: str,
    subject: str,
    settings: EmailSettings | None = None,
) -> None:
    settings = settings or settings_from_env()
    normalized_subject = " ".join(subject.splitlines()).strip()
    if not normalized_subject:
        raise RuntimeError("Email subject must not be empty.")

    message = EmailMessage()
    message["Subject"] = normalized_subject
    message["From"] = settings.sender
    message["To"] = ", ".join(settings.recipients)
    message.set_content("This message contains an HTML public-affairs news digest.")
    message.add_alternative(html, subtype="html")

    tls_context = ssl.create_default_context()
    if settings.security == "ssl":
        with smtplib.SMTP_SSL(
            settings.host,
            settings.port,
            timeout=settings.timeout_seconds,
            context=tls_context,
        ) as client:
            _deliver(client, message, settings)
        return

    with smtplib.SMTP(settings.host, settings.port, timeout=settings.timeout_seconds) as client:
        client.ehlo()
        client.starttls(context=tls_context)
        client.ehlo()
        _deliver(client, message, settings)


def _deliver(client: smtplib.SMTP, message: EmailMessage, settings: EmailSettings) -> None:
    client.login(settings.username, settings.password)
    client.send_message(message, from_addr=settings.sender, to_addrs=list(settings.recipients))
