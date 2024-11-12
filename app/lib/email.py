import logging
from flask_mail import Mail, Message

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
        logging.info("Email sent successfully!")
    except Exception as e:
        logging.error(f"Failed to send email: {e}")

