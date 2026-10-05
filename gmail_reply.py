"""Decide who to reply to, and keep a send from happening twice."""

from __future__ import annotations

import base64
import json
import threading
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path


def address_only(value: str) -> str:
    _name, email = parseaddr(value or "")
    return email.strip().lower()


def is_incoming(message: dict, account_email: str) -> bool:
    labels = set(message.get("labelIds") or [])
    if "DRAFT" in labels:
        return False
    sender = address_only(message.get("from_email") or "")
    account = (account_email or "").strip().lower()
    if sender and sender == account:
        return False
    if "SENT" in labels and sender == account:
        return False
    return bool(sender)


def latest_incoming(messages: list[dict], account_email: str) -> dict | None:
    incoming = [message for message in messages if is_incoming(message, account_email)]
    if not incoming:
        return None
    return max(incoming, key=lambda message: int(message.get("internalDate") or 0))


def newer_incoming(messages: list[dict], account_email: str, message_id: str) -> dict | None:
    incoming = [
        message for message in messages if is_incoming(message, account_email)
    ]
    incoming.sort(key=lambda message: int(message.get("internalDate") or 0))
    if not incoming:
        return None
    ids = [message["id"] for message in incoming]
    if message_id not in ids or ids[-1] != message_id:
        return incoming[-1]
    return None


def reply_subject(subject: str) -> str:
    text = (subject or "").strip()
    if text.lower().startswith("re:"):
        return text
    return f"Re: {text}" if text else "Re:"


def single_recipient(value: str, expected_email: str) -> str:
    text = (value or "").strip()
    if "," in text or ";" in text:
        raise ValueError("Reply goes to one person. Reply All is not used.")
    email = address_only(text) or text.lower()
    expected = (expected_email or "").strip().lower()
    if not email or email != expected:
        raise ValueError("The recipient has to be the sender of the latest message.")
    return email


def build_reply_raw(
    *,
    sender_email: str,
    to_email: str,
    subject: str,
    body: str,
    message_id_header: str,
    references: str,
) -> str:
    message = EmailMessage()
    message["From"] = sender_email
    message["To"] = to_email
    message["Subject"] = subject
    header = (message_id_header or "").strip()
    if header:
        message["In-Reply-To"] = header
        prior = (references or "").strip()
        message["References"] = f"{prior} {header}".strip()
    message.set_content(body or "")
    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    return encoded.rstrip("=")


class SendLedger:
    """Remember send attempts so a second click cannot send again."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._items = self._load()
        changed = False
        for token, item in list(self._items.items()):
            if item.get("state") == "pending":
                item["state"] = "uncertain"
                changed = True
        if changed:
            self._write()

    def get(self, token: str) -> dict | None:
        with self._lock:
            current = self._items.get(token)
            return dict(current) if current else None

    def begin(self, token: str) -> dict | None:
        with self._lock:
            current = self._items.get(token)
            if current:
                return dict(current)
            self._items[token] = {"state": "pending"}
            self._write()
            return None

    def mark_sent(self, token: str, gmail_message_id: str) -> None:
        with self._lock:
            self._items[token] = {"state": "sent", "gmail_message_id": gmail_message_id}
            self._write()

    def mark_failed(self, token: str) -> None:
        with self._lock:
            self._items.pop(token, None)
            self._write()

    def mark_uncertain(self, token: str) -> None:
        with self._lock:
            self._items[token] = {"state": "uncertain"}
            self._write()

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._items), encoding="utf-8")
        temporary.replace(self.path)
