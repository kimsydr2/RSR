"""Delivery: email via SMTP, SMS via carrier email-to-SMS gateways (free, no
Twilio account needed). dry_run prints + logs instead of sending."""
from __future__ import annotations
import os
import smtplib
from email.message import EmailMessage

SMS_GATEWAYS = {
    "verizon": "vtext.com",
    "att": "txt.att.net",
    "tmobile": "tmomail.net",
    "sprint": "messaging.sprintpcs.com",
    "uscellular": "email.uscc.net",
    "googlefi": "msg.fi.google.com",
}
SMS_MAX = 300


class Sender:
    def __init__(self, cfg, log_path: str = "outbox_log.txt"):
        self.cfg = cfg
        self.log_path = log_path
        self.sent = []   # (address, subject, body) — handy for tests and demos

    def addresses(self, contact) -> list[tuple[str, bool]]:
        """-> [(address, is_sms)]"""
        out = []
        if contact.channel in ("email", "both") and contact.email:
            out.append((contact.email, False))
        if contact.channel in ("sms", "both") and contact.phone:
            gw = SMS_GATEWAYS.get((contact.carrier or "").lower())
            if gw:
                out.append((f"{contact.phone}@{gw}", True))
        if not out and contact.email:       # fall back rather than drop the message
            out.append((contact.email, False))
        return out

    def send(self, contact, subject: str, body: str):
        for addr, is_sms in self.addresses(contact):
            text = (f"{subject}: {body}")[:SMS_MAX] if is_sms else body
            subj = "" if is_sms else subject
            self.sent.append((addr, subj, text))
            if self.cfg.dry_run:
                line = f"[DRY RUN] to={addr} | {subj} | {text}".replace("\n", " / ")
                print(line)
                with open(self.log_path, "a") as f:
                    f.write(line + "\n")
            else:
                self._smtp(addr, subj, text)

    def _smtp(self, to, subject, body):
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.cfg.email_from, to, subject
        msg.set_content(body)
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", 587))) as s:
            s.starttls()
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
            s.send_message(msg)
