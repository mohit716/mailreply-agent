"""Parse a Gmail web conversation URL.

The id in the address bar is not a Gmail API thread id. Some links use a
reduced-alphabet encoding of thread-f:<decimal>. That decimal is the legacy
thread number, and its hexadecimal form is the API thread id. The API must
still confirm the thread. /u/0/ is only a browser profile slot, not an email
address.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass

REDUCED = "BCDFGHJKLMNPQRSTVWXZbcdfghjklmnpqrstvwxz"
FULL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

_URL = re.compile(
    r"^https://mail\.google\.com/mail(?:/u/(?P<index>\d+))?/(?:.*?)#(?P<fragment>.+)$",
    re.IGNORECASE,
)
_SYNC = re.compile(r"^[B-DF-HJ-NP-TV-Zb-df-hj-np-tv-z]{16,}$")
_HEX = re.compile(r"^[0-9a-fA-F]{15,16}$")

_LABELS = {
    "inbox": "INBOX",
    "sent": "SENT",
    "drafts": "DRAFT",
    "imp": "IMPORTANT",
    "important": "IMPORTANT",
    "starred": "STARRED",
    "spam": "SPAM",
    "trash": "TRASH",
}


@dataclass(frozen=True)
class GmailLink:
    account_index: str | None
    label_id: str | None
    sync_id: str | None
    api_thread_id: str | None


def parse_gmail_url(url: str) -> GmailLink:
    text = (url or "").strip()
    match = _URL.match(text)
    if not match:
        raise ValueError("Paste a Gmail conversation link.")
    fragment = match.group("fragment").split("?", 1)[0]
    parts = [part for part in fragment.split("/") if part]
    if not parts:
        raise ValueError("That link does not include a conversation.")
    label_id = _label(parts[0])
    token = parts[-1]
    sync_id = None
    api_thread_id = None
    if _HEX.fullmatch(token):
        api_thread_id = token.lower()
    elif _SYNC.fullmatch(token):
        sync_id = token
        api_thread_id = api_id_from_sync(token)
    else:
        raise ValueError("That link does not include a conversation id.")
    return GmailLink(
        account_index=match.group("index"),
        label_id=label_id,
        sync_id=sync_id,
        api_thread_id=api_thread_id,
    )


def _label(segment: str) -> str | None:
    return _LABELS.get(segment.lower())


def api_id_from_sync(token: str) -> str | None:
    """Return a hex API thread id when the token is a thread-f value."""
    try:
        number = 0
        for char in token:
            number = number * len(REDUCED) + REDUCED.index(char)
        digits: list[int] = []
        value = number
        while value:
            value, remainder = divmod(value, 64)
            digits.append(remainder)
        digits.reverse()
        encoded = "".join(FULL[digit] for digit in digits)
        padding = "=" * ((-len(encoded)) % 4)
        decoded = base64.b64decode(encoded + padding).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    if decoded.startswith("f:"):
        decoded = "thread-" + decoded
    marker = "thread-f:"
    if not decoded.startswith(marker):
        return None
    decimal = decoded[len(marker) :]
    if not decimal.isdigit():
        return None
    return format(int(decimal), "x")
