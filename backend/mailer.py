"""Sends email through any SMTP server, such as Gmail with an app password.

Without SMTP_HOST in .env nothing is sent: the message is printed in the server console instead, so the forgot
password flow can still be tried on a local copy. Never leave it that way on a server other people use.
"""
import logging
import smtplib
import ssl
from email.message import EmailMessage

from .settings import settings

log = logging.getLogger("verixa.mail")


def configured() -> bool:
    return bool(settings.smtp_host)


def send_email(to: str, subject: str, text: str) -> None:
    """Runs after the reply has been sent, so a slow or broken mail server never shows in the answer."""
    if not configured():
        log.warning("Email is not set up (SMTP_HOST is empty), so this was not sent.\nTo: %s\nSubject: %s\n\n%s",
                    to, subject, text)
        return
    message = EmailMessage()
    message["From"] = settings.mail_from or settings.smtp_user
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    context = ssl.create_default_context()
    try:
        if settings.smtp_port == 465:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=20)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
            server.starttls(context=context)
        with server:
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
        log.info("Sent '%s' to %s", subject, to)
    except Exception as exc:  # the person already saw "check your inbox", so this can only be logged
        log.error("Could not send '%s' to %s: %s: %s", subject, to, type(exc).__name__, exc)
