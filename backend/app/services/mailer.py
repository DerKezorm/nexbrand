"""Mail through the operator's SMTP server: invitations, and the link of a review to the client.

Off until the operator enters a server: the link to copy is always enough. Nothing else is ever mailed, apart from
the operator's test mail. The invitation names who invites and into which client, and carries the link, in the
language of whoever receives it; the test mail as well. The review mail goes to someone without an account, in the
language of the person who puts the draft forward.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from sqlalchemy.orm import Session

from ..security import decrypt_secret
from . import settings_service

logger = logging.getLogger("nexbrand.mail")

TIMEOUT = 15
SECURITY = ("starttls", "tls", "none")


class MailError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def status_of(exc: MailError) -> int:
    """The answer for a mail that did not go: 409 when no mail server is set up (a setting, nothing went wrong
    outside, so no error in the log), 502 when the mail server failed."""
    return 409 if exc.code == "mail_off" else 502


def configured(db: Session) -> bool:
    values = settings_service.get_all(db)
    return bool(values["smtp_host"] and values["smtp_from"])


def _send(db: Session, message: EmailMessage) -> None:
    values = settings_service.get_all(db)
    if not (values["smtp_host"] and values["smtp_from"]):
        raise MailError("mail_off", "No mail server is set up.")
    host = str(values["smtp_host"])
    port = int(values["smtp_port"])
    security = str(values["smtp_security"])
    message["From"] = str(values["smtp_from"])
    message["Message-ID"] = make_msgid(domain=str(values["smtp_from"]).rpartition("@")[2] or None)
    # Required by RFC 5322. smtplib does not add it, and without it iCloud, Outlook and Gmail drop the mail silently.
    if "Date" not in message:
        message["Date"] = formatdate(localtime=True)
    context = ssl.create_default_context()
    try:
        if security == "tls":
            server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=TIMEOUT)
        with server:
            if security == "starttls":
                server.starttls(context=context)
            user = str(values["smtp_user"])
            if user:
                server.login(user, decrypt_secret(str(values["smtp_password_enc"])))
            server.send_message(message)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        # The reason goes to the log by its kind only: an SMTP answer can quote the address or the credentials.
        logger.warning("Mail not sent host=%s reason=%s", host, type(exc).__name__)
        raise MailError("mail_failed", "The mail server did not take the mail.") from exc
    logger.info("Mail sent host=%s", host)


#: The invitation, in the language of whoever receives it: the account that already
#: has the address; else has no language of its own, the inviter's account language, then the language
#: the inviter's page shows, else English.
INVITE_MAIL = {
    "de": {
        "subject": "{by} lädt dich zu nexbrand ein",
        "where": "zum Kunden „{space}“ in nexbrand",
        "app": "zu nexbrand",
        "body": "{by} lädt dich {where} ein. In nexbrand liegt die CI von Kunden: Farben, Schriften, Logos und "
                "Regeln.\n\nÖffne diesen Link, um die Einladung anzunehmen:\n{link}\n\n"
                "Der Link gilt einmal, bis {until}. Wenn du diese Mail nicht erwartet hast, ignoriere sie.\n",
        "date": "%d.%m.%Y",
    },
    "en": {
        "subject": "{by} invites you to nexbrand",
        "where": "to the client “{space}” in nexbrand",
        "app": "to nexbrand",
        "body": "{by} invites you {where}. nexbrand keeps the corporate design of clients: colours, fonts, logos and "
                "rules.\n\nOpen this link to accept:\n{link}\n\n"
                "The link works once, until {until}. If you did not expect this mail, ignore it.\n",
        "date": "%Y-%m-%d",
    },
}


def mail_language(*choices: str) -> str:
    """The first of ``choices`` nexbrand has mail texts for (``de-AT`` counts as ``de``); English otherwise."""
    for choice in choices:
        code = (choice or "").split("-")[0].lower()
        if code in INVITE_MAIL:
            return code
    return "en"


def send_invite(db: Session, to: str, link: str, *, by: str, space: str | None, until: datetime,
                language: str = "en") -> None:
    words = INVITE_MAIL.get(language, INVITE_MAIL["en"])
    values = {"by": _one_line(by), "link": link, "until": until.strftime(words["date"])}
    values["where"] = words["where"].format(space=_one_line(space)) if space else words["app"]
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = words["subject"].format(**values)
    message.set_content(words["body"].format(**values))
    _send(db, message)


#: The review mail, in the language of the person who puts the draft forward (English when it is neither).
REVIEW_MAIL = {
    "de": {
        "subject": "{sender}: Ihre Meinung zum neuen Auftritt von {client}",
        "body": "{sender} bittet um Ihre Meinung zum neuen Auftritt von {client}.\n\n{message}"
                "Unter diesem Link sehen Sie die Entwürfe, können sie kommentieren und einen auswählen:\n{link}\n\n"
                "Ein Konto brauchen Sie dafür nicht. Wenn Sie diese Mail nicht erwartet haben, können Sie sie "
                "ignorieren.\n",
    },
    "en": {
        "subject": "{sender}: your opinion on the new look of {client}",
        "body": "{sender} asks for your opinion on the new look of {client}.\n\n{message}"
                "This link shows the drafts; you can comment on them and choose one:\n{link}\n\n"
                "You need no account for it. If you did not expect this mail, ignore it.\n",
    },
}


def _one_line(text: str) -> str:
    """A name in a mail header: one line, no control characters."""
    return " ".join("".join(char if ord(char) >= 32 and ord(char) != 127 else " " for char in text).split())


def send_review(db: Session, to: str, link: str, *, client: str, sender: str, message: str, language: str) -> None:
    """The link of a review to the client. ``language``: a code such as ``de`` or ``de-AT``."""
    words = REVIEW_MAIL.get(language.split("-")[0].lower(), REVIEW_MAIL["en"])
    values = {"sender": _one_line(sender), "client": _one_line(client), "link": link,
              "message": f"{message.strip()}\n\n" if message.strip() else ""}
    mail = EmailMessage()
    mail["To"] = to
    mail["Subject"] = words["subject"].format(**values)
    mail.set_content(words["body"].format(**values))
    _send(db, mail)


#: The operator's test mail, in the language of whoever receives it (as the invitation).
TEST_MAIL = {
    "de": {"subject": "nexbrand: Testmail", "body": "Der Mailserver in nexbrand funktioniert.\n"},
    "en": {"subject": "nexbrand test mail", "body": "The mail server in nexbrand works.\n"},
}


def send_test(db: Session, to: str, language: str = "en") -> None:
    """``language``: as ``mail_language`` chose it (the account with the address, else the operator's)."""
    words = TEST_MAIL.get(language, TEST_MAIL["en"])
    message = EmailMessage()
    message["To"] = formataddr(("", to))
    message["Subject"] = words["subject"]
    message.set_content(words["body"])
    _send(db, message)
