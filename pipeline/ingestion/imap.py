from __future__ import annotations

import email
import imaplib
import logging
import re
from datetime import datetime, timedelta, timezone
from email.message import Message

from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

DEFAULT_LABEL = "syndicate"
DEFAULT_LOOKBACK_DAYS = 1


def select_label(imap: imaplib.IMAP4_SSL, label: str = DEFAULT_LABEL, readonly: bool = True) -> int:
    mailbox = f'"{label}"'
    typ, data = imap.select(mailbox, readonly=readonly)
    if typ != "OK":
        raise RuntimeError(f"Could not select label {label!r}: {data!r}")
    return int(data[0])


def search_uids(
    imap: imaplib.IMAP4_SSL,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    gmail_raw: str | None = None,
) -> list[bytes]:
    if gmail_raw:
        typ, data = imap.uid("SEARCH", "X-GM-RAW", f'"{gmail_raw}"')
    else:
        days = max(1, lookback_days)
        since_date = (datetime.now(timezone.utc) - timedelta(days=days - 1)).strftime("%d-%b-%Y")
        typ, data = imap.uid("SEARCH", None, "SINCE", since_date)
    if typ != "OK":
        raise RuntimeError(f"IMAP search failed: {data!r}")
    raw = (data[0] or b"").split()
    return raw


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def fetch_message(imap: imaplib.IMAP4_SSL, uid: bytes) -> tuple[Message, dict]:
    typ, data = imap.uid("FETCH", uid, "(RFC822 X-GM-MSGID X-GM-THRID X-GM-LABELS)")
    if typ != "OK" or not data or not data[0]:
        raise RuntimeError(f"Fetch failed for UID {uid!r}: {data!r}")

    raw_bytes = b""
    meta_blob = b""
    for part in data:
        if isinstance(part, tuple):
            meta_blob = part[0]
            raw_bytes = part[1]
            break
    msg = email.message_from_bytes(raw_bytes)
    meta = _parse_gmail_meta(meta_blob.decode("utf-8", errors="replace"))
    return msg, meta


_META_RE = re.compile(r"X-GM-(MSGID|THRID|LABELS)\s+(\([^)]*\)|\S+)", re.I)


def _parse_gmail_meta(blob: str) -> dict:
    out: dict[str, object] = {}
    for m in _META_RE.finditer(blob):
        key = m.group(1).upper()
        val = m.group(2).strip()
        if key == "LABELS":
            inner = val.strip("()")
            labels = [t.strip().strip('"') for t in inner.split() if t.strip()]
            out["labels"] = labels
        else:
            out[key.lower()] = val
    return out


def extract_html_payload(msg: Message) -> tuple[str, str]:
    html = ""
    text = ""

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if part.get_content_disposition() == "attachment":
                continue
            if ctype == "text/html" and not html:
                html = _decode_part(part)
            elif ctype == "text/plain" and not text:
                text = _decode_part(part)
    else:
        ctype = msg.get_content_type()
        body = _decode_part(msg)
        if ctype == "text/html":
            html = body
        else:
            text = body

    return html, text


def _decode_part(part: Message) -> str:
    raw = part.get_payload(decode=True)
    if raw is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")


def get_header(msg: Message, name: str) -> str:
    val = msg.get(name, "")
    if not val:
        return ""
    decoded_parts = email.header.decode_header(val)
    chunks: list[str] = []
    for chunk, enc in decoded_parts:
        if isinstance(chunk, bytes):
            try:
                chunks.append(chunk.decode(enc or "utf-8", errors="replace"))
            except LookupError:
                chunks.append(chunk.decode("utf-8", errors="replace"))
        else:
            chunks.append(chunk)
    return "".join(chunks).strip()


def add_labels(imap: imaplib.IMAP4_SSL, uid: bytes, labels: list[str]) -> None:
    if not labels:
        return
    quoted = " ".join(f'"{lbl}"' for lbl in labels)
    typ, data = imap.uid("STORE", uid, "+X-GM-LABELS", f"({quoted})")
    if typ != "OK":
        raise RuntimeError(f"Failed to add labels {labels} to {uid!r}: {data!r}")


def mark_read(imap: imaplib.IMAP4_SSL, uid: bytes) -> None:
    typ, data = imap.uid("STORE", uid, "+FLAGS", "(\\Seen)")
    if typ != "OK":
        raise RuntimeError(f"Failed to mark {uid!r} read: {data!r}")
