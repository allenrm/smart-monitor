import logging
import smtplib
import time

from email.mime.text import MIMEText
from email import charset

LOGGER = logging.getLogger()

def get_service(hostname, port, tls, username, password):
    server = None

    try:
        if tls:
            server = smtplib.SMTP_SSL(hostname, port, timeout = 3)
        else:
            server = smtplib.SMTP(hostname, port, timeout = 3)

        if username and password:
            server.login(username, password)
    except smtplib.SMTPAuthenticationError:
        LOGGER.error("Issue with login to SMTP server -> Authentication to SMTP server failed. Please check your username and password.")
        return None
    except smtplib.SMTPException:
        LOGGER.error("Issue with connecting with SMTP server -> Unable to connect to SMTP server. Please check your configuration.")
        return None
    finally:
        if server:
            server.quit()

    return MailService(hostname, port, tls, username, password)

class MailService():
    def __init__(self, hostname, port, tls, username, password):
        self.hostname = hostname
        self.port = port
        self.tls = tls
        self.username = username
        self.password = password
        self.attempts = 2

    def __connect(self):
        charset.add_charset("utf-8", charset.SHORTEST, charset.QP)

        if self.tls:
            server = smtplib.SMTP_SSL(self.hostname, self.port, timeout = 3)
        else:
            server = smtplib.SMTP(self.hostname, self.port, timeout = 3)

        if self.username and self.password:
            server.login(self.username, self.password)

        return server

    # Recommended for only sending messages sparingly otherwise SMTP providers like GMail will 
    # disconnect if too many connection attempts are made within a certain amount of time
    def send_message(self, sender, destination, subject, body):
        # Build envelope
        envelope  = MIMEText(body, "plain", "utf-8")
        envelope["Subject"] = subject
        envelope["From"] = sender
        envelope["To"] = destination

        # Send envelope
        server = self.__connect()
        for i in range(self.attempts):
            try:
                server.sendmail(sender, destination, envelope.as_string())
                break
            except smtplib.SMTPException:
                if i < self.attempts - 1:
                    LOGGER.warning("Issue with sending mail through SMTP server -> Retrying connection...")
                    server.quit()
                    time.sleep(30)
                    server = self.connect()
                else:
                    LOGGER.error("Issue with sending mail through SMTP server -> Could not connect to SMTP server!")

        server.quit()

    # Send multiple messages with the following format: {"subject" : "", "body" : ""}
    def bulk_message(self, sender, destination, messages):
        # Connection made earlier in preperation for bulk messaging
        server = self.__connect()

        for message in messages:
            # Build envelope
            envelope  = MIMEText(message["body"], "plain", "utf-8")
            envelope["Subject"] = message["subject"]
            envelope["From"] = sender
            envelope["To"] = destination

            # Send envelope
            for i in range(self.attempts):
                try:
                    server.sendmail(sender, destination, envelope.as_string())
                    break
                except smtplib.SMTPException:
                    if i < self.attempts - 1:
                        LOGGER.warning("Issue with sending mail through SMTP server -> Retrying connection...")
                        server.quit()
                        time.sleep(30)
                        server = self.connect()
                    else:
                        LOGGER.error("Issue with sending mail through SMTP server -> Could not connect to SMTP server!")

        server.quit()