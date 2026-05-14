from __future__ import annotations

import imaplib
import logging
import os
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger(__name__)

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993


class AuthError(RuntimeError):
    pass


def _load_env() -> tuple[str, str]:
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
    user = os.environ.get("GMAIL_USER", "").strip()
    pw = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    if not user or not pw:
        raise AuthError(
            f"GMAIL_USER and GMAIL_APP_PASSWORD must be set (in env or {ENV_PATH}). "
            "Generate an app password at https://myaccount.google.com/apppasswords"
        )
    return user, pw


def connect() -> imaplib.IMAP4_SSL:
    user, pw = _load_env()
    log.info("Connecting to %s as %s", IMAP_HOST, user)

    try:
        imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=60)
    except (TimeoutError, OSError) as e:
        raise AuthError(f"IMAP connect timed out / failed: {e}") from e
    try:
        imap.login(user, pw)
    except imaplib.IMAP4.error as e:
        raise AuthError(f"IMAP login failed: {e}") from e
    except (TimeoutError, OSError) as e:
        raise AuthError(f"IMAP login timed out: {e}") from e
    log.info("IMAP login OK")
    return imap


@contextmanager
def session():
    imap = connect()
    try:
        yield imap
    finally:
        try:
            imap.logout()
        except Exception:
            pass
