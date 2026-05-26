from __future__ import annotations

import email
import imaplib
import time
from datetime import UTC, datetime
from email.header import decode_header

from patina.models import EmailMessage


class ImapEmailAdapter:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_ssl: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_ssl = use_ssl

    @property
    def platform(self) -> str:
        return "imap"

    def _connect(self) -> imaplib.IMAP4 | imaplib.IMAP4_SSL:
        if self._use_ssl:
            conn = imaplib.IMAP4_SSL(self._host, self._port)
        else:
            conn = imaplib.IMAP4(self._host, self._port)
        conn.login(self._username, self._password)
        return conn

    def _decode_header_value(self, raw: str) -> str:
        parts = decode_header(raw)
        result = []
        for data, charset in parts:
            if isinstance(data, bytes):
                result.append(data.decode(charset or "utf-8", errors="replace"))
            else:
                result.append(data)
        return " ".join(result)

    def _parse_message(self, raw_bytes: bytes) -> EmailMessage | None:
        msg = email.message_from_bytes(raw_bytes)

        sender = self._decode_header_value(msg.get("From", ""))
        subject = self._decode_header_value(msg.get("Subject", ""))
        msg_id = msg.get("Message-ID", "")
        in_reply_to = msg.get("In-Reply-To")

        date_str = msg.get("Date", "")
        try:
            ts = email.utils.parsedate_to_datetime(date_str).timestamp()
        except Exception:
            ts = time.time()

        to_raw = msg.get("To", "")
        recipients = [r.strip() for r in to_raw.split(",") if r.strip()]

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="replace")
                    break
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode("utf-8", errors="replace")

        return EmailMessage(
            id=msg_id,
            sender=sender,
            subject=subject,
            text=body,
            timestamp=ts,
            recipients=recipients,
            conversation_id=in_reply_to,
        )

    def list_inbox(self, since: float) -> list[EmailMessage]:
        conn = self._connect()
        try:
            conn.select("INBOX")
            since_date = datetime.fromtimestamp(since, tz=UTC).strftime("%d-%b-%Y")
            _, data = conn.search(None, f'(SINCE "{since_date}")')
            msg_ids = data[0].split() if data[0] else []

            results: list[EmailMessage] = []
            for mid in msg_ids[-200:]:
                _, msg_data = conn.fetch(mid, "(RFC822)")
                if msg_data and msg_data[0] and isinstance(msg_data[0], tuple):
                    parsed = self._parse_message(msg_data[0][1])
                    if parsed and parsed.timestamp >= since:
                        results.append(parsed)
            return results
        finally:
            conn.logout()

    def search_sent(self, query: str) -> list[EmailMessage]:
        conn = self._connect()
        try:
            conn.select('"[Gmail]/Sent Mail"')
            _, data = conn.search(None, f'(SUBJECT "{query}")')
            msg_ids = data[0].split() if data[0] else []

            results: list[EmailMessage] = []
            for mid in msg_ids[-100:]:
                _, msg_data = conn.fetch(mid, "(RFC822)")
                if msg_data and msg_data[0] and isinstance(msg_data[0], tuple):
                    parsed = self._parse_message(msg_data[0][1])
                    if parsed:
                        results.append(parsed)
            return results
        finally:
            conn.logout()
