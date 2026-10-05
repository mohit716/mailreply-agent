"""Gmail API access for one connected account.

Tokens stay in GMAIL_TOKEN_PATH. The browser session on a desktop is not used.
"""

from __future__ import annotations

import base64
import os
from email.utils import parseaddr
from pathlib import Path

SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
)
TOKEN_PATH = Path(os.environ.get("GMAIL_TOKEN_PATH", ".gmail_token.json"))
CLIENT_SECRET = Path(os.environ.get("GMAIL_CLIENT_SECRET_FILE", "client_secret.json"))


class GmailError(Exception):
    """The mailbox could not be read or the reply could not be sent."""

    def __init__(self, message: str, *, uncertain: bool = False) -> None:
        super().__init__(message)
        self.uncertain = uncertain


def connected() -> bool:
    return TOKEN_PATH.is_file()


def run_auth() -> None:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as error:
        raise SystemExit("Install requirements.txt, then run this again.") from error
    if not CLIENT_SECRET.is_file():
        raise SystemExit(
            "Download an OAuth client secret to client_secret.json, "
            "or set GMAIL_CLIENT_SECRET_FILE."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), list(SCOPES))
    creds = flow.run_local_server(port=0, open_browser=True)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        pass
    print(f"Saved Gmail token to {TOKEN_PATH}")


def _service():
    if not TOKEN_PATH.is_file():
        raise GmailError("Gmail is not connected. Run python draft_email.py --gmail-auth.")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except ImportError as error:
        raise GmailError("Install requirements.txt, then run this again.") from error
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), list(SCOPES))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    return service, HttpError


def account_email() -> str:
    service, http_error = _service()
    try:
        profile = service.users().getProfile(userId="me").execute()
    except http_error as error:
        raise GmailError(_http_message(error)) from error
    email = (profile.get("emailAddress") or "").strip()
    if not email:
        raise GmailError("Gmail did not return the account address.")
    return email


def get_thread(thread_id: str) -> list[dict] | None:
    service, http_error = _service()
    try:
        thread = (
            service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )
    except http_error as error:
        if getattr(error, "status_code", None) == 404 or error.resp.status == 404:
            return None
        raise GmailError(_http_message(error)) from error
    return [_normalize(message) for message in thread.get("messages") or []]


def list_threads(label_id: str | None, limit: int = 10) -> list[dict]:
    service, http_error = _service()
    kwargs = {"userId": "me", "maxResults": limit}
    if label_id:
        kwargs["labelIds"] = [label_id]
    try:
        listed = service.users().threads().list(**kwargs).execute()
    except http_error as error:
        raise GmailError(_http_message(error)) from error
    choices = []
    for item in listed.get("threads") or []:
        choices.append(
            {
                "threadId": item.get("id") or "",
                "snippet": item.get("snippet") or "",
            }
        )
    return [choice for choice in choices if choice["threadId"]]


def send_raw(raw: str, thread_id: str) -> str:
    service, http_error = _service()
    try:
        sent = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": raw, "threadId": thread_id})
            .execute()
        )
    except http_error as error:
        status = getattr(error.resp, "status", 0)
        uncertain = status >= 500 or status == 0
        raise GmailError(_http_message(error), uncertain=uncertain) from error
    except (TimeoutError, OSError) as error:
        raise GmailError(
            "Gmail did not confirm the send. Check the thread before trying again.",
            uncertain=True,
        ) from error
    message_id = sent.get("id") or ""
    if not message_id:
        raise GmailError(
            "Gmail did not confirm the send. Check the thread before trying again.",
            uncertain=True,
        )
    return message_id


def _normalize(message: dict) -> dict:
    payload = message.get("payload") or {}
    headers = {
        (header.get("name") or "").lower(): header.get("value") or ""
        for header in payload.get("headers") or []
    }
    name, email = parseaddr(headers.get("from") or "")
    return {
        "id": message.get("id") or "",
        "threadId": message.get("threadId") or "",
        "internalDate": str(message.get("internalDate") or "0"),
        "labelIds": list(message.get("labelIds") or []),
        "from_name": name,
        "from_email": email,
        "subject": headers.get("subject") or "",
        "message_id_header": headers.get("message-id") or "",
        "references": headers.get("references") or "",
        "body": _plain_body(payload) or (message.get("snippet") or ""),
        "snippet": message.get("snippet") or "",
    }


def _plain_body(payload: dict) -> str:
    mime = payload.get("mimeType") or ""
    if mime == "text/plain" and payload.get("body", {}).get("data"):
        return _decode_body(payload["body"]["data"])
    for part in payload.get("parts") or []:
        text = _plain_body(part)
        if text:
            return text
    return ""


def _decode_body(data: str) -> str:
    padding = "=" * ((-len(data)) % 4)
    try:
        return base64.urlsafe_b64decode(data + padding).decode("utf-8", errors="replace")
    except (ValueError, UnicodeDecodeError):
        return ""


def _http_message(error: Exception) -> str:
    status = getattr(getattr(error, "resp", None), "status", "")
    return f"Gmail returned {status}." if status else "Gmail could not complete that request."
