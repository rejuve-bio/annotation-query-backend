import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_email(subject, recipients, body):
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.MAIL_DEFAULT_SENDER
    message["To"] = recipients
    message.set_content(body)

    context = ssl.create_default_context()
    smtp_class = smtplib.SMTP_SSL if settings.MAIL_USE_SSL else smtplib.SMTP
    options = {"context": context} if settings.MAIL_USE_SSL else {}
    port = settings.MAIL_PORT or (465 if settings.MAIL_USE_SSL else 587 if settings.MAIL_USE_TLS else 25)
    try:
        with smtp_class(settings.MAIL_SERVER, port, timeout=10, **options) as smtp:
            if settings.MAIL_USE_TLS and not settings.MAIL_USE_SSL:
                smtp.starttls(context=context)
            if settings.MAIL_USERNAME:
                smtp.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD or "")
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        logger.exception("Annotation email delivery failed")
