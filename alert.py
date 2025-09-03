import smtplib
from email.message import EmailMessage

from configuration import botAlert, mailConfig

class BotFailedError(Exception):
    """Custom exception for bot failures."""
    pass

class Mail:
    def send(self, subject, message):
        msg = EmailMessage()
        msg.set_content(message)

        msg["Subject"] = subject
        msg["From"] = mailConfig["from"]
        msg["To"] = mailConfig["to"]

        s = smtplib.SMTP(mailConfig["smtp"], mailConfig["port"], None, 3)
        s.login(mailConfig["username"], mailConfig["password"])

        try:
            s.send_message(msg)
            try:
                from status import notify
                notify('Sent alert "' + message + '" via email')
            except Exception:
                print('Sent alert "' + message + '" via email')
        finally:
            s.quit()


def alert(asset, message, isError=False):
    if botAlert == "email":
        msg = EmailMessage()
        msg.set_content(message)

        if isError:
            subj = "OPI Error"
        else:
            subj = "OPI Alert"

        if asset:
            subj = subj + ", Asset: " + asset

        mail = Mail()
        mail.send(subj, message)

        if isError:
            raise BotFailedError(message)
    else:
        if asset:
            try:
                from status import notify
                notify("Asset: " + asset)
            except Exception:
                print("Asset: " + asset)

        try:
            from status import notify
            notify(message)
        except Exception:
            print(message)

        if isError:
            raise BotFailedError(message)


def botFailed(asset, message):
    return alert(asset, message, True)
