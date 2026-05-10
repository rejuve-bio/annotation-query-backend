import logging
from flask_mail import Mail, Message

logger = logging.getLogger(__name__)

mail = None

def init_mail(app):
    global mail
    mail = Mail(app)

def send_email(subject, recipients, body):
    try:
        if mail is None:
            raise Exception("Can't send email")
        
        # Create the email message
        msg = Message(
            subject=subject,
            recipients=recipients,
            body=body,
        )

        # Send the email
        mail.send(msg)
        logger.info("Email sent successfully!")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")

